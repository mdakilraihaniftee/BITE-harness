#!/usr/bin/env bash
# Source this file from Bash to activate the harness and load project settings.
OPENVLHARNESS_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd -- "$OPENVLHARNESS_ROOT" || return 1
source "$OPENVLHARNESS_ROOT/.venv/bin/activate"
if [[ -f "$OPENVLHARNESS_ROOT/.env" ]]; then
    # Parse .env as data: a malformed credential line must never be executed
    # as a shell command or echoed in a command-not-found error.
    eval "$(python - <<'PY'
import re
import shlex
from dotenv import dotenv_values
for name, value in dotenv_values('.env').items():
    if value is not None and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
        print(f'export {name}={shlex.quote(value)}')
PY
)"
fi
mkdir -p "${LMUData:-data}" "${MPLCONFIGDIR:-.cache/matplotlib}" outputs/setup outputs/services
