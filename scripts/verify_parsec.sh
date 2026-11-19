#!/usr/bin/env bash
# Offline verification. Default: full. Does not start GPU/model services.
set -euo pipefail
repo="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${PARSEC_PYTHON:-$repo/.venv/bin/python}"
[[ -x "$python_bin" ]] || { echo "Python environment missing: $python_bin" >&2; exit 2; }
cd -- "$repo"
exec "$python_bin" scripts/parsec_audit.py verify "$@"
