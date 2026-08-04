from __future__ import annotations

import configparser
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from mutagen import MutagenError

from .cache import (
    CacheEntry,
    CacheHealth,
    CatalogCache,
    load_catalog_cache,
    utc_now,
    write_catalog_cache,
)
from .config import (
    AUDIO_EXTENSIONS,
    CACHE_FILENAME,
    CONFIG_FILENAME,
    DEFAULT_RETRY_ERROR_AFTER_DAYS,
)
from .metadata import read_song
from .models import AuditIssue, AuditReport, Song

LOGGER = logging.getLogger(__name__)
MetadataReader = Callable[[Path, Path], Song]


def _is_inside(path: Path, parent: Path | None) -> bool:
    if parent is None:
        return False
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _is_stale_copy_stage(relative: Path) -> bool:
    return any(part.startswith(".playlist-copy-") for part in relative.parts)


def _retry_days(root: Path) -> float:
    parser = configparser.ConfigParser()
    path = root / CONFIG_FILENAME
    try:
        parser.read(path, encoding="utf-8")
        value = parser.getfloat(
            "cache", "retry_error_after_days", fallback=DEFAULT_RETRY_ERROR_AFTER_DAYS
        )
        if value < 0:
            raise ValueError("retry_error_after_days no puede ser negativo")
        return value
    except (OSError, configparser.Error, ValueError) as exc:
        LOGGER.warning("Se ignora la configuración de caché %s: %s", path, exc)
        return DEFAULT_RETRY_ERROR_AFTER_DAYS


def _error_retry_due(entry: CacheEntry, now: datetime, days: float) -> bool:
    if not entry.error or not entry.error_at:
        return bool(entry.error)
    try:
        recorded = datetime.fromisoformat(entry.error_at)
        if recorded.tzinfo is None:
            recorded = recorded.replace(tzinfo=UTC)
    except ValueError:
        return True
    return now - recorded >= timedelta(days=days)


def scan_library(
    root: Path,
    *,
    rescan: bool = False,
    excluded_root: Path | None = None,
    metadata_reader: MetadataReader = read_song,
    retry_error_after_days: float | None = None,
) -> tuple[list[Song], AuditReport]:
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"La raíz musical no existe o no es un directorio: {root}")
    excluded = excluded_root.expanduser().resolve() if excluded_root is not None else None
    cache_path = root / CACHE_FILENAME
    loaded = load_catalog_cache(cache_path, root)
    old_cache = loaded.files
    retry_days = _retry_days(root) if retry_error_after_days is None else retry_error_after_days
    started = utc_now()
    # Publicar primero completed=false impide que una muerte abrupta legitime el escaneo anterior.
    health = CacheHealth(
        started, None, False, loaded.health.last_read_at, dict(loaded.health.errors)
    )
    write_catalog_cache(cache_path, CatalogCache(dict(old_cache), health))
    new_cache: dict[str, CacheEntry] = {}
    songs: list[Song] = []
    report = AuditReport()

    try:
        paths = sorted(
            (
                path
                for path in root.rglob("*")
                if path.is_file()
                and path.suffix.casefold() in AUDIO_EXTENSIONS
                and not _is_inside(path.resolve(), excluded)
                and not _is_stale_copy_stage(path.relative_to(root))
            ),
            key=lambda item: (
                item.relative_to(root).as_posix().casefold(),
                item.relative_to(root).as_posix(),
            ),
        )
        report.total_audio_files = len(paths)
        now = datetime.now(UTC)
        for path in paths:
            relative = path.relative_to(root)
            key = relative.as_posix()
            try:
                stat = path.stat()
            except OSError as exc:
                report.issues.append(AuditIssue(relative, error=str(exc)))
                continue
            cached = old_cache.get(key)
            unchanged = (
                cached is not None
                and cached.size == stat.st_size
                and cached.mtime_ns == stat.st_mtime_ns
            )
            reuse = (
                cached is not None
                and unchanged
                and not rescan
                and not _error_retry_due(cached, now, retry_days)
            )
            if reuse:
                assert cached is not None
                song, error, error_at = cached.song, cached.error, cached.error_at
                LOGGER.debug("Caché válida: %s", relative)
            else:
                try:
                    song = metadata_reader(path, root)
                    error = error_at = None
                    LOGGER.debug("Metadatos leídos: %s", relative)
                except (OSError, ValueError, TypeError, UnicodeError, MutagenError) as exc:
                    song = None
                    error = f"{type(exc).__name__}: {exc}"
                    error_at = utc_now()
                    LOGGER.warning("No se pudieron leer metadatos de %s: %s", relative, exc)
            new_cache[key] = CacheEntry(stat.st_size, stat.st_mtime_ns, song, error, error_at)
            if song is None:
                report.issues.append(AuditIssue(relative, error=error or "error desconocido"))
                continue
            songs.append(song)
            missing = tuple(
                name
                for name, absent in (
                    ("Artist", not song.artist),
                    ("Genre", not song.genres),
                    ("Year", song.year is None),
                )
                if absent
            )
            if missing:
                report.issues.append(
                    AuditIssue(
                        relative,
                        missing_tags=missing,
                        informational_tags=("AlbumArtist",) if not song.album_artists else (),
                    )
                )
            elif not song.album_artists:
                report.issues.append(AuditIssue(relative, informational_tags=("AlbumArtist",)))
    except BaseException:
        # No se podan entradas: el recorrido no demostró que hayan desaparecido.
        retained = dict(old_cache)
        retained.update(new_cache)
        health.errors = {key: entry.error for key, entry in retained.items() if entry.error}
        write_catalog_cache(cache_path, CatalogCache(retained, health))
        raise

    health.scan_finished_at = utc_now()
    health.completed = True
    health.errors = {key: entry.error for key, entry in new_cache.items() if entry.error}
    write_catalog_cache(cache_path, CatalogCache(new_cache, health))
    return songs, report
