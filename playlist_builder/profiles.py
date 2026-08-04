"""Versioned, human-readable filter profiles with atomic persistence."""

from __future__ import annotations

import json
import os
import re
import tempfile
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

VERSION = 1
_NAME = re.compile(r"[^/\\\x00-\x1f]{1,80}\Z")
_LIST_FIELDS = (
    "included_artists",
    "excluded_artists",
    "included_album_artists",
    "excluded_album_artists",
    "included_genres",
    "excluded_genres",
)
_FIELDS = frozenset((*_LIST_FIELDS, "year_min", "year_max", "max_album", "max_artist", "size_mb"))


class ProfileError(ValueError):
    """A profile store is malformed or cannot satisfy the request."""


@dataclass(slots=True)
class FilterProfile:
    included_artists: list[str] = field(default_factory=list)
    excluded_artists: list[str] = field(default_factory=list)
    included_album_artists: list[str] = field(default_factory=list)
    excluded_album_artists: list[str] = field(default_factory=list)
    included_genres: list[str] = field(default_factory=list)
    excluded_genres: list[str] = field(default_factory=list)
    year_min: int | None = None
    year_max: int | None = None
    max_album: int = 2
    max_artist: int | None = None
    size_mb: float = 8000.0

    def to_dict(self) -> dict[str, Any]:
        return {
            name: getattr(self, name)
            for name in (
                *_LIST_FIELDS,
                "year_min",
                "year_max",
                "max_album",
                "max_artist",
                "size_mb",
            )
        }


def validate_name(name: str) -> str:
    if name != name.strip() or not _NAME.fullmatch(name) or name in {".", ".."}:
        raise ProfileError(
            "nombre de perfil no válido: use de 1 a 80 caracteres, sin controles ni '/' o '\\'"
        )
    return name


def _profile(value: Any, name: str) -> FilterProfile:
    if not isinstance(value, dict):
        raise ProfileError(f"el perfil {name!r} debe ser un objeto JSON")
    unknown = set(value) - _FIELDS
    if unknown:
        raise ProfileError(
            f"el perfil {name!r} contiene el campo desconocido {sorted(unknown)[0]!r}"
        )
    missing = _FIELDS - set(value)
    if missing:
        raise ProfileError(f"el perfil {name!r} no contiene el campo {sorted(missing)[0]!r}")
    for key in _LIST_FIELDS:
        items = value[key]
        if not isinstance(items, list) or any(
            not isinstance(item, str) or not item.strip() for item in items
        ):
            raise ProfileError(
                f"el campo {key!r} del perfil {name!r} debe ser una lista de textos no vacíos"
            )
        if len(items) != len(set(items)):
            raise ProfileError(f"el campo {key!r} del perfil {name!r} contiene duplicados")
    for key in ("year_min", "year_max"):
        if value[key] is not None and (
            isinstance(value[key], bool) or not isinstance(value[key], int)
        ):
            raise ProfileError(f"el campo {key!r} del perfil {name!r} debe ser un entero o null")
    if (
        value["year_min"] is not None
        and value["year_max"] is not None
        and value["year_min"] > value["year_max"]
    ):
        raise ProfileError(f"el perfil {name!r} tiene un intervalo de años invertido")
    if (
        isinstance(value["max_album"], bool)
        or not isinstance(value["max_album"], int)
        or value["max_album"] <= 0
    ):
        raise ProfileError(f"max_album del perfil {name!r} debe ser un entero positivo")
    maximum_artist = value["max_artist"]
    if maximum_artist is not None and (
        isinstance(maximum_artist, bool)
        or not isinstance(maximum_artist, int)
        or maximum_artist <= 0
    ):
        raise ProfileError(f"max_artist del perfil {name!r} debe ser un entero positivo o null")
    size = value["size_mb"]
    if (
        isinstance(size, bool)
        or not isinstance(size, (int, float))
        or not (0 < float(size) < float("inf"))
    ):
        raise ProfileError(f"size_mb del perfil {name!r} debe ser un número positivo finito")
    return FilterProfile(
        included_artists=list(value["included_artists"]),
        excluded_artists=list(value["excluded_artists"]),
        included_album_artists=list(value["included_album_artists"]),
        excluded_album_artists=list(value["excluded_album_artists"]),
        included_genres=list(value["included_genres"]),
        excluded_genres=list(value["excluded_genres"]),
        year_min=value["year_min"],
        year_max=value["year_max"],
        max_album=value["max_album"],
        max_artist=value["max_artist"],
        size_mb=float(value["size_mb"]),
    )


def load_profiles(path: Path) -> dict[str, FilterProfile]:
    if not path.exists():
        return {}
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProfileError(f"no se pudo leer el archivo de perfiles {path}: {exc}") from exc
    if not isinstance(document, dict) or set(document) != {"version", "profiles"}:
        raise ProfileError(f"archivo de perfiles {path}: se esperaban 'version' y 'profiles'")
    if document["version"] != VERSION:
        raise ProfileError(
            f"archivo de perfiles {path}: versión desconocida {document['version']!r}"
        )
    if not isinstance(document["profiles"], dict):
        raise ProfileError(f"archivo de perfiles {path}: 'profiles' debe ser un objeto")
    result: dict[str, FilterProfile] = {}
    for name, value in document["profiles"].items():
        if not isinstance(name, str):
            raise ProfileError("todos los nombres de perfil deben ser textos")
        validate_name(name)
        result[name] = _profile(value, name)
    return result


def save_profiles_atomic(path: Path, profiles: dict[str, FilterProfile]) -> None:
    payload = {
        "version": VERSION,
        "profiles": {name: profile.to_dict() for name, profile in sorted(profiles.items())},
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        descriptor, raw = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
        temporary = Path(raw)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        temporary = None
        # Make the rename durable on POSIX. Other platforms may reject opening
        # a directory, in which case the atomic replacement is still retained.
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    except OSError as exc:
        raise ProfileError(f"no se pudo guardar el archivo de perfiles {path}: {exc}") from exc
    finally:
        if temporary is not None:
            with suppress(FileNotFoundError):
                temporary.unlink()


def format_profile_summary(name: str, profile: FilterProfile) -> str:
    filters = sum(len(getattr(profile, key)) for key in _LIST_FIELDS)
    years = (
        "sin años"
        if profile.year_min is None and profile.year_max is None
        else f"años {profile.year_min or '…'}-{profile.year_max or '…'}"
    )
    artist = profile.max_artist if profile.max_artist is not None else "sin límite"
    return (
        f"{name}: {filters} selecciones, {years}, {profile.size_mb:g} MB, "
        f"álbum {profile.max_album}, artista {artist}"
    )
