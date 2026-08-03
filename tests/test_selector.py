from collections import Counter
from collections.abc import Callable

from playlist_builder.models import Song
from playlist_builder.selector import select_balanced


def test_max_album_and_size_limits(song_factory: Callable[..., Song]) -> None:
    songs = [
        song_factory(album_directory=f"Artist/Album-{album}", size_bytes=100)
        for album in range(3)
        for _ in range(3)
    ]
    selected = select_balanced(songs, 500, 2, seed=1)
    counts = Counter(song.album_directory for song in selected)
    assert sum(song.size_bytes for song in selected) <= 500
    assert max(counts.values()) <= 2
    assert len(selected) == 5


def test_large_song_does_not_block_smaller_ones(song_factory: Callable[..., Song]) -> None:
    songs = [
        song_factory(album_directory="A/One", size_bytes=1000),
        song_factory(album_directory="B/Two", size_bytes=200),
        song_factory(album_directory="C/Three", size_bytes=300),
    ]
    selected = select_balanced(songs, 500, 1, seed=7)
    assert sum(song.size_bytes for song in selected) == 500


def test_seed_is_reproducible(song_factory: Callable[..., Song]) -> None:
    songs = [song_factory(album_directory=f"A/Album-{i // 4}") for i in range(20)]
    first = select_balanced(songs, 1_000, 2, seed=123)
    second = select_balanced(list(reversed(songs)), 1_000, 2, seed=123)
    assert [song.relative_path for song in first] == [song.relative_path for song in second]
