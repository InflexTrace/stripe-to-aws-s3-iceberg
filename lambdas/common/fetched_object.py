from datetime import datetime
from typing import NamedTuple

from stripe import StripeObject


class FetchedObject(NamedTuple):
    """A Stripe object plus its read window: Stripe read it somewhere between requested_at and received_at."""
    obj: StripeObject | dict
    requested_at: datetime
    received_at: datetime
