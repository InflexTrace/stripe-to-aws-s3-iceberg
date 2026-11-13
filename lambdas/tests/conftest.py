import os
import subprocess
from pathlib import Path

import pytest

from common.fetched_object import FetchedObject

# Point common.iceberg at the docker catalog from compose.yml (before any test imports it: it reads env at import).
# setdefault, so exporting the vars beforehand targets another catalog instead
TEST_ENV = {
    # this machine's extensions, downloaded by ../../layers/build.sh (consistent with how lambda loads them in AWS)
    "duckdb_extension_directory": str(Path(__file__).parents[2] / ".build/dev/duckdb_extensions"),
    "iceberg_rest_endpoint": "http://localhost:8181",
    "s3_endpoint": "http://localhost:9090",
    "s3_table_stripe_raw_namespace": "test",
    "AWS_ACCESS_KEY_ID": "admin",
    "AWS_SECRET_ACCESS_KEY": "password",
    "AWS_REGION": "us-east-2",  # read by common.iceberg (DuckDB secret)
    "AWS_DEFAULT_REGION": "us-east-2",  # read by boto3, which ignores AWS_REGION
}
for k, v in TEST_ENV.items():
    os.environ.setdefault(k, v)


@pytest.fixture(scope="session", autouse=True)
def docker_catalog():
    """Starts compose.yml for the whole run and removes it afterwards (fresh catalog + S3 state every run).

    yield splits setup from teardown: if a fixture function is a generator, the code after yield is teardown.
    Pytest checks for this and drives the generator itself. Nothing is yielded, tests only need the containers up.
    """
    compose = ["docker", "compose", "-f", str(Path(__file__).parent / "compose.yml")]
    already_up = subprocess.run([*compose, "ps", "-q"], capture_output=True, text=True, check=True).stdout.strip()
    subprocess.run([*compose, "up", "-d", "--wait"], check=True)  # --wait: until healthy

    # The fresh catalog has no namespaces; in AWS the namespace comes from Terraform
    from common.iceberg import S3_TABLE_NAMESPACE, S3_TABLES, connect_s3_tables

    with connect_s3_tables() as con:
        con.execute(f"CREATE SCHEMA IF NOT EXISTS {S3_TABLES}.{S3_TABLE_NAMESPACE}")
    yield
    if not already_up:  # leave a stack started by hand running
        subprocess.run([*compose, "down"], check=True)

######################## Monkey patching (e.g Lambda API cals) ########################
# Both fakes replace what the lambdas call to read Stripe, and take the read window explicitly, so a test controls
# exactly when Stripe "read" each object (e.g. overlapping or out-of-order windows)

@pytest.fixture
def mock_event_lambda_stripe_lookup(monkeypatch):
    """Returns fake(sub, requested_at, received_at): from then on the event lambda's lookup returns that subscription,
    read within that window. The lambda still looks it up by the id from the event, which has to match sub."""
    import stripe_events.stripe_events_lambda as stripe_event_lambda_module

    def fake(sub, requested_at, received_at):
        def lookup(sub_id):
            assert sub_id == sub["id"]
            return FetchedObject(sub, requested_at, received_at)

        monkeypatch.setattr(stripe_event_lambda_module, "lookup_subscription_with_read_window", lookup)

    return fake


@pytest.fixture
def mock_recon_lambda_list_all_subs_stripe(monkeypatch):
    """Returns fake(*subs, requested_at, received_at): from then on the reconciliation lambda's listing returns exactly
    those subscriptions as one page, all read within that window (as in the real listing, the window is per page)."""
    import reconciliation.reconciliation_lambda as reconciliation_lambda_module

    def fake(*subs, requested_at, received_at):
        def list_pages():
            yield [FetchedObject(sub, requested_at, received_at) for sub in subs]

        monkeypatch.setattr(reconciliation_lambda_module, "RECONCILED_OBJECTS", {"subscription": list_pages})

    return fake


ICEBERG_SCHEMAS_DIR = Path(__file__).parents[2] / ".build" / "stripe_openapi"


@pytest.fixture(autouse=True)
def chdir_to_access_openapi_schemas(monkeypatch):
    monkeypatch.chdir(ICEBERG_SCHEMAS_DIR)


@pytest.fixture(autouse=True)
def drop_lambda_tables():
    """Drops every lambda table (one per iceberg/<table>.json) at test START, so each test begins with an empty catalog.
    """
    from common.iceberg import connect_s3_tables, target_table

    with connect_s3_tables() as con:
        for schema_file in (ICEBERG_SCHEMAS_DIR / "iceberg").glob("*.json"):
            con.execute(f"DROP TABLE IF EXISTS {target_table(schema_file.stem)}")