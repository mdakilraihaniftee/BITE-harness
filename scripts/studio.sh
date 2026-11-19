#!/usr/bin/env bash
# Run an Investigation Studio in the foreground.
#
# The launch link connects the browser automatically without token entry.
# The server binds its port first and prints "Studio ready" plus a
# browser link only after its API answers. If the port is taken, it explains
# whether the holder is a compatible Studio, an outdated Studio, or an unrelated
# process, and exits without claiming success.
#
# Background/idempotent alternative: python scripts/studio_ctl.py ensure --open
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$REPO_ROOT"
source scripts/env.sh
export TRANSFORMERS_NO_ADVISORY_WARNINGS="${TRANSFORMERS_NO_ADVISORY_WARNINGS:-1}"

STUDIO_HOST="${STUDIO_HOST:-127.0.0.1}"
STUDIO_PORT="${STUDIO_PORT:-8787}"
STUDIO_RUNS_DIR="${STUDIO_RUNS_DIR:-outputs/multi_agent}"
if [[ -z "${STUDIO_VIEWER_TOKEN:-}" ]]; then
    STUDIO_VIEWER_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(24))')"
fi
export STUDIO_VIEWER_TOKEN

exec python -m openvlharness.studio.server \
    --host "$STUDIO_HOST" \
    --port "$STUDIO_PORT" \
    --runs-dir "$STUDIO_RUNS_DIR" "$@"
