from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Song

LOGGER = logging.getLogger(__name__)
CACHE_VERSION = 1


@dataclass(frozen=True, slots=True)
class CacheEntry:
    size: int
    mtime_ns: int
    song: Song | None
    error: str | None


def load_cache(path: Path, root: Path) -> dict[str, CacheEntry]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if raw.get("version") != CACHE_VERSION or not isinstance(raw.get("files"), dict):
            raise ValueError("versión o estructura incompatible")
        entries: dict[str, CacheEntry] = {}
        for relative, value in raw["files"].items():
            song_data = value.get("song")
            entries[str(relative)] = CacheEntry(
                size=int(value["size"]),
                mtime_ns=int(value["mtime_ns"]),
                song=Song.from_cache_dict(root, song_data) if song_data else None,
                error=str(value["error"]) if value.get("error") else None,
            )
        LOGGER.info("Cargadas %d entradas de caché", len(entries))
        return entries
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        LOGGER.warning("Se ignora la caché %s: %s", path, exc)
        return {}


def write_cache(path: Path, entries: dict[str, CacheEntry]) -> None:
    data: dict[str, Any] = {
        "version": CACHE_VERSION,
        "files": {
            relative: {
                "size": entry.size,
                "mtime_ns": entry.mtime_ns,
                "song": entry.song.to_cache_dict() if entry.song else None,
                "error": entry.error,
            }
            for relative, entry in sorted(entries.items())
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except OSError as exc:
        LOGGER.warning("No se pudo escribir la caché %s: %s", path, exc)
        if temporary is not None:
            temporary.unlink(missing_ok=True)
