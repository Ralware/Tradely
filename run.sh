#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

# Tradely needs Python 3.11-3.14. Python 3.15+ has no pandas wheel yet, so
# "pip install -r requirements.txt" would try to build pandas from source.
PYTHON=""
for candidate in python3.14 python3.13 python3.12 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1 && \
     "$candidate" -c 'import sys; raise SystemExit(0 if (3,11) <= sys.version_info[:2] <= (3,14) else 1)' 2>/dev/null; then
    PYTHON="$candidate"
    break
  fi
done

if [ -z "$PYTHON" ]; then
  echo "[Tradely] No compatible Python interpreter found." >&2
  echo "[Tradely] Install Python 3.11-3.14. Python 3.15 is not supported yet (no pandas wheel)." >&2
  exit 1
fi

# The React frontend needs Node.js and npm.
if ! command -v node >/dev/null 2>&1 || ! command -v npm >/dev/null 2>&1; then
  echo "[Tradely] Node.js and npm are required for the React frontend." >&2
  echo "[Tradely] Install Node.js 20 or newer from https://nodejs.org/ and try again." >&2
  exit 1
fi

VENV_PY=".venv/bin/python"

# Recreate an existing venv built with an unsupported interpreter.
if [ -x "$VENV_PY" ] && ! "$VENV_PY" -c 'import sys; raise SystemExit(0 if (3,11) <= sys.version_info[:2] <= (3,14) else 1)' 2>/dev/null; then
  echo "[Tradely] Existing .venv uses an unsupported Python version; recreating it..." >&2
  rm -rf .venv
fi

if [ ! -x "$VENV_PY" ]; then
  echo "[Tradely] Creating virtual environment with $PYTHON..."
  "$PYTHON" -m venv .venv
fi

echo "[Tradely] Validating backend dependencies..."
"$VENV_PY" -m pip install --disable-pip-version-check -q -r requirements.txt

if [ ! -f .env ]; then cp .env.example .env; fi

if [ ! -f frontend/package.json ]; then
  echo "[Tradely] frontend/package.json is missing." >&2
  exit 1
fi

if [ ! -d frontend/node_modules ]; then
  echo "[Tradely] Installing frontend dependencies (first run)..."
  (cd frontend && npm install --no-fund --no-audit)
fi

cleanup() {
  if [ -n "${API_PID:-}" ]; then
    kill "$API_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

echo "[Tradely] Starting FastAPI on http://127.0.0.1:8000 ..."
"$VENV_PY" -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload &
API_PID=$!

for _ in $(seq 1 40); do
  if curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    break
  fi
  sleep 0.75
done

if ! curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
  echo "[Tradely] FastAPI did not become ready on port 8000." >&2
  exit 1
fi

echo "[Tradely] FastAPI is ready."
echo "[Tradely] Starting Vite on http://localhost:5173 ..."
echo "[Tradely] Press Ctrl+C to stop both servers."
cd frontend
npm run dev
