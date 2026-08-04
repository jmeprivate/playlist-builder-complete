from __future__ import annotations

import configparser
import math
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

SECTION = "playlist_builder"
_EXTENSION = re.compile(r"\.[a-z0-9]+\Z")

# Compatibility defaults for modules imported before a configuration is loaded.
MUSIC_ROOT = Path(r"/ruta/a/MiDiscoteca")
DEFAULT_YEAR_MARGIN = 5
DEFAULT_SIZE_MB = 8000.0
DEFAULT_MAX_ALBUM = 2
# 0 conserva el comportamiento histórico: sin cuota por artista de pista.
DEFAULT_MAX_ARTIST = 0
CACHE_FILENAME = ".playlist_catalog.json"
MIN_REASONABLE_YEAR = 1000
MAX_REASONABLE_YEAR_OFFSET = 1
AUDIO_EXTENSIONS = frozenset({".mp3", ".flac", ".m4a", ".mp4", ".ogg", ".opus", ".ape"})


class ConfigError(ValueError):
    """An actionable error in a user configuration file."""


@dataclass(frozen=True, slots=True)
class Settings:
    music_root: Path
    default_year_margin: int
    default_size_mb: float
    default_max_album: int
    default_max_artist: int
    cache_filename: str
    min_reasonable_year: int
    max_reasonable_year_offset: int
    audio_extensions: frozenset[str]
    surprise_mode: bool
    preview_entries: int
    copy_structure: str
    source: Path


def _packaged_config_path() -> Path:
    return Path(__file__).resolve().parent / "config.ini"


def _user_config_path() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "Playlist Builder" / "config.ini"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Playlist Builder" / "config.ini"
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "playlist-builder" / "config.ini"


def default_config_path() -> Path:
    """Return a writable user config, except when running from a source checkout."""
    package_directory = Path(__file__).resolve().parent
    project = package_directory.parent / "config.ini"
    if project.is_file():
        return project

    entry = Path(sys.argv[0]).resolve()
    beside_entry = entry.parent / "config.ini"
    if entry.stem.casefold().replace("_", "-") == "crear-playlist" and beside_entry.is_file():
        return beside_entry
    return _user_config_path()


def _install_default_config(source: Path) -> None:
    template = _packaged_config_path()
    try:
        content = template.read_bytes()
        source.parent.mkdir(parents=True, exist_ok=True)
        try:
            with source.open("xb") as stream:
                stream.write(content)
        except FileExistsError:
            pass
    except OSError as exc:
        raise ConfigError(
            f"No se pudo crear la configuración editable {source} desde {template}: {exc}"
        ) from exc


def _problem(path: Path, key: str, message: str) -> ConfigError:
    return ConfigError(f"{path} [{SECTION}] {key}: {message}")


def _publish_compatibility_defaults(settings: Settings) -> None:
    global MUSIC_ROOT, DEFAULT_YEAR_MARGIN, DEFAULT_SIZE_MB, DEFAULT_MAX_ALBUM, DEFAULT_MAX_ARTIST
    global CACHE_FILENAME, MIN_REASONABLE_YEAR, MAX_REASONABLE_YEAR_OFFSET, AUDIO_EXTENSIONS
    MUSIC_ROOT = settings.music_root
    DEFAULT_YEAR_MARGIN = settings.default_year_margin
    DEFAULT_SIZE_MB = settings.default_size_mb
    DEFAULT_MAX_ALBUM = settings.default_max_album
    DEFAULT_MAX_ARTIST = settings.default_max_artist
    CACHE_FILENAME = settings.cache_filename
    MIN_REASONABLE_YEAR = settings.min_reasonable_year
    MAX_REASONABLE_YEAR_OFFSET = settings.max_reasonable_year_offset
    AUDIO_EXTENSIONS = settings.audio_extensions


def load_config(path: Path | str | None = None) -> Settings:
    source = Path(path).expanduser().resolve() if path is not None else default_config_path()
    if path is None and not source.exists():
        _install_default_config(source)

    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        with source.open(encoding="utf-8") as stream:
            parser.read_file(stream)
    except FileNotFoundError as exc:
        raise ConfigError(f"No se encontró el archivo de configuración: {source}") from exc
    except (OSError, UnicodeError, configparser.Error) as exc:
        raise ConfigError(f"No se pudo leer la configuración {source}: {exc}") from exc

    extra_sections = set(parser.sections()) - {SECTION}
    if extra_sections:
        section_name = sorted(extra_sections)[0]
        raise ConfigError(f"{source} [{section_name}]: sección desconocida")
    if SECTION not in parser:
        raise ConfigError(f"{source}: falta la sección [{SECTION}]")

    section = parser[SECTION]
    expected = {
        "music_root",
        "default_year_margin",
        "default_size_mb",
        "default_max_album",
        "default_max_artist",
        "cache_filename",
        "min_reasonable_year",
        "max_reasonable_year_offset",
        "audio_extensions",
        "surprise_mode",
        "preview_entries",
        "copy_structure",
    }
    missing = expected - set(section)
    if missing:
        key = sorted(missing)[0]
        raise _problem(source, key, "falta la clave obligatoria")
    unknown = set(section) - expected
    if unknown:
        key = sorted(unknown)[0]
        raise _problem(source, key, "clave desconocida")

    def positive_int(key: str) -> int:
        try:
            value = int(section[key])
        except ValueError as exc:
            raise _problem(source, key, "debe ser un entero positivo") from exc
        if value <= 0:
            raise _problem(source, key, "debe ser mayor que cero")
        return value

    def positive_float(key: str) -> float:
        try:
            value = float(section[key])
        except ValueError as exc:
            raise _problem(source, key, "debe ser un número positivo") from exc
        if not math.isfinite(value) or value <= 0:
            raise _problem(source, key, "debe ser un número finito mayor que cero")
        return value

    def nonnegative_int(key: str) -> int:
        try:
            value = int(section[key])
        except ValueError as exc:
            raise _problem(source, key, "debe ser un entero no negativo") from exc
        if value < 0:
            raise _problem(source, key, "no puede ser negativo")
        return value

    raw_root = section["music_root"].strip()
    if not raw_root:
        raise _problem(source, "music_root", "la ruta no puede estar vacía")
    root = Path(raw_root).expanduser()
    if not root.is_absolute():
        root = source.parent / root

    cache = section["cache_filename"].strip()
    if (
        not cache
        or Path(cache).name != cache
        or cache in {".", ".."}
        or "/" in cache
        or "\\" in cache
    ):
        raise _problem(source, "cache_filename", "debe ser un nombre de archivo, no una ruta")

    minimum = positive_int("min_reasonable_year")
    if minimum > datetime.now().year:
        raise _problem(source, "min_reasonable_year", "no puede ser posterior al año actual")
    try:
        offset = int(section["max_reasonable_year_offset"])
    except ValueError as exc:
        raise _problem(
            source, "max_reasonable_year_offset", "debe ser un entero entre 0 y 100"
        ) from exc
    if not 0 <= offset <= 100:
        raise _problem(source, "max_reasonable_year_offset", "debe estar entre 0 y 100")

    raw_extensions = [item.strip().casefold() for item in section["audio_extensions"].split(",")]
    if not raw_extensions or any(not item for item in raw_extensions):
        raise _problem(source, "audio_extensions", "use extensiones separadas por comas")
    invalid = next((item for item in raw_extensions if not _EXTENSION.fullmatch(item)), None)
    if invalid is not None:
        raise _problem(source, "audio_extensions", f"extensión no válida: {invalid!r}")
    if len(set(raw_extensions)) != len(raw_extensions):
        raise _problem(source, "audio_extensions", "contiene extensiones duplicadas")

    try:
        surprise_mode = section.getboolean("surprise_mode")
    except ValueError as exc:
        raise _problem(source, "surprise_mode", "debe ser true o false") from exc
    if surprise_mode is None:
        raise _problem(source, "surprise_mode", "falta la clave obligatoria")
    copy_structure = section["copy_structure"].strip().casefold()
    if copy_structure not in {"flat", "tree"}:
        raise _problem(source, "copy_structure", "debe ser 'flat' o 'tree'")

    settings = Settings(
        music_root=root.resolve(),
        default_year_margin=positive_int("default_year_margin"),
        default_size_mb=positive_float("default_size_mb"),
        default_max_album=positive_int("default_max_album"),
        default_max_artist=nonnegative_int("default_max_artist"),
        cache_filename=cache,
        min_reasonable_year=minimum,
        max_reasonable_year_offset=offset,
        audio_extensions=frozenset(raw_extensions),
        surprise_mode=surprise_mode,
        preview_entries=positive_int("preview_entries"),
        copy_structure=copy_structure,
        source=source,
    )
    _publish_compatibility_defaults(settings)
    return settings
