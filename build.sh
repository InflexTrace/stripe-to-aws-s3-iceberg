#!/usr/bin/env bash
# Builds everything this deployment needs locally (must run before `tofu plan`). Outputs land in ./.build
set -euo pipefail
cd "$(dirname "$0")"

./layers/build.sh
python3 tools/stripe_to_iceberg/stripe_to_iceberg.py
