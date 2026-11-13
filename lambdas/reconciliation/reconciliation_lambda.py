import json
import logging
from collections import Counter, defaultdict
from itertools import batched, chain

from common.iceberg import connect_s3_tables, upsert
from common.stripe_client import list_subscriptions_with_read_window, lookup_subscription_with_read_window

logger = logging.getLogger()
logger.setLevel("INFO")


# Objects per MERGE. Each MERGE is one Iceberg commit (snapshot + new files). Rows keep their own page's
# read window, so batching across pages doesn't affect the stale-write guard.
UPSERT_BATCH_SIZE = 5000

# table name (matches iceberg/{table}.json) -> function listing every object of that type from Stripe
RECONCILED_OBJECTS = {
    "subscription": list_subscriptions_with_read_window,
}

# table name -> function reading one object by id again, for objects whose read window overlaps the stored one's.
# Looks the function up on call, so tests can monkeypatch it on this module
REFETCH_OBJECT = {
    "subscription": lambda sub_id: lookup_subscription_with_read_window(sub_id),
}


def lambda_handler(event, context):
    logger.info('## EVENT')
    logger.info(json.dumps(event))

    upsert_stats = defaultdict(Counter)

    with connect_s3_tables() as conn:
        for table, fetch_all in RECONCILED_OBJECTS.items():
            logger.info('Reconciling %s', table)

            for batch in batched(chain.from_iterable(fetch_all()), UPSERT_BATCH_SIZE):
                upsert_stats[table] += upsert(conn, table, batch, REFETCH_OBJECT[table])

            logger.info('Reconciled %s: %s', table, upsert_stats[table])

    return {
        "statusCode": 200,
        "body": upsert_stats
    }
