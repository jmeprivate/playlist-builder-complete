from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from .models import Song
from .normalization import normalize_for_search


@dataclass(frozen=True, slots=True)
class SelectionResult:
    songs: list[Song]
    skipped_by_artist_quota: int


def select_balanced(
    candidates: list[Song],
    max_size_bytes: int,
    max_per_album: int,
    seed: int | random.Random | None = None,
    max_per_artist: int | None = None,
) -> list[Song]:
    return select_balanced_with_stats(
        candidates, max_size_bytes, max_per_album, seed, max_per_artist
    ).songs


def select_balanced_with_stats(
    candidates: list[Song],
    max_size_bytes: int,
    max_per_album: int,
    seed: int | random.Random | None = None,
    max_per_artist: int | None = None,
) -> SelectionResult:
    if max_size_bytes <= 0:
        raise ValueError("max_size_bytes debe ser positivo")
    if max_per_album <= 0:
        raise ValueError("max_per_album debe ser positivo")
    if max_per_artist is not None and max_per_artist < 0:
        raise ValueError("max_per_artist no puede ser negativo")
    artist_limit = max_per_artist or None
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
    selected_per_artist: dict[str, int] = defaultdict(int)
    skipped_by_artist_quota = 0
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
                # Una colaboración consume un cupo de cada Artist distinto. AlbumArtist no
                # participa en esta cuota.
                candidate_artists = {
                    normalized
                    for artist in candidate.artist
                    if (normalized := normalize_for_search(artist))
                }
                if artist_limit is not None and any(
                    selected_per_artist[artist] >= artist_limit for artist in candidate_artists
                ):
                    skipped_by_artist_quota += 1
                    continue
                if total + candidate.size_bytes <= max_size_bytes:
                    chosen = candidate
                    break
                # La capacidad solo disminuye; esta canción ya nunca podrá entrar.
            if chosen is not None:
                selected.append(chosen)
                selected_per_album[album] += 1
                for artist in candidate_artists:
                    selected_per_artist[artist] += 1
                total += chosen.size_bytes
                added_this_round = True
        if not added_this_round:
            break
    return SelectionResult(selected, skipped_by_artist_quota)


def estimate_selection_count(
    candidates: list[Song],
    max_size_bytes: int,
    max_per_album: int,
    seed: int | random.Random | None = None,
    max_per_artist: int | None = None,
) -> int:
    return len(select_balanced(candidates, max_size_bytes, max_per_album, seed, max_per_artist))
