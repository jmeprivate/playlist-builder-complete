from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

from mutagen import MutagenError

from .cache import CacheEntry, load_cache, write_cache
from .config import AUDIO_EXTENSIONS, CACHE_FILENAME
from .metadata import read_song
from .models import AuditIssue, AuditReport, Song
from .progress import ProgressCallback, ScanProgress

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


def scan_library(
    root: Path,
    *,
    rescan: bool = False,
    excluded_root: Path | None = None,
    metadata_reader: MetadataReader = read_song,
    progress: ProgressCallback | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[list[Song], AuditReport]:
    started_at = clock()
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"La raíz musical no existe o no es un directorio: {root}")
    excluded = excluded_root.expanduser().resolve() if excluded_root is not None else None
    cache_path = root / CACHE_FILENAME
    old_cache = {} if rescan else load_cache(cache_path, root)
    new_cache: dict[str, CacheEntry] = {}
    songs: list[Song] = []
    report = AuditReport()

    if progress is not None:
        progress(ScanProgress(phase="discovery_started"))
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
    if progress is not None:
        progress(ScanProgress(phase="discovery_complete", total=len(paths)))

    cached_count = 0
    error_count = 0
    for processed_count, path in enumerate(paths, start=1):
        relative = path.relative_to(root)
        key = relative.as_posix()
        try:
            stat = path.stat()
        except OSError as exc:
            report.issues.append(AuditIssue(relative, error=str(exc)))
            error_count += 1
            if progress is not None:
                progress(ScanProgress("file_processed", processed_count, len(paths), len(songs), cached_count, error_count, clock() - started_at))
            continue
        cached = old_cache.get(key)
        if cached and cached.size == stat.st_size and cached.mtime_ns == stat.st_mtime_ns:
            song, error = cached.song, cached.error
            cached_count += 1
            LOGGER.debug("Caché válida: %s", relative)
        else:
            try:
                song = metadata_reader(path, root)
                error = None
                LOGGER.debug("Metadatos leídos: %s", relative)
            except (OSError, ValueError, TypeError, UnicodeError, MutagenError) as exc:
                song = None
                error = f"{type(exc).__name__}: {exc}"
                LOGGER.warning("No se pudieron leer metadatos de %s: %s", relative, exc)
        new_cache[key] = CacheEntry(stat.st_size, stat.st_mtime_ns, song, error)
        if song is None:
            report.issues.append(AuditIssue(relative, error=error or "error desconocido"))
            error_count += 1
        else:
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
            informational = ("AlbumArtist",) if not song.album_artists else ()
            if missing or informational:
                report.issues.append(
                    AuditIssue(relative, missing_tags=missing, informational_tags=informational)
                )
        if progress is not None:
            progress(ScanProgress("file_processed", processed_count, len(paths), len(songs), cached_count, error_count, clock() - started_at))

    write_cache(cache_path, new_cache)
    if progress is not None:
        progress(ScanProgress("complete", len(paths), len(paths), len(songs), cached_count, error_count, clock() - started_at))
    return songs, report
