from __future__ import annotations

import json
import logging
import os
import tempfile
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from .models import Song

LOGGER = logging.getLogger(__name__)
# El formato completo (entradas y metadatos de salud) se invalida como una unidad.
CACHE_VERSION = 3


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True, slots=True)
class CacheEntry:
    size: int
    mtime_ns: int
    song: Song | None
    error: str | None
    error_at: str | None = None


@dataclass(slots=True)
class CacheHealth:
    scan_started_at: str | None = None
    scan_finished_at: str | None = None
    completed: bool = False
    last_read_at: str | None = None
    errors: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class CatalogCache:
    files: dict[str, CacheEntry] = field(default_factory=dict)
    health: CacheHealth = field(default_factory=CacheHealth)


def _safe_relative(value: object) -> str:
    relative = str(value)
    parsed = PurePosixPath(relative)
    if parsed.is_absolute() or not relative or ".." in parsed.parts:
        raise ValueError(f"ruta no relativa en caché: {relative!r}")
    return relative


def load_catalog_cache(path: Path, root: Path) -> CatalogCache:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(raw, dict)
            or raw.get("version") != CACHE_VERSION
            or not isinstance(raw.get("files"), dict)
            or not isinstance(raw.get("health"), dict)
        ):
            raise ValueError("versión o estructura incompatible")
        entries: dict[str, CacheEntry] = {}
        for relative_value, value in raw["files"].items():
            relative = _safe_relative(relative_value)
            if not isinstance(value, dict):
                raise ValueError("entrada de archivo inválida")
            song_data = value.get("song")
            entries[relative] = CacheEntry(
                size=int(value["size"]),
                mtime_ns=int(value["mtime_ns"]),
                song=Song.from_cache_dict(root, song_data) if song_data else None,
                error=str(value["error"]) if value.get("error") else None,
                error_at=str(value["error_at"]) if value.get("error_at") else None,
            )
        health_raw = raw["health"]
        errors_raw = health_raw.get("errors", {})
        if not isinstance(errors_raw, dict):
            raise ValueError("resumen de errores inválido")
        health = CacheHealth(
            scan_started_at=health_raw.get("scan_started_at"),
            scan_finished_at=health_raw.get("scan_finished_at"),
            completed=health_raw.get("completed") is True,
            last_read_at=utc_now(),
            errors={_safe_relative(key): str(value) for key, value in errors_raw.items()},
        )
        LOGGER.info("Cargadas %d entradas de caché", len(entries))
        return CatalogCache(entries, health)
    except FileNotFoundError:
        return CatalogCache()
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        LOGGER.warning("Se ignora la caché %s: %s", path, exc)
        return CatalogCache()


def load_cache(path: Path, root: Path) -> dict[str, CacheEntry]:
    """API compatible: carga solo las entradas de una caché válida."""
    return load_catalog_cache(path, root).files


def write_catalog_cache(path: Path, cache: CatalogCache) -> bool:
    data: dict[str, Any] = {
        "version": CACHE_VERSION,
        "health": {
            "scan_started_at": cache.health.scan_started_at,
            "scan_finished_at": cache.health.scan_finished_at,
            "completed": cache.health.completed,
            "last_read_at": cache.health.last_read_at,
            "errors": dict(sorted(cache.health.errors.items())),
        },
        "files": {
            relative: {
                "size": entry.size,
                "mtime_ns": entry.mtime_ns,
                "song": entry.song.to_cache_dict() if entry.song else None,
                "error": entry.error,
                "error_at": entry.error_at,
            }
            for relative, entry in sorted(cache.files.items())
        },
    }
    temporary: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        # También hace durable el cambio de nombre en sistemas POSIX; en otros, se omite.
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
        return True
    except OSError as exc:
        LOGGER.warning("No se pudo escribir la caché %s: %s", path, exc)
        if temporary is not None:
            with suppress(OSError):
                temporary.unlink(missing_ok=True)
        return False


def write_cache(path: Path, entries: dict[str, CacheEntry]) -> bool:
    """API compatible para consumidores que no aportan datos de salud."""
    now = utc_now()
    errors = {key: entry.error for key, entry in entries.items() if entry.error}
    return write_catalog_cache(
        path,
        CatalogCache(entries, CacheHealth(now, now, True, None, errors)),
    )
