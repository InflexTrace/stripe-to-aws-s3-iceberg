# Tests

## Create the venv

Needs [uv](https://docs.astral.sh/uv/). From `lambdas/`:

```bash
uv sync
```

Creates `.venv` with the `dev` dependency group from `pyproject.toml` (pinned by `uv.lock`).

## Run

Tests write to a local Iceberg REST catalog + S3 mock (`compose.yml`), so Docker must be running. `conftest.py` points
`common/iceberg.py` at it through env vars and starts the compose stack for the test run, removing it afterwards
(fresh state every run). DuckDB extensions load from `../.build/dev/duckdb_extensions`, downloaded for this machine by
`../layers/build.sh` (run it once, and again after bumping duckdb). From `lambdas/`:

```bash
../layers/build.sh
uv run pytest
```

To skip the startup on every run, start the stack yourself; pytest then reuses it and leaves it running:

```bash
docker compose -f tests/compose.yml up -d --wait
docker compose -f tests/compose.yml down   # when done
```

## Run against real S3 Tables

Local is the default. `TEST_CATALOG=s3tables` runs the same tests against a real table bucket, always in its `test`
namespace (Terraform creates it), because the tests drop their tables at the start of each test. From `lambdas/`:

```bash
eval "$(aws configure export-credentials --profile stripe-iceberg-dev --format env)"
TEST_CATALOG=s3tables uv run pytest
```

## Browse the files tests write to S3

Start the stack yourself as above, otherwise pytest removes it (and every file) when the run ends. The S3 mock serves
the `warehouse` bucket on `localhost:9090` and accepts the dummy credentials from `compose.yml`. Tables land at
`warehouse/<namespace>/<table>/`, Parquet data in `data/`, Iceberg metadata (`*.metadata.json`, manifest `*.avro`)
in `metadata/`.

```bash
export AWS_ACCESS_KEY_ID=admin AWS_SECRET_ACCESS_KEY=password AWS_REGION=us-east-2
aws --endpoint-url http://localhost:9090 s3 ls s3://warehouse/ --recursive

# download the whole table
aws --endpoint-url http://localhost:9090 s3 cp s3://warehouse/test/subscription/ ./dummy_iceberg_table --recursive
```

To query a Parquet file in place with DuckDB :

```python
import duckdb
con = duckdb.connect()
con.execute("SET extension_directory = '../.build/dev/duckdb_extensions'")  # httpfs autoloads from here on first s3:// read
con.execute("CREATE SECRET (TYPE s3, KEY_ID 'admin', SECRET 'password', REGION 'us-east-2', "
            "ENDPOINT 'localhost:9090', URL_STYLE 'path', USE_SSL false)")
# raw files, bypassing the catalog: also reads files of earlier dropped generations of the table
con.sql("SELECT * FROM 's3://warehouse/test/dummy/data/*.parquet'").show()
```

Or with the venv activated:

```bash
source .venv/bin/activate
pytest
```
