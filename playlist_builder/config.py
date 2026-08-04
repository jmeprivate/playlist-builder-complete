from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path

# Edite esta ruta antes de usar la aplicación con su colección real.
MUSIC_ROOT = Path(r"/ruta/a/MiDiscoteca")

DEFAULT_YEAR_MARGIN = 5
DEFAULT_SIZE_MB = 8000.0
DEFAULT_MAX_ALBUM = 2
DEFAULT_PREVIEW_ENTRIES = 5
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


@dataclass(frozen=True, slots=True)
class UserConfig:
    surprise_mode: bool = False
    preview_entries: int = DEFAULT_PREVIEW_ENTRIES
    copy_structure: str = "flat"


def default_config_path() -> Path:
    """Prefer an explicit working-directory config, then the launcher-adjacent example."""
    local = Path("config.ini")
    if local.is_file():
        return local
    return Path(__file__).resolve().parent.parent / "config.ini"


def load_user_config(path: Path | None = None) -> UserConfig:
    """Load optional UI preferences, failing clearly on invalid values."""
    path = path or default_config_path()
    parser = ConfigParser()
    if not path.is_file():
        return UserConfig()
    parser.read(path, encoding="utf-8")
    section = (
        parser["playlist_builder"] if parser.has_section("playlist_builder") else parser["DEFAULT"]
    )
    surprise = section.getboolean("surprise_mode", fallback=False)
    preview_entries = section.getint("preview_entries", fallback=DEFAULT_PREVIEW_ENTRIES)
    if preview_entries < 1:
        raise ValueError("preview_entries debe ser al menos 1")
    copy_structure = section.get("copy_structure", "flat").strip().casefold()
    if copy_structure not in {"flat", "tree"}:
        raise ValueError("copy_structure debe ser 'flat' o 'tree'")
    return UserConfig(surprise, preview_entries, copy_structure)
