#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -x .venv/bin/python ]]; then
  echo 'Set up the backend first:'
  echo '  python3 -m venv .venv'
  echo '  .venv/bin/python -m pip install -r requirements.lock'
  exit 1
fi

if [[ ! -f frontend/dist/index.html || frontend/package-lock.json -nt frontend/dist/index.html || frontend/vite.config.ts -nt frontend/dist/index.html || frontend/index.html -nt frontend/dist/index.html ]] || [[ -n "$(find frontend/src frontend/public -type f -newer frontend/dist/index.html -print -quit 2>/dev/null)" ]]; then
  if ! command -v npm >/dev/null 2>&1; then
    echo 'Node.js and npm are needed to build the interface. Install them, then run ./start.sh again.'
    exit 1
  fi
  if [[ ! -d frontend/node_modules ]]; then
    (cd frontend && npm ci)
  fi
  (cd frontend && npm run build)
fi

echo 'Starting Jab at http://127.0.0.1:8000'
echo 'Keep this terminal open. Press Ctrl+C to stop Jab.'
exec .venv/bin/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000 --workers 1
