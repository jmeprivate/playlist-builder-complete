#!/usr/bin/env sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
VENV_DIR="$ROOT_DIR/.venv"
CONFIG_FILE="$ROOT_DIR/config.ini"

fail() {
    printf 'Error: %s\n' "$1" >&2
    exit 1
}

find_python() {
    for candidate in python3.13 python3.12 python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 && \
            "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' >/dev/null 2>&1; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done
    return 1
}

PYTHON_BIN=$(find_python) || fail "se necesita Python 3.12 o posterior"

printf 'Preparando Playlist Builder en %s\n' "$ROOT_DIR"

if [ ! -x "$VENV_DIR/bin/python" ]; then
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi

VENV_PYTHON="$VENV_DIR/bin/python"
"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install -e "$ROOT_DIR"
chmod +x "$ROOT_DIR/crear-playlist.sh"

MUSIC_ROOT=${1:-${PLAYLIST_BUILDER_MUSIC_ROOT:-}}
if [ -z "$MUSIC_ROOT" ] && [ -t 0 ]; then
    printf 'Ruta de la carpeta musical (Enter para dejar config.ini sin cambios): '
    IFS= read -r MUSIC_ROOT
fi

if [ -n "$MUSIC_ROOT" ]; then
    [ -d "$MUSIC_ROOT" ] || fail "la carpeta musical no existe: $MUSIC_ROOT"
    ABSOLUTE_MUSIC_ROOT=$(
        "$VENV_PYTHON" - "$MUSIC_ROOT" <<'PY'
from pathlib import Path
import sys

print(Path(sys.argv[1]).expanduser().resolve())
PY
    )
    "$VENV_PYTHON" - "$CONFIG_FILE" "$ABSOLUTE_MUSIC_ROOT" <<'PY'
from pathlib import Path
import sys

config_path = Path(sys.argv[1])
music_root = sys.argv[2]
lines = config_path.read_text(encoding="utf-8").splitlines()
for index, line in enumerate(lines):
    if line.lstrip().startswith("music_root") and "=" in line:
        lines[index] = f"music_root = {music_root}"
        break
else:
    raise SystemExit("No se encontró music_root en config.ini")
config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
    printf 'Discoteca configurada: %s\n' "$ABSOLUTE_MUSIC_ROOT"
fi

"$VENV_PYTHON" -c 'import playlist_builder'

printf '\nInstalación completada.\n'
printf 'Ejecute: ./crear-playlist.sh\n'
printf 'Entorno virtual: %s\n' "$VENV_DIR"
printf 'Configuración: %s\n' "$CONFIG_FILE"
