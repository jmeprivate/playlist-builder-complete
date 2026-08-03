from pathlib import Path

# Edite esta ruta antes de usar la aplicación con su colección real.
MUSIC_ROOT = Path(r"/ruta/a/MiDiscoteca")

DEFAULT_YEAR_MARGIN = 5
DEFAULT_SIZE_MB = 8000.0
DEFAULT_MAX_ALBUM = 2
CACHE_FILENAME = ".playlist_catalog.json"
MIN_REASONABLE_YEAR = 1000
MAX_REASONABLE_YEAR_OFFSET = 1
AUDIO_EXTENSIONS = frozenset(
    {
        ".mp3",
        ".flac",
        ".m4a",
        ".mp4",
        ".ogg",
        ".opus",
        ".ape",
    }
)
