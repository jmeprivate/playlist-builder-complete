from __future__ import annotations

import configparser
import math
import os
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .normalization import normalize_for_search

SECTION = "playlist_builder"
GENRE_ALIASES_SECTION = "genre_aliases"
_EXTENSION = re.compile(r"\.[a-z0-9]+\Z")

# Compatibility defaults for modules imported before a configuration is loaded.
MUSIC_ROOT = Path(r"/ruta/a/MiDiscoteca")
DEFAULT_YEAR_MARGIN = 5
DEFAULT_SIZE_MB = 8000.0
DEFAULT_MAX_ALBUM = 2
DEFAULT_RETRY_ERROR_AFTER_DAYS = 7.0
# 0 conserva el comportamiento histórico: sin cuota por artista de pista.
DEFAULT_MAX_ARTIST = 0
CACHE_FILENAME = ".playlist_catalog.json"
CONFIG_FILENAME = "config.ini"
PROFILES_FILENAME = "filter_profiles.json"
MIN_REASONABLE_YEAR = 1000
MAX_REASONABLE_YEAR_OFFSET = 1
AUDIO_EXTENSIONS = frozenset({".mp3", ".flac", ".m4a", ".mp4", ".ogg", ".opus", ".ape"})


class ConfigError(ValueError):
    """An actionable error in a user configuration file."""


class _CasePreservingConfigParser(configparser.ConfigParser):
    def optionxform(self, optionstr: str) -> str:
        return optionstr


@dataclass(frozen=True, slots=True)
class GenreAliases:
    """Manual, display-preserving genre equivalences loaded from the INI."""

    canonical_displays: dict[str, str]
    alias_to_canonical: dict[str, str]

    def resolve(self, value: str) -> str:
        normalized = normalize_for_search(value)
        return self.alias_to_canonical.get(normalized, normalized)

    def display_options(self, values: Iterable[str]) -> tuple[str, ...]:
        by_normalized: dict[str, str] = {}
        for raw in values:
            display = " ".join(str(raw).split())
            normalized = normalize_for_search(display)
            if not normalized:
                continue
            resolved = self.alias_to_canonical.get(normalized, normalized)
            by_normalized.setdefault(resolved, self.canonical_displays.get(resolved, display))
        return tuple(by_normalized.values())


EMPTY_GENRE_ALIASES = GenreAliases({}, {})


@dataclass(frozen=True, slots=True)
class Settings:
    music_root: Path
    default_year_margin: int
    default_size_mb: float
    default_max_album: int
    retry_error_after_days: float
    default_max_artist: int
    cache_filename: str
    min_reasonable_year: int
    max_reasonable_year_offset: int
    audio_extensions: frozenset[str]
    surprise_mode: bool
    preview_entries: int
    copy_structure: str
    profiles_file: Path
    genre_aliases: GenreAliases
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
    global MUSIC_ROOT, DEFAULT_YEAR_MARGIN, DEFAULT_SIZE_MB, DEFAULT_MAX_ALBUM
    global DEFAULT_RETRY_ERROR_AFTER_DAYS
    global DEFAULT_MAX_ARTIST
    global CACHE_FILENAME, MIN_REASONABLE_YEAR, MAX_REASONABLE_YEAR_OFFSET, AUDIO_EXTENSIONS
    MUSIC_ROOT = settings.music_root
    DEFAULT_YEAR_MARGIN = settings.default_year_margin
    DEFAULT_SIZE_MB = settings.default_size_mb
    DEFAULT_MAX_ALBUM = settings.default_max_album
    DEFAULT_RETRY_ERROR_AFTER_DAYS = settings.retry_error_after_days
    DEFAULT_MAX_ARTIST = settings.default_max_artist
    CACHE_FILENAME = settings.cache_filename
    MIN_REASONABLE_YEAR = settings.min_reasonable_year
    MAX_REASONABLE_YEAR_OFFSET = settings.max_reasonable_year_offset
    AUDIO_EXTENSIONS = settings.audio_extensions


def load_config(path: Path | str | None = None) -> Settings:
    source = Path(path).expanduser().resolve() if path is not None else default_config_path()
    if path is None and not source.exists():
        _install_default_config(source)

    parser = _CasePreservingConfigParser(interpolation=None, strict=True)
    try:
        with source.open(encoding="utf-8") as stream:
            parser.read_file(stream)
    except FileNotFoundError as exc:
        raise ConfigError(f"No se encontró el archivo de configuración: {source}") from exc
    except configparser.ParsingError as exc:
        raise ConfigError(
            f"No se pudo leer la configuración {source}: formato INI no válido; "
            f"compruebe también que no haya una clave canónica vacía ({exc})"
        ) from exc
    except (OSError, UnicodeError, configparser.Error) as exc:
        raise ConfigError(f"No se pudo leer la configuración {source}: {exc}") from exc

    extra_sections = set(parser.sections()) - {SECTION, GENRE_ALIASES_SECTION}
    if extra_sections:
        section_name = sorted(extra_sections)[0]
        raise ConfigError(f"{source} [{section_name}]: sección desconocida")
    if SECTION not in parser:
        raise ConfigError(f"{source}: falta la sección [{SECTION}]")

    canonical_displays: dict[str, str] = {}
    alias_to_canonical: dict[str, str] = {}
    alias_items = (
        parser.items(GENRE_ALIASES_SECTION, raw=True)
        if parser.has_section(GENRE_ALIASES_SECTION)
        else ()
    )
    for raw_canonical, raw_value in alias_items:
        canonical = " ".join(raw_canonical.split())
        canonical_normalized = normalize_for_search(canonical)
        if not canonical_normalized:
            raise ConfigError(
                f"{source} [{GENRE_ALIASES_SECTION}]: la clave canónica no puede estar vacía"
            )
        if canonical_normalized in canonical_displays:
            previous_display = canonical_displays[canonical_normalized]
            raise ConfigError(
                f"{source} [{GENRE_ALIASES_SECTION}] {canonical}: la clave canónica coincide con "
                f"{previous_display!r} tras normalizar; declárela una sola vez"
            )
        aliases = raw_value.split(";")
        if any(not alias.strip() for alias in aliases):
            raise ConfigError(
                f"{source} [{GENRE_ALIASES_SECTION}] {canonical}: "
                "los alias separados por ';' no pueden estar vacíos"
            )
        for value in (canonical, *aliases):
            normalized = normalize_for_search(value)
            previous = alias_to_canonical.get(normalized)
            if previous is not None and previous != canonical_normalized:
                other = canonical_displays[previous]
                raise ConfigError(
                    f"{source} [{GENRE_ALIASES_SECTION}] {canonical}: {value.strip()!r} "
                    f"también está asignado a {other!r}; el alias es ambiguo"
                )
            alias_to_canonical[normalized] = canonical_normalized
        canonical_displays[canonical_normalized] = canonical

    section: dict[str, str] = {}
    original_names: dict[str, str] = {}
    for raw_key, value in parser.items(SECTION, raw=True):
        key = raw_key.casefold()
        if key in section:
            raise _problem(
                source,
                raw_key,
                f"duplica la clave {original_names[key]!r} al ignorar mayúsculas",
            )
        section[key] = value
        original_names[key] = raw_key

    expected = {
        "music_root",
        "default_year_margin",
        "default_size_mb",
        "default_max_album",
        "retry_error_after_days",
        "default_max_artist",
        "cache_filename",
        "min_reasonable_year",
        "max_reasonable_year_offset",
        "audio_extensions",
        "surprise_mode",
        "preview_entries",
        "copy_structure",
        "profiles_file",
    }
    # profiles_file was added after the original INI format.  Keeping a safe
    # default beside the selected INI lets existing user configurations update
    # without becoming unusable.
    missing = expected - {"profiles_file"} - set(section)
    if missing:
        key = sorted(missing)[0]
        raise _problem(source, key, "falta la clave obligatoria")
    unknown = set(section) - expected
    if unknown:
        key = sorted(unknown)[0]
        raise _problem(source, original_names[key], "clave desconocida")

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

    def nonnegative_float(key: str) -> float:
        try:
            value = float(section[key])
        except ValueError as exc:
            raise _problem(source, key, "debe ser un número no negativo") from exc
        if not math.isfinite(value) or value < 0:
            raise _problem(source, key, "debe ser un número finito no negativo")
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

    raw_surprise = section["surprise_mode"].strip().casefold()
    if raw_surprise in {"1", "yes", "true", "on"}:
        surprise_mode = True
    elif raw_surprise in {"0", "no", "false", "off"}:
        surprise_mode = False
    else:
        raise _problem(source, "surprise_mode", "debe ser true o false")

    copy_structure = section["copy_structure"].strip().casefold()
    if copy_structure not in {"flat", "tree"}:
        raise _problem(source, "copy_structure", "debe ser 'flat' o 'tree'")

    raw_profiles = section.get("profiles_file", PROFILES_FILENAME).strip()
    if not raw_profiles:
        raise _problem(source, "profiles_file", "la ruta no puede estar vacía")
    profiles_file = Path(raw_profiles).expanduser()
    if not profiles_file.is_absolute():
        profiles_file = source.parent / profiles_file

    settings = Settings(
        music_root=root.resolve(),
        default_year_margin=positive_int("default_year_margin"),
        default_size_mb=positive_float("default_size_mb"),
        default_max_album=positive_int("default_max_album"),
        retry_error_after_days=nonnegative_float("retry_error_after_days"),
        default_max_artist=nonnegative_int("default_max_artist"),
        cache_filename=cache,
        min_reasonable_year=minimum,
        max_reasonable_year_offset=offset,
        audio_extensions=frozenset(raw_extensions),
        surprise_mode=surprise_mode,
        preview_entries=positive_int("preview_entries"),
        copy_structure=copy_structure,
        profiles_file=profiles_file.resolve(),
        genre_aliases=GenreAliases(canonical_displays, alias_to_canonical),
        source=source,
    )
    _publish_compatibility_defaults(settings)
    return settings
