from __future__ import annotations

import hashlib
import logging
from collections import defaultdict
from pathlib import Path

from .models import Song

LOGGER = logging.getLogger(__name__)
HASH_BLOCK_SIZE = 1024 * 1024


def _stable_path_key(song: Song) -> tuple[str, str]:
    relative = song.relative_path.as_posix()
    return relative.casefold(), relative


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(HASH_BLOCK_SIZE):
            digest.update(block)
    return digest.hexdigest()


def deduplicate_songs(songs: list[Song]) -> list[Song]:
    """Remove content duplicates, keeping the most stable relative path.

    Only size-collision groups are read.  A file that cannot be hashed remains a
    candidate because its content identity could not be established.

    Grouping relies on ``song.size_bytes`` from the scan/cache rather than a fresh
    ``stat()``.  If a file changed on disk since the last scan without invalidating
    its cache entry, two files with identical current content may land in different
    size buckets and never be compared.  This can only miss a deduplication (files
    are never removed unless their hashes match), so it is a benign inconsistency.
    """
    by_size: dict[int, list[tuple[int, Song]]] = defaultdict(list)
    for index, song in enumerate(songs):
        by_size[song.size_bytes].append((index, song))

    collision_groups = [group for group in by_size.values() if len(group) >= 2]
    hash_candidates = sum(map(len, collision_groups))
    LOGGER.info(
        "Deduplicación: %d candidatas; %d requieren hash en %d grupos de tamaño",
        len(songs),
        hash_candidates,
        len(collision_groups),
    )
    removed: set[int] = set()
    for size_group in collision_groups:
        by_digest: dict[str, list[tuple[int, Song]]] = defaultdict(list)
        for index, song in sorted(size_group, key=lambda item: _stable_path_key(item[1])):
            try:
                digest = _sha256(song.path)
            except OSError as exc:
                LOGGER.warning("No se pudo calcular SHA-256 de %s: %s", song.relative_path, exc)
                continue
            LOGGER.debug("SHA-256 %s %s", digest, song.relative_path)
            by_digest[digest].append((index, song))
        for digest, identical in by_digest.items():
            if len(identical) < 2:
                continue
            # ``identical`` is already in stable order (built from a sorted scan).
            representative = identical[0][1]
            removed.update(index for index, _ in identical[1:])
            LOGGER.info(
                "Duplicadas SHA-256 %s: se conserva %s; se omiten %s",
                digest,
                representative.relative_path,
                ", ".join(song.relative_path.as_posix() for _, song in identical[1:]),
            )

    return [song for index, song in enumerate(songs) if index not in removed]
