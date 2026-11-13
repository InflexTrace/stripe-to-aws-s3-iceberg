# stripe_to_iceberg

Downloads the Stripe OpenAPI spec and converts its schemas to Iceberg table schemas.
Output goes to `../../.build/stripe_openapi/`.

The spec is pinned to the stripe SDK the Lambdas run (`stripe==` in `../../lambdas/pyproject.toml`, read from the
layer `../../layers/build.sh` builds, so run that first): the SDK release's `OPENAPI_VERSION` names the
[stripe/openapi](https://github.com/stripe/openapi) tag to download, i.e. the spec of the API version the SDK sends
(`Stripe-Version`). Table schemas therefore only change when you bump the SDK.

## Run

Standard library only, no dependencies to install. `../../build.sh` runs it as part of the build, after the layers; to run it alone:

```bash
python3 stripe_to_iceberg.py
```

## Troubleshooting

**`CERTIFICATE_VERIFY_FAILED`**: the python.org Python 3.14 on macOS doesn't trust any HTTPS certificates until its certificate installer has run once:

```bash
open "/Applications/Python 3.14/Install Certificates.command"
```
