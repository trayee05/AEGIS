#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
port="${1:-8000}"

if [[ ! "$port" =~ ^[0-9]+$ ]] || (( port < 1 || port > 65535 )); then
  echo "Usage: scripts/run_demo.sh [port 1-65535]" >&2
  exit 2
fi

if [[ -n "${AEGIS_PYTHON:-}" ]]; then
  python_bin="$AEGIS_PYTHON"
elif [[ -x "$repo_root/.venv312/bin/python" ]]; then
  python_bin="$repo_root/.venv312/bin/python"
elif [[ -x "$repo_root/.venv/bin/python" ]]; then
  python_bin="$repo_root/.venv/bin/python"
else
  python_bin="python3"
fi

if ! "$python_bin" -c 'import sys; assert sys.version_info >= (3, 10)' 2>/dev/null; then
  echo "AEGIS-Care needs Python 3.10 or newer. Create a virtual environment with python3.12 -m venv .venv312." >&2
  exit 1
fi

if ! "$python_bin" -c 'import fastapi, numpy, sklearn, pandas, matplotlib, cryptography, httpx' 2>/dev/null; then
  echo "Dependencies are missing for $python_bin. Run: $python_bin -m pip install -r requirements.txt" >&2
  exit 1
fi

if command -v lsof >/dev/null && lsof -nP -iTCP:"$port" -sTCP:LISTEN -t | grep -q .; then
  echo "Port $port is already in use. Stop that server or choose another port; this prevents showing an older checkout." >&2
  exit 1
fi

cd "$repo_root"
export AEGIS_ASSISTANT_MAX_CALLS="${AEGIS_ASSISTANT_MAX_CALLS:-0}"
if [[ -z "${AEGIS_CLINICAL_DB:-}" ]]; then
  demo_data_dir="$(mktemp -d "${TMPDIR:-/tmp}/aegis-demo.XXXXXX")"
  export AEGIS_CLINICAL_DB="$demo_data_dir/clinical_demo.sqlite3"
fi
echo "AEGIS-Care source: $repo_root"
echo "Python: $python_bin"
echo "Dashboard: http://127.0.0.1:$port/"
echo "Synthetic case database: $AEGIS_CLINICAL_DB"
echo "Synthetic sandbox; assistant model calls: $AEGIS_ASSISTANT_MAX_CALLS"
echo "Keep this terminal open. Press Ctrl+C when finished."
exec "$python_bin" -m aegis_care.cli serve --host 127.0.0.1 --port "$port"
