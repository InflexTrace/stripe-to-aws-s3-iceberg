# stripe-to-aws-s3-iceberg
Stripe subscriptions synced into Apache Iceberg on S3, with concurrency-safe upserts from AWS Lambda and DuckDB.

## How it works

```
Stripe ──thin events──> EventBridge partner bus ──rule──> SQS (+DLQ) ──batches──> stripe_events Lambda ─┐
                                                                                                         ├─ MERGE ─> S3 Tables (Iceberg)
EventBridge Scheduler ─────────────────────────────────────────────────────────> reconciliation Lambda ─┘
```

- **Stripe event destination** sends `v1.customer.subscription.{created,updated,deleted}` as *thin* events (only a
  reference to the subscription) to an Amazon EventBridge partner event bus.
- **`stripe_events` Lambda** consumes them from SQS in batches, retrieves each subscription's *current* state from
  Stripe (Stripe doesn't guarantee event order, so event payloads aren't trusted) and upserts the batch in one MERGE.
- **`reconciliation` Lambda** runs on a schedule, lists every subscription from Stripe and upserts them, catching
  anything the event path missed.
- **Stale-write guard**: every row stores the read window of the Stripe request that produced it (`_requested_at`,
  `_received_at`). A row only overwrites the stored one if its read provably started after the stored read finished;
  overlapping windows are re-read from Stripe. Iceberg commit conflicts (409) rerun the whole classify -> MERGE ->
  COMMIT transaction on the newer snapshot. See [`lambdas/common/iceberg.py`](lambdas/common/iceberg.py).
- **Table schemas** are generated from the Stripe OpenAPI spec pinned to the Stripe SDK version the Lambdas run
  ([`tools/stripe_to_iceberg`](tools/stripe_to_iceberg)), and the tables are created by the Lambdas.


## Deploy

### Prerequisites

- [OpenTofu](https://opentofu.org/) >= 1.12.6, [uv](https://docs.astral.sh/uv/), Python 3.14
- One AWS account per environment (`dev`, `prod`), with an AWS CLI profile named `<name_prefix>-<env>`
  (`stripe-iceberg-dev` by default; see `variables.tf`)
- An S3 bucket for the state in each account: `<name_prefix>-<region>-tofu-state-<env>` (see `versions.tf`)
- The Stripe secret API key, stored manually as a SecureString in SSM Parameter Store of that account under
  `/<env>/<name_prefix>/stripe/api_secret_key`. It's read by `data.tf` for the Stripe provider and by the Lambdas at runtime.

### Build, init and apply

Both environments use a single code base with [backend config from variables](https://opentofu.org/blog/opentofu-1-8-0/),
so the state of each environment lives in a bucket in its own account.

```bash
./build.sh

tofu init -var="env=dev"
tofu apply -var="env=dev"
```

`./build.sh` runs every local build step; all outputs land in `.build/` (safe to delete).

| Step | Script | Output |
|---|---|---|
| Shared Lambda layers | `layers/build.sh` | `.build/layers/` |
| Stripe OpenAPI -> Iceberg schemas | `tools/stripe_to_iceberg/stripe_to_iceberg.py` | `.build/stripe_openapi/` |

### Lambda layers (shared)

Third-party Python packages are shipped as Lambda layers shared by every Lambda: `stripe-python-{env}` (the `stripe`
SDK), `duckdb-python-{env}` (`duckdb`) and `duckdb-extensions-{env}` (DuckDB extensions, pre-downloaded so Lambda never
fetches them at runtime). The layers are built locally before every plan/apply.

### Switching environments: use `-reconfigure`, never `-migrate-state`

`.terraform/` is initialised against exactly one environment, and nothing on disk records which one. When you switch
`env`, the resolved backend config changes and OpenTofu stops with *"Backend configuration changed"*, offering two ways
forward:

```bash
tofu init -reconfigure -var="env=prod"   # correct: discard the local backend record, re-init against prod
tofu init -migrate-state -var="env=prod" # WRONG: copies the dev state into the prod bucket
```

## Tests

See [`lambdas/tests/README.md`](lambdas/tests/README.md). In short, with Docker running:

```bash
./build.sh
cd lambdas && uv run pytest
```
