from pathlib import Path

# Edite esta ruta antes de usar la aplicación con su colección real.
MUSIC_ROOT = Path(r"/ruta/a/MiDiscoteca")

DEFAULT_YEAR_MARGIN = 5
DEFAULT_SIZE_MB = 8000.0
DEFAULT_MAX_ALBUM = 2
# 0 conserva el comportamiento histórico: sin cuota por artista de pista.
DEFAULT_MAX_ARTIST = 0
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
        ".wav",
        ".wma",
        ".ape",
        ".aiff",
        ".aif",
    }
)
