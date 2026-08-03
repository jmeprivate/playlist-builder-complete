from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import Song

LOGGER = logging.getLogger(__name__)
CACHE_VERSION = 2


@dataclass(frozen=True, slots=True)
class CacheEntry:
    size: int
    mtime_ns: int
    song: Song | None
    error: str | None


def _payload_digest(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def load_cache(path: Path, root: Path) -> dict[str, CacheEntry]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("estructura incompatible")
        digest = raw.get("digest")
        payload = {key: value for key, value in raw.items() if key != "digest"}
        if not isinstance(digest, str) or not hashlib.compare_digest(
            digest, _payload_digest(payload)
        ):
            raise ValueError("la caché fue modificada o está dañada")
        if payload.get("version") != CACHE_VERSION or not isinstance(payload.get("files"), dict):
            raise ValueError("versión o estructura incompatible")
        entries: dict[str, CacheEntry] = {}
        for relative, value in payload["files"].items():
            if not isinstance(value, dict):
                raise ValueError("entrada de caché incompatible")
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
    payload: dict[str, Any] = {
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
    data = {**payload, "digest": _payload_digest(payload)}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(data, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
