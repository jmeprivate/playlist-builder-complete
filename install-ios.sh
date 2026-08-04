#!/bin/sh
set -eu

VERSION="${PLAYLIST_BUILDER_VERSION:-1.0.0}"
REPOSITORY="jmeprivate/playlist-builder-complete"
WHEEL_NAME="playlist_builder_local-${VERSION}-py3-none-any.whl"
WHEEL_URL="https://github.com/${REPOSITORY}/releases/download/v${VERSION}/${WHEEL_NAME}"
ALLOW_NON_IOS="${PLAYLIST_BUILDER_ALLOW_NON_IOS:-0}"

fail() {
    printf 'Error: %s\n' "$1" >&2
    exit 1
}

find_python() {
    if [ -n "${PYTHON:-}" ]; then
        command -v "$PYTHON" >/dev/null 2>&1 || fail "no se encuentra el intérprete indicado en PYTHON=$PYTHON"
        printf '%s\n' "$PYTHON"
        return
    fi
    if command -v python3 >/dev/null 2>&1; then
        printf '%s\n' python3
        return
    fi
    if command -v python >/dev/null 2>&1; then
        printf '%s\n' python
        return
    fi
    fail "a-Shell no expone python3 ni python"
}

PYTHON_BIN="$(find_python)"

if [ "$ALLOW_NON_IOS" != "1" ] && ! command -v pickFolder >/dev/null 2>&1; then
    fail "este instalador está diseñado para la app a-Shell en iPhone o iPad"
fi

"$PYTHON_BIN" - <<'PY' || fail "Playlist Builder requiere Python 3.12 o posterior"
import sys
raise SystemExit(0 if sys.version_info >= (3, 12) else 1)
PY

if [ -n "${PLAYLIST_BUILDER_HOME:-}" ]; then
    DOCUMENTS_DIR="$PLAYLIST_BUILDER_HOME"
elif [ -d "$HOME/Documents" ] && [ -w "$HOME/Documents" ]; then
    DOCUMENTS_DIR="$HOME/Documents"
else
    DOCUMENTS_DIR="$HOME"
fi

APP_DIR="$DOCUMENTS_DIR/PlaylistBuilder"
BIN_DIR="$DOCUMENTS_DIR/bin"
SITE_PACKAGES="$APP_DIR/site-packages"
CONFIG_FILE="$APP_DIR/config.ini"
DEFAULT_MUSIC_ROOT="$APP_DIR/Music"
REQUESTED_MUSIC_ROOT="${1:-${PLAYLIST_BUILDER_MUSIC_ROOT:-}}"

mkdir -p "$APP_DIR" "$BIN_DIR" "$SITE_PACKAGES"

printf 'Instalando Playlist Builder %s para a-Shell...\n' "$VERSION"
"$PYTHON_BIN" -m pip install \
    --disable-pip-version-check \
    --upgrade \
    --target "$SITE_PACKAGES" \
    "$WHEEL_URL"

if [ ! -f "$CONFIG_FILE" ]; then
    mkdir -p "$DEFAULT_MUSIC_ROOT"
    cat >"$CONFIG_FILE" <<EOF
# Configuración de Playlist Builder para a-Shell en iOS/iPadOS.
# Use el comando configurar-playlist para cambiar la carpeta musical.
[playlist_builder]
music_root = $DEFAULT_MUSIC_ROOT
default_year_margin = 5
default_size_mb = 8000
default_max_album = 2
retry_error_after_days = 7
default_max_artist = 0
deduplicate = false
cache_filename = .playlist_catalog.json
min_reasonable_year = 1000
max_reasonable_year_offset = 1
audio_extensions = .mp3, .flac, .m4a, .mp4, .ogg, .opus, .ape
surprise_mode = false
preview_entries = 5
copy_structure = flat
profiles_file = filter_profiles.json
EOF
fi

cat >"$BIN_DIR/crear-playlist" <<'EOF'
#!/bin/sh
set -eu
BIN_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
DOCUMENTS_DIR="$(dirname "$BIN_DIR")"
APP_DIR="$DOCUMENTS_DIR/PlaylistBuilder"
if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=python3
else
    PYTHON_BIN=python
fi
export PYTHONPATH="$APP_DIR/site-packages${PYTHONPATH:+:$PYTHONPATH}"
exec "$PYTHON_BIN" -m playlist_builder.cli --config "$APP_DIR/config.ini" "$@"
EOF
chmod +x "$BIN_DIR/crear-playlist"

cat >"$BIN_DIR/configurar-playlist" <<'EOF'
#!/bin/sh
set -eu
if [ "$#" -ne 1 ]; then
    printf '%s\n' 'Uso: configurar-playlist RUTA' >&2
    printf '%s\n' 'En a-Shell: ejecute pickFolder, elija la carpeta, consulte pwd y pase esa ruta.' >&2
    exit 2
fi
if [ ! -d "$1" ]; then
    printf 'Error: no existe la carpeta: %s\n' "$1" >&2
    exit 1
fi
BIN_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
DOCUMENTS_DIR="$(dirname "$BIN_DIR")"
CONFIG_FILE="$DOCUMENTS_DIR/PlaylistBuilder/config.ini"
if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN=python3
else
    PYTHON_BIN=python
fi
"$PYTHON_BIN" - "$CONFIG_FILE" "$1" <<'PY'
from pathlib import Path
import sys

config_path = Path(sys.argv[1])
music_root = Path(sys.argv[2]).expanduser().resolve()
lines = config_path.read_text(encoding="utf-8").splitlines()
for index, line in enumerate(lines):
    if line.strip().startswith("music_root") and "=" in line:
        lines[index] = f"music_root = {music_root}"
        break
else:
    raise SystemExit("No se encontró music_root en config.ini")
config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"Discoteca configurada: {music_root}")
PY
EOF
chmod +x "$BIN_DIR/configurar-playlist"

if [ -n "$REQUESTED_MUSIC_ROOT" ]; then
    "$BIN_DIR/configurar-playlist" "$REQUESTED_MUSIC_ROOT"
fi

PYTHONPATH="$SITE_PACKAGES${PYTHONPATH:+:$PYTHONPATH}" \
    "$PYTHON_BIN" - "$CONFIG_FILE" <<'PY'
from pathlib import Path
import sys

from playlist_builder.config import load_config

settings = load_config(Path(sys.argv[1]))
if not settings.music_root.is_dir():
    raise SystemExit(f"La carpeta musical no existe: {settings.music_root}")
PY

printf '\nInstalación completada.\n'
printf 'Comando principal: crear-playlist\n'
printf 'Configuración: %s\n' "$CONFIG_FILE"
printf '\nPara usar una carpeta de Archivos:\n'
printf '  1. Ejecute: pickFolder\n'
printf '  2. Seleccione la carpeta que contiene la música.\n'
printf '  3. Ejecute: configurar-playlist "$(pwd)"\n'
printf '  4. Ejecute: crear-playlist\n'
printf '\nEl programa solo podrá leer las carpetas que iOS permita a a-Shell.\n'
