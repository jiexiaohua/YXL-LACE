#!/usr/bin/env bash
# Replace repository root README.md with a locale from docs/README.<lang>.md
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "${SCRIPT_DIR}/switch_readme.py" "${1:?usage: $0 en|zh|ja|ko|es}"
