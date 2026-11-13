######
# Same overlapping windows as test_002, but now both lambdas are inside their upsert transaction at the same time:
#
#   time  Lambda 1                                       Lambda 2
#   ----  ---------------------------------------------  -----------------------------------------------------------
#   t1    BEGIN, classify on snapshot S0 -> 'insert'     BEGIN, classify on snapshot S0 -> 'insert'
#   t2    MERGE: writes Lambda 1's data files to S3
#   t3    COMMIT: table S0 -> S1, Lambda 1's files live
#   t4                                                   MERGE: writes Lambda 2's data files to S3
#   t5                                                   COMMIT: expects S0, table is at S1 -> 409,
#                                                        Lambda 2's data files are deleted, never visible
#         ---- Lambda 2's upsert retries the whole transaction ----
#   t6                                                   BEGIN, classify on S1 -> 'refetch', re-reads from Stripe
#   t7                                                   MERGE: writes Lambda 2's new data files to S3
#   t8                                                   COMMIT: table S1 -> S2 (ok)
#
# MERGE writes the data files, COMMIT only publishes them: the catalog atomically swaps the table's pointer to a new
# metadata.json, but only if the table is still at the snapshot the transaction read (optimistic concurrency).
# Until then, nobody else reads those files. So it doesn't matter when Lambda 2 writes its data files: even at t2,
# alongside Lambda 1, its COMMIT would still fail at t5. The test runs Lambda 2's MERGE after Lambda 1's COMMIT only
# to fix the order of the commits.
#
# Both classify against the same (empty) snapshot S0, so both decide 'insert', neither sees the other's row and nobody
# re-reads from Stripe. That decision is outdated by the time Lambda 2 commits: the catalog rejects its commit (409)
# instead of letting it overwrite Lambda 1's row.
#
# The retry runs classify -> MERGE -> COMMIT again, not just the commit: on S1 it sees Lambda 1's row, the windows
# overlap, it re-reads the object from Stripe and the fresh read wins. Nothing from the rejected attempt is reused.

# This also covers concurrent inserts of a new object: both lambdas decide 'insert' at t1, and only the 409 keeps the
# table from ending up with two rows for the same id. That needs 'commit.retry.num-retries' = '0
import threading
from concurrent.futures.thread import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest
from dateutil.tz import UTC

from common import iceberg
from common.fetched_object import FetchedObject
from tests.stripe_samples import subscription, thin_event_customer_subscription_updated, sqs_batch
import reconciliation.reconciliation_lambda as recon_lambda_module
import stripe_events.stripe_events_lambda as stripe_event_lambda_module
from reconciliation.reconciliation_lambda import lambda_handler as recon_lambda_handler
from stripe_events.stripe_events_lambda import lambda_handler as stripe_event_lambda_handler


SUB_ID = "ID__OVERLAP__002"
STALE_STATUS = "trialing"
FRESH_STATUS = "active"  # also the state Stripe returns when the object is read again


@pytest.mark.parametrize("newer_holder", ["recon", "event"])
@pytest.mark.parametrize("first_commit", ["recon", "event"])
def test_overlapping_windows_concurrent_commit(newer_holder, first_commit,
                                               mock_event_lambda_stripe_lookup, mock_recon_lambda_list_all_subs_stripe,
                                               monkeypatch):
    t0 = datetime.now(UTC)
    event_status, recon_status = (STALE_STATUS, FRESH_STATUS) if newer_holder == "recon" else (FRESH_STATUS, STALE_STATUS)

    mock_event_lambda_stripe_lookup(subscription(SUB_ID, event_status),
                                    requested_at=t0, received_at=t0 + timedelta(seconds=10))

    mock_recon_lambda_list_all_subs_stripe(subscription(SUB_ID, recon_status),
                                           requested_at=t0 + timedelta(seconds=1), received_at=t0 + timedelta(seconds=10))

    ##### Re-reads from Stripe: the object as it is now, read after both windows above
    def refetch(sub_id):
        return FetchedObject(subscription(sub_id, FRESH_STATUS), t0 + timedelta(seconds=20), t0 + timedelta(seconds=21))

    monkeypatch.setattr(recon_lambda_module, "lookup_subscription_with_read_window", refetch)
    # Event lambda's first lookup is the mock above, any later lookup (re-read, or the retried invocation) is fresh
    event_lookups = iter([stripe_event_lambda_module.lookup_subscription_with_read_window])
    monkeypatch.setattr(stripe_event_lambda_module, "lookup_subscription_with_read_window",
                        lambda sub_id: next(event_lookups, refetch)(sub_id))

    # Created up front, so the two lambdas only race on the row, not on CREATE TABLE
    with iceberg.connect_s3_tables() as conn:
        iceberg.create_table_if_not_exists(conn, "subscription",
                                           iceberg.load_iceberg_schema("subscription")["schema"]
                                           | iceberg.REQUEST_WINDOW_METADATA_FIELDS)

    ##### Hold both lambdas inside their transaction (right after classify), then let them commit in a fixed order
    real_upsert, real_classify = iceberg.upsert, iceberg.classify
    both_classified = threading.Barrier(2)
    first_committed = threading.Event()
    role = threading.local()

    def racing_classify(*args):
        result = real_classify(*args)
        if getattr(role, "name", None) and not getattr(role, "classified", False):  # only the first classify per lambda
            role.classified = True
            both_classified.wait(10)  # both transactions now read the same snapshot
            if role.name == "second":
                assert first_committed.wait(10), "Timed out when waiting for the other lambda to commit"
        return result

    def upsert_as(name):
        def wrapped(conn, table, objects, refetch_object):
            role.name = name
            try:
                return real_upsert(conn, table, objects, refetch_object)
            finally:
                if name == "first":
                    first_committed.set()  # also on failure, so the other lambda doesn't hang until the timeout
        return wrapped

    monkeypatch.setattr(iceberg, "classify", racing_classify)
    monkeypatch.setattr(recon_lambda_module, "upsert", upsert_as("first" if first_commit == "recon" else "second"))
    monkeypatch.setattr(stripe_event_lambda_module, "upsert", upsert_as("first" if first_commit == "event" else "second"))
    #####
    with ThreadPoolExecutor(max_workers=2) as executor:
        recon_future = executor.submit(recon_lambda_handler, {}, None)
        event_future = executor.submit(stripe_event_lambda_handler, sqs_batch(thin_event_customer_subscription_updated(SUB_ID)), None)

    # re-raise any exception from the lambda's thread
    stats = {"recon": recon_future.result()["body"]["subscription"],
             "event": event_future.result()["body"]["subscription"]}
    second_commit = "event" if first_commit == "recon" else "recon"

    assert stats[first_commit]["conflict_retries"] == 0
    # 409 on the first attempt; the retry sees the first lambda's row, the windows overlap, so it re-reads from Stripe
    assert stats[second_commit]["conflict_retries"] == 1
    assert stats[second_commit]["refetch"] == 1

    conn = iceberg.connect_s3_tables()
    actual = conn.execute(f"SELECT status FROM {iceberg.target_table('subscription')} WHERE id = ?", [SUB_ID]).fetchall()
    assert len(actual) == 1, f"expected exactly one row for {SUB_ID}, got {actual} (apache/iceberg#18758?)"
    assert actual == [(FRESH_STATUS,)]
