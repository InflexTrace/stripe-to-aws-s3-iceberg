import threading
from datetime import datetime, timedelta, timezone
from concurrent.futures.thread import ThreadPoolExecutor

from common.iceberg import connect_s3_tables, target_table
from stripe_events.stripe_events_lambda import lambda_handler as stripe_event_lambda_handler
from reconciliation.reconciliation_lambda import lambda_handler as reconciliation_lambda_handler
from stripe_samples import subscription, thin_event_customer_subscription_updated, sqs_batch


def test_001_provably_older_stale_overwrite(mock_event_lambda_stripe_lookup, mock_recon_lambda_list_all_subs_stripe, monkeypatch):
    """
    Race condition tested:

    1. Recon Lambda calls fetch_all_subscriptions() and retrieves object with  'trialing' state
    2. Event Lambda calls lookup_subscription(), retrieves object with 'active' state and does upsert() with that 'active' state
    3. Recon Lambda upserts 'trialing' state (state at this point). It should NOT overwrite 'active', which is the most recent version of the object.
    """
    SUB_ID = "sub_race"
    STALE_STATUS = "trialing"  # recon's listing, read before the update
    FRESH_STATUS = "active"  # event lambda's lookup, read after the update

    # Recon's listing is read strictly before the event lambda's lookup (non-overlapping windows)
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    mock_recon_lambda_list_all_subs_stripe(subscription(SUB_ID, STALE_STATUS),
                                           requested_at=t0, received_at=t0 + timedelta(seconds=1))
    mock_event_lambda_stripe_lookup(subscription(SUB_ID, FRESH_STATUS),
                                    requested_at=t0 + timedelta(seconds=2), received_at=t0 + timedelta(seconds=3))

    import reconciliation.reconciliation_lambda as reconciliation_lambda_module
    real_upsert = reconciliation_lambda_module.upsert

    event_lambda_completed = threading.Event()
    def waiting_upsert(conn, table, objects, extra_upsert_conditions):
        assert event_lambda_completed.wait(timeout=10), "Reconciliation lambda waited for stripe event lambda and timed out"
        return real_upsert(conn, table, objects, extra_upsert_conditions)

    monkeypatch.setattr(reconciliation_lambda_module, "upsert", waiting_upsert)

    with ThreadPoolExecutor(max_workers=1) as executor:
        batch_lambda_future = executor.submit(reconciliation_lambda_handler, {}, None)

        stripe_event_lambda_handler(sqs_batch(thin_event_customer_subscription_updated(SUB_ID)), None)
        event_lambda_completed.set()

        batch_result = batch_lambda_future.result() #   re-raises the assertion/any exception from the thread

    conn = connect_s3_tables()
    result = conn.execute( f"SELECT status FROM {target_table('subscription')} WHERE id = ?", [SUB_ID]).fetchall()
    assert result == [(FRESH_STATUS,)] , f"expected exactly one fresh row, got {result}"

