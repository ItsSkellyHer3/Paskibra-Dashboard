#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-5000}"
PYTHON_BIN="${PYTHON:-python3}"
VENV_DIR="$ROOT_DIR/.venv"
APP_PYTHON="$VENV_DIR/bin/python"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    echo "Python was not found. Install Python 3, then run this script again."
    exit 1
fi

if [[ ! -x "$APP_PYTHON" ]]; then
    echo "Preparing the app's Python environment..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

if ! "$APP_PYTHON" -c 'import flask, qrcode, PIL, py_vapid, pywebpush, cryptography' >/dev/null 2>&1; then
    echo "Installing the app's required packages..."
    "$APP_PYTHON" -m pip install --upgrade pip
    "$APP_PYTHON" -m pip install -r requirements.txt
fi

if ! "$APP_PYTHON" - "$HOST" "$PORT" <<'PY'
import socket
import sys

host, port = sys.argv[1], int(sys.argv[2])
probe = socket.socket()
try:
    probe.bind((host, port))
except OSError:
    print(f"Port {port} is already in use. Stop the other app or run with PORT=5001 ./run.sh.", file=sys.stderr)
    sys.exit(1)
finally:
    probe.close()
PY
then
    exit 1
fi

mkdir -p static/uploads static/img static/css static/js
echo "Starting Paskibra at http://${HOST}:${PORT}"
echo "Press Ctrl+C to stop the app."
exec "$APP_PYTHON" -m flask --app app:create_app run --host "$HOST" --port "$PORT"
