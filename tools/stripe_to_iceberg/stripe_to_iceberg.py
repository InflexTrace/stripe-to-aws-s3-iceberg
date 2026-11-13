"""Downloads the Stripe OpenAPI spec the Lambdas' stripe SDK was generated from and converts its schemas to Iceberg
table schemas."""
import json
import re
from pathlib import Path
from urllib.request import urlopen

BUILD_DIR = Path(__file__).resolve().parent / "../../.build"
OUT_DIR = BUILD_DIR / "stripe_openapi"
# The stripe SDK the Lambdas run, built by layers/build.sh from uv.lock (build.sh runs that first)
STRIPE_SDK_DIR = BUILD_DIR / "layers/stripe/python/stripe"
SCHEMAS_TO_EXTRACT = ['subscription']


def sdk_constant(file_name: str, constant: str) -> str:
    """Reads e.g. VERSION = "16.0.0" from the SDK's source without importing it (it's built for Lambda's platform)."""
    source = (STRIPE_SDK_DIR / file_name).read_text()
    return re.search(rf'^\s*{constant} = "([^"]+)"', source, re.MULTILINE).group(1)


def download_openapi_spec() -> str:
    """Downloads the spec at the stripe/openapi tag the SDK was generated from, so the table schemas match the API
    version the SDK requests (it sends its pinned version with every request), not whatever Stripe released last."""
    sdk_version = sdk_constant("_version.py", "VERSION")

    # Every stripe-python release records the stripe/openapi tag it was generated from in OPENAPI_VERSION
    # urlopen raises HTTPError on 4xx/5xx, so a failed download stops the build
    with urlopen(f"https://raw.githubusercontent.com/stripe/stripe-python/v{sdk_version}/OPENAPI_VERSION") as resp:
        openapi_tag = resp.read().decode("utf-8").strip()

    with urlopen(f"https://raw.githubusercontent.com/stripe/openapi/{openapi_tag}/latest/openapi.spec3.json") as resp:
        resp_bytes = resp.read()

    print(f"Stripe OpenAPI spec {openapi_tag} (API version {json.loads(resp_bytes)['info']['version']}) "
          f"for stripe SDK {sdk_version}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "openapi.spec3.json").write_bytes(resp_bytes) # write raw response for debugging
    return resp_bytes.decode("utf-8")


def field_type(field, field_properties):
    match field_properties:
        case {'type': 'string'}:
            return "string"
        case {'type': 'integer', 'format': 'unix-time'}:
            return 'timestamptz' #timestamptz is an absolute instant, stored as microseconds from the UTC epoch. When you query it, the engine converts it to your session’s zone for display
        case {'type': 'integer'}:
            return "bigint" # amounts are in the currency's smallest unit and can overflow int32
        case {'type': 'number'}:
            return "double" # only used for fractional values like percentages; money is always integer in Stripe
        case {'type': 'boolean'}:
            return "boolean"
        case {'type': 'array', 'items': items}:
            element_type = field_type(field, items)
            # duckdb can only write variant as a root column (as of 2.0.0), so an array of objects is stored as a single variant holding the array
            return "variant" if element_type == "variant" else f"{element_type}[]"
        case {'type': 'object', 'additionalProperties': {'type': 'string'}}:
            return "map(varchar, varchar)" # free-form string dictionary, e.g. metadata
        case {'type': 'object'} | {'$ref': str()}:
            return "variant" # nested struct, its shape changes between Stripe API versions
        case {'anyOf': [{'type': 'string'}, *_]}:
            return "string" # expandable field: Stripe returns the id unless the request expands it
        case {'anyOf': [single]}:
            return field_type(field, single) # nullable wrapper around a single schema
        case _:
            raise ValueError(f"Couldn't map field {field} with properties {field_properties} to iceberg type")


def open_api_to_iceberg(open_api_schema):
    return {field: field_type(field, field_properties) for field, field_properties in open_api_schema['properties'].items()}

def primary_key(open_api_schema):
    match open_api_schema:
        case { "properties": {"id": {"description": "Unique identifier for the object."}} }:
            return "id"
        case _:
            raise ValueError(
                f"Couldn't automatically figure out PK for title: ${open_api_schema.get('title')} x-resourceId: ${open_api_schema.get('x-resourceId')}")

def created_at(open_api_schema):
    match open_api_schema:
        case { "properties": {"created": {"description": str(desc)}} } if "Time at which the object was created." in desc:
            return "created"
        case _:
            raise ValueError(
                f"Couldn't automatically figure out created timestamp for title: ${open_api_schema.get('title')} x-resourceId: ${open_api_schema.get('x-resourceId')}")


def construct_iceberg_schema(schema, pk, ts):
    return { "schema" : schema, "primary_key": pk, "created_at": ts }

if __name__ == "__main__":
    open_api_spec = json.loads(download_openapi_spec())
    for schema_name in SCHEMAS_TO_EXTRACT:
        open_api_schema = open_api_spec['components']['schemas'][schema_name]

        iceberg_schema = open_api_to_iceberg(open_api_schema)
        pk = primary_key(open_api_schema)
        created_ts = created_at(open_api_schema)

        schema_path = OUT_DIR / f"iceberg/{schema_name}.json"
        schema_path.parent.mkdir(parents=True, exist_ok=True)
        with open(schema_path, "w") as out_file:
            json.dump(construct_iceberg_schema(iceberg_schema, pk, created_ts), out_file, indent=2)



