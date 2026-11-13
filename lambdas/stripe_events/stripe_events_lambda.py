import logging
import json
from collections import defaultdict

from common.stripe_client import lookup_subscription_with_read_window
from common.iceberg import connect_s3_tables, upsert

logger = logging.getLogger()
logger.setLevel("INFO")


def subscription_id(event):
    # detail is the thin event: {id, type, created, related_object: {id, type, url}, ...}
    obj = event['detail']['related_object']
    if obj['type'] != 'subscription':
        raise ValueError(f"Unsupported event: {event['detail-type']}")

    return obj['id']


def lambda_handler(event, context):
    """Invoked by the SQS event source mapping with a batch of SQS messages, each holding one EventBridge event.

    Thin events carry only a reference to the subscription, so its state is always fetched. That's needed anyway, because Stripe says:
    "Stripe doesn’t guarantee the delivery of events in the order that they’re generated. "
    and
    "Make sure that your event destination isn’t dependent on receiving events in a specific order." (see https://docs.stripe.com/webhooks)
    Hence, we're retrieving a state of object as it is right now to avoid late arrival issues. For the same reason, a
    subscription with several events in the batch is looked up once: every lookup would return the same current state.

    All subscriptions of the batch are upserted in one MERGE (one Iceberg commit)
    """
    logger.info('## EVENT')
    logger.info(json.dumps(event))

    failed_message_ids = []
    message_ids_by_sub = defaultdict(list)
    for record in event["Records"]:
        try:
            message_ids_by_sub[subscription_id(json.loads(record["body"]))].append(record["messageId"])
        except Exception:
            logger.exception("Can't read subscription id from message %s", record["messageId"])
            failed_message_ids.append(record["messageId"])

    subs = []
    for sub_id, message_ids in message_ids_by_sub.items():
        try:
            subs.append(lookup_subscription_with_read_window(sub_id))
        except Exception:
            logger.exception("Lookup of subscription %s failed", sub_id)
            failed_message_ids += message_ids

    upsert_stats = {}
    if subs:
        with connect_s3_tables() as conn:
            upsert_stats["subscription"] = upsert(conn,
                                                  "subscription",
                                                  subs,
                                                  lambda sub_id: lookup_subscription_with_read_window(sub_id))

    logger.info('Upserted %s from %s messages, failed messages: %s', upsert_stats, len(event["Records"]), failed_message_ids)

    return {
        "batchItemFailures": [{"itemIdentifier": message_id} for message_id in failed_message_ids],
        "body": upsert_stats
    }
