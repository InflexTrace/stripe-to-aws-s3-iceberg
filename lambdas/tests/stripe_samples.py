import json
from pathlib import Path

SAMPLES = Path(__file__).parent / "stripe_event_samples"


def _load(rel_glob):
    # one captured sample per directory, named after the object it holds
    return json.loads(next(SAMPLES.glob(rel_glob)).read_text())


def subscription(sub_id, status):
    """get_stripe().v1.subscriptions.retrieve(sub_id) response; status tells apart versions of the same subscription"""
    sub = _load("api/v1/subscriptions/retrieve/*.json")
    sub["id"] = sub_id
    sub["status"] = status
    for item in sub["items"]["data"]:
        item["subscription"] = sub_id
    sub["items"]["url"] = f"/v1/subscription_items?subscription={sub_id}"
    return sub


def thin_subscription_event(sub_id, event_type):
    """EventBridge envelope of a thin v1.customer.subscription.* event"""
    event = _load("events/thin/event_bridge_customer_subscription_created.json")
    event["detail-type"] = event["detail"]["type"] = event_type
    event["detail"]["related_object"]["id"] = sub_id
    event["detail"]["related_object"]["url"] = f"/v1/subscriptions/{sub_id}"
    return event

def thin_event_customer_subscription_updated(sub_id):
    return thin_subscription_event(sub_id, "v1.customer.subscription.updated")

def sqs_batch(*events):
    """SQS event source mapping payload: one message per EventBridge event, its body is the whole event as JSON"""
    return {"Records": [{"messageId": f"msg-{i}", "body": json.dumps(e), "eventSource": "aws:sqs"}
                        for i, e in enumerate(events)]}
