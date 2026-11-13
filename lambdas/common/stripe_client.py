from datetime import datetime, timezone
import os
from typing import Iterator

import time
from functools import lru_cache

import boto3
from stripe import StripeClient

from common.fetched_object import FetchedObject

_ssm = boto3.client("ssm")
_KEY_TTL_SECONDS = 300

@lru_cache(maxsize=1)
def _get_api_key(_ttl_bucket: int) -> str:
    # _ttl_bucket is virtually not used with cache maxsize=1; it only makes lru_cache expire every _KEY_TTL_SECONDS
    resp = _ssm.get_parameter(
        Name=os.environ["ssm_param_store_stripe_api_key"],
        WithDecryption=True,
    )
    return resp["Parameter"]["Value"]


@lru_cache(maxsize=1)
def _client_for(api_key: str) -> StripeClient:
    return StripeClient(api_key)


def get_stripe() -> StripeClient:
    bucket = int(time.time() // _KEY_TTL_SECONDS)  # changes every 5 min
    return _client_for(_get_api_key(bucket))


def _with_read_window(request):
    """Calls request() and returns (response, requested_at, received_at): Stripe read the data somewhere in between."""
    requested_at = datetime.now(timezone.utc)
    response = request()
    received_at = datetime.now(timezone.utc)
    return response, requested_at, received_at


def lookup_subscription_with_read_window(sub_id) -> FetchedObject:
    """Retrieves the subscription as it is right now, with the read window of the request."""
    sub, requested_at, received_at = _with_read_window(lambda: get_stripe().v1.subscriptions.retrieve(sub_id))
    return FetchedObject(sub, requested_at, received_at)


def list_subscriptions_with_read_window() -> Iterator[list[FetchedObject]]:
    """Lists all subscriptions (any status), yielding one page (up to 100) at a time.

    Every object carries the read window of its page: Stripe read it somewhere between requested_at and received_at.
    Subscriptions created mid-listing are missed
    """
    stripe = get_stripe()
    params = {"status": "all", "limit": 100}

    def next_page(request_params):
        response, requested_at, received_at = _with_read_window(lambda: stripe.v1.subscriptions.list(request_params))
        return [FetchedObject(sub, requested_at, received_at) for sub in response.data], response.has_more

    data, has_more = next_page(params)
    yield data

    while has_more:
        data, has_more = next_page({**params, "starting_after": data[-1].obj.id})
        yield data
