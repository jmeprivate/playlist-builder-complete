from __future__ import annotations

import random
from collections import defaultdict
from pathlib import Path

from .models import Song


def select_balanced(
    candidates: list[Song],
    max_size_bytes: int,
    max_per_album: int,
    seed: int | random.Random | None = None,
) -> list[Song]:
    if max_size_bytes <= 0:
        raise ValueError("max_size_bytes debe ser positivo")
    if max_per_album <= 0:
        raise ValueError("max_per_album debe ser positivo")
    randomizer = seed if isinstance(seed, random.Random) else random.Random(seed)
    grouped: dict[Path, list[Song]] = defaultdict(list)
    for song in sorted(
        candidates,
        key=lambda item: (
            item.relative_path.as_posix().casefold(),
            item.relative_path.as_posix(),
        ),
    ):
        grouped[song.album_directory].append(song)
    album_keys = sorted(grouped, key=lambda path: (path.as_posix().casefold(), path.as_posix()))
    for songs in grouped.values():
        randomizer.shuffle(songs)
    randomizer.shuffle(album_keys)

    selected: list[Song] = []
    selected_per_album: dict[Path, int] = defaultdict(int)
    total = 0
    while True:
        added_this_round = False
        for album in album_keys:
            if selected_per_album[album] >= max_per_album:
                continue
            pool = grouped[album]
            chosen: Song | None = None
            while pool:
                candidate = pool.pop()
                if total + candidate.size_bytes <= max_size_bytes:
                    chosen = candidate
                    break
                # La capacidad solo disminuye; esta canción ya nunca podrá entrar.
            if chosen is not None:
                selected.append(chosen)
                selected_per_album[album] += 1
                total += chosen.size_bytes
                added_this_round = True
        if not added_this_round:
            break
    return selected


def estimate_selection_count(
    candidates: list[Song], max_size_bytes: int, max_per_album: int, seed: int | None = None
) -> int:
    return len(select_balanced(candidates, max_size_bytes, max_per_album, seed))
