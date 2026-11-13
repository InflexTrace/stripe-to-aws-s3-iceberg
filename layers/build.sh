#!/usr/bin/env bash
# Builds one shared Lambda layer per dependency group in ../lambdas/pyproject.toml (except dev) into
# ../.build/layers/<group>/python, pinned by ../lambdas/uv.lock (must run before `tofu plan`).
# Target platform must match every function using the layers: arm64 + python3.14
# (lambda_runtime / lambda_architecture locals in ../main.tf).
set -euo pipefail
cd "$(dirname "$0")"
build_dir="../.build/layers"

lambdas_dir="../lambdas"
groups="$(python3 -c 'import sys, tomllib; print(*(g for g in tomllib.load(open(sys.argv[1], "rb"))["dependency-groups"] if g != "dev"))' "$lambdas_dir/pyproject.toml")"

rm -rf "$build_dir"
for name in $groups; do
  mkdir -p "$build_dir/$name/python"
  req="$build_dir/$name.requirements.txt"
  # --locked fails if uv.lock is out of date with pyproject.toml; the export keeps hashes, so pip verifies every wheel
  uv export --project "$lambdas_dir" --only-group "$name" --no-emit-project --locked --quiet > "$req"
  # duckdb only ships manylinux_2_28 aarch64 wheels; Lambda python3.14 runs on AL2023 (glibc 2.34), so both tags are safe
  pip3 install \
    -r "$req" \
    -t "$build_dir/$name/python" \
    --platform manylinux_2_28_aarch64 \
    --platform manylinux2014_aarch64 \
    --implementation cp \
    --python-version 3.14 \
    --only-binary=:all: \
    --no-compile # no .pyc files, so the layer hash only changes when dependencies change
done

# DuckDB extensions get their own layer (duckdb-extensions) so Lambda never downloads them at runtime;
# bundled with the duckdb package the zip would exceed Lambda's 50 MB direct-upload limit.
# Layer contents land in /opt, so these load from /opt/duckdb_extensions/<duckdb version>/linux_arm64/.
# no aws extension: credentials come from Lambda env vars (see lambdas/common/iceberg.py), saves ~68 MB unzipped
DUCKDB_EXTENSIONS=(httpfs iceberg avro) # avro is autoloaded by iceberg to read manifests
duckdb_version="$(sed -n 's/^Version: //p' "$build_dir"/duckdb/python/duckdb-*.dist-info/METADATA)"

# download_extensions <extension_directory> <platform>: same layout duckdb looks up, <dir>/v<version>/<platform>/
download_extensions() {
  local ext_dir="$1/v$duckdb_version/$2"
  rm -rf "$ext_dir"
  mkdir -p "$ext_dir"
  for ext in "${DUCKDB_EXTENSIONS[@]}"; do
    curl -fsSL "https://extensions.duckdb.org/v$duckdb_version/$2/$ext.duckdb_extension.gz" \
      | gunzip > "$ext_dir/$ext.duckdb_extension"
  done
}

download_extensions "$build_dir/duckdb-extensions/duckdb_extensions" linux_arm64

# Same extensions for this machine, used by the tests (../lambdas/tests/conftest.py); not part of any layer.
# Platform comes from the dev venv's duckdb (same pinned version), e.g. osx_arm64 on Apple silicon
local_platform="$(uv run --project "$lambdas_dir" --locked --quiet python -c "import duckdb; print(duckdb.execute('PRAGMA platform').fetchone()[0])")"
download_extensions "../.build/dev/duckdb_extensions" "$local_platform"
