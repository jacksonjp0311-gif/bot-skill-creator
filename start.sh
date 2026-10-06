#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
PYTHON="${BSC_PYTHON:-python3}"
command -v "$PYTHON" >/dev/null || { printf 'Python 3.11+ is required. Set BSC_PYTHON to your interpreter.\n' >&2; exit 1; }
"$PYTHON" -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ is required"'
exec "$PYTHON" -m bsc serve --open "$@"
