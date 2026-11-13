######
# Let's consider edge case when both lambdas retrieve the same object at the approximately the same time
#
# When request/response windows for both lambdas do not overlap, we know that:
#    most recent object version  was retrieved by lambda with request start time > response received time (of the other lambda)
# For example, in this case Lambda 2 possesses more recent version of object
#
# Lambda 1: ----> Request time --------> Response time
# Lambda 2: -----------------------------------------------> Request time --------> Response time

# However, when they do overlap, we can't immediately know which lambda fetched most recent object version
# For example:
#
# Lambda 1: ----> Request time -----------------------------------------------> Response time
# Lambda 2: --------------------------> Request time -------------------------> Response time
#
# The windows below are the same whichever lambda holds the newer version, so the windows alone can't decide.
# The lambda that writes second sees the overlap and re-reads the object from Stripe; its fresh read starts after
# both windows, so it is provably newer and wins, whichever lambda holds the newer version and whichever commits first.


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


SUB_ID = "ID__OVERLAP__001"
STALE_STATUS = "trialing"
FRESH_STATUS = "active"  # also the state Stripe returns when the object is read again


@pytest.mark.parametrize("newer_holder", ["recon", "event"])
@pytest.mark.parametrize("first_commit", ["recon", "event"])
def test_overlapping_windows_refetch(newer_holder, first_commit,
                                     mock_event_lambda_stripe_lookup, mock_recon_lambda_list_all_subs_stripe, monkeypatch):
    t0 = datetime.now(UTC)
    event_status, recon_status = (STALE_STATUS, FRESH_STATUS) if newer_holder == "recon" else (FRESH_STATUS, STALE_STATUS)

    mock_event_lambda_stripe_lookup(subscription(SUB_ID, event_status),
                                    requested_at=t0, received_at=t0 + timedelta(seconds=10))

    mock_recon_lambda_list_all_subs_stripe(subscription(SUB_ID, recon_status),
                                           requested_at=t0 + timedelta(seconds=1), received_at=t0 + timedelta(seconds=10))

    ##### Re-reads from Stripe: the object as it is now, read after both windows above
    refetched_ids = []

    def refetch(sub_id):
        refetched_ids.append(sub_id)
        return FetchedObject(subscription(sub_id, FRESH_STATUS),
                             t0 + timedelta(seconds=20), t0 + timedelta(seconds=21))

    # Recon only looks objects up by id to re-read them
    monkeypatch.setattr(recon_lambda_module, "lookup_subscription_with_read_window", refetch)
    # Event lambda looks up the object once for the event (the mock above), any later lookup is a re-read
    event_lookups = iter([stripe_event_lambda_module.lookup_subscription_with_read_window])
    monkeypatch.setattr(stripe_event_lambda_module, "lookup_subscription_with_read_window",
                        lambda sub_id: next(event_lookups, refetch)(sub_id))

    ##### Control which upsert commits first
    real_upsert = iceberg.upsert
    first_committed = threading.Event()

    def first_upsert(conn, table, objects, refetch_object):
        try:
            return real_upsert(conn, table, objects, refetch_object)
        finally:
            first_committed.set()  # also on failure, so the other lambda doesn't hang until the timeout

    def second_upsert(conn, table, objects, refetch_object):
        assert first_committed.wait(30), "Timed out when waiting for first upsert to complete"
        return real_upsert(conn, table, objects, refetch_object)

    monkeypatch.setattr(recon_lambda_module, "upsert", first_upsert if first_commit == "recon" else second_upsert)
    monkeypatch.setattr(stripe_event_lambda_module, "upsert", first_upsert if first_commit == "event" else second_upsert)
    #####
    with ThreadPoolExecutor(max_workers=2) as executor:
        recon_future = executor.submit(recon_lambda_handler, {}, None)
        event_future = executor.submit(stripe_event_lambda_handler, sqs_batch(thin_event_customer_subscription_updated(SUB_ID)), None)

    recon_future.result()  # re-raises any exception from the lambda's thread
    event_future.result()

    conn = iceberg.connect_s3_tables()
    actual = conn.execute(f"SELECT status FROM {iceberg.target_table('subscription')} WHERE id = ?", [SUB_ID]).fetchall()
    assert actual == [(FRESH_STATUS,)]
    assert refetched_ids == [SUB_ID], "only the second writer should see the overlap and re-read the object"
