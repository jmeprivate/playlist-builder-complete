#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if [ -x "$ROOT_DIR/.venv/bin/python" ]; then
    PYTHON_BIN="$ROOT_DIR/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN=python
else
    printf 'Error: no se encontro Python. Ejecute primero ./install.sh\n' >&2
    exit 1
fi

exec "$PYTHON_BIN" "$ROOT_DIR/crear_playlist.py" "$@"
