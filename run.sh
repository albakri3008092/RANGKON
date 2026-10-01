#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ -f .env ]; then set -a; source .env; set +a; fi
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt; }
exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
