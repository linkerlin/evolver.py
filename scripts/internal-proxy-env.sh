#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: scripts/internal-proxy-env.sh [--settings FILE] [--status] [--token]

Print shell exports for routing local agent clients through the running
EvoMap Proxy (Python port). Intended usage:

  eval "$(scripts/internal-proxy-env.sh)"

The script reads ~/.evomap/proxy-settings.json by default (EVOLVER_HOME
overrides) and never writes files.
--status prints only proxy metadata lines (proxy_url/proxy_pid/...).
--token prints only the proxy token for command-backed auth.
EOF
}

settings_file="${EVOLVER_SETTINGS_FILE:-}"
status_only=0
token_only=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --settings)
      if [[ $# -lt 2 ]]; then
        echo "missing value for --settings" >&2
        exit 2
      fi
      settings_file="$2"
      shift 2
      ;;
    --status)
      status_only=1
      shift
      ;;
    --token)
      token_only=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$settings_file" ]]; then
  settings_dir="${EVOLVER_HOME:-$HOME/.evomap}"
  settings_file="$settings_dir/proxy-settings.json"
fi

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN=python3
else
  PYTHON_BIN=python
fi

"$PYTHON_BIN" - "$settings_file" "$status_only" "$token_only" <<'PY'
import json
import sys
import os

settings_file = sys.argv[1]
status_only = sys.argv[2] == "1"
token_only = sys.argv[3] == "1"


def die(message, code=1):
    print(message, file=sys.stderr)
    sys.exit(code)


try:
    with open(settings_file, encoding="utf-8") as f:
        parsed = json.load(f)
except OSError:
    die(f"cannot read proxy settings at {settings_file}; start `evolver proxy` first")

proxy = parsed.get("proxy") if isinstance(parsed, dict) else None
if not isinstance(proxy, dict) or not isinstance(proxy.get("url"), str) or not isinstance(proxy.get("token"), str):
    die(f"no active proxy.url/proxy.token found in {settings_file}; start `evolver proxy` first")

proxy_url = proxy["url"]
if status_only:
    print(f"proxy_url={proxy_url}")
    if proxy.get("pid") is not None:
        print(f"proxy_pid={proxy['pid']}")
    if proxy.get("started_at"):
        print(f"proxy_started_at={proxy['started_at']}")
    sys.exit(0)

if token_only:
    print(proxy["token"])
    sys.exit(0)

def quote(value):
    return "'" + str(value).replace("'", "'\\''") + "'"

# Python port serves the Anthropic-compatible relay under /v1/a2a.
base = proxy_url.rstrip("/") + "/v1/a2a"
print(f"export ANTHROPIC_BASE_URL={quote(base)}")
print(f"export ANTHROPIC_AUTH_TOKEN={quote(proxy['token'])}")
print(f"export EVOMAP_PROXY_URL={quote(proxy_url)}")
PY
