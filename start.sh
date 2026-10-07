#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"
PYTHON="${BSC_PYTHON:-python3}"
command -v "$PYTHON" >/dev/null || { printf 'Python 3.11+ is required. Set BSC_PYTHON to your interpreter.\n' >&2; exit 1; }
"$PYTHON" -c 'import sys; assert sys.version_info >= (3,11), "Python 3.11+ is required"'

args=("$@")
PORT=8717
i=0
while [[ $i -lt ${#args[@]} ]]; do
  case "${args[$i]}" in
    --port) PORT="${args[$((i+1))]:-}"; i=$((i+2));;
    *) i=$((i+1));;
  esac
done
has_open=0
if [[ ${#args[@]} -gt 0 ]]; then
  for arg in "${args[@]}"; do
    [[ "$arg" == "--open" ]] && has_open=1
  done
fi
if [[ "$has_open" -eq 0 ]]; then args+=(--open); fi

studio_open() {
  "$PYTHON" -c 'import sys, urllib.request
url = "http://127.0.0.1:%s/" % sys.argv[1]
try:
    with urllib.request.urlopen(url, timeout=2) as response:
        raise SystemExit(0 if b"Bot Skill Creator" in response.read(4000) else 1)
except SystemExit:
    raise
except Exception:
    raise SystemExit(1)
' "$1"
}

if studio_open "$PORT"; then
  "$PYTHON" -m bsc serve --port "$PORT" --open
  exit 0
fi

err="$(mktemp)"
nohup "$PYTHON" -m bsc serve "${args[@]}" >/dev/null 2>"$err" &
pid=$!
ready=0
for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37 38 39 40; do
  if studio_open "$PORT"; then ready=1; break; fi
  if ! kill -0 "$pid" 2>/dev/null; then
    status=0
    wait "$pid" || status=$?
    if [[ "$status" -ne 0 ]]; then cat "$err" >&2 || true; fi
    rm -f "$err"
    exit "$status"
  fi
  sleep 0.25
done
rm -f "$err"
disown "$pid" 2>/dev/null || true
if [[ "$ready" -ne 1 ]]; then
  printf 'Bot Skill Creator did not open on http://127.0.0.1:%s/\n' "$PORT" >&2
  exit 1
fi
exit 0
