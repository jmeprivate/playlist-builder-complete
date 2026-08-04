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


def test_disabled_artist_quota_preserves_historical_result(
    song_factory: Callable[..., Song],
) -> None:
    songs = [song_factory(album_directory=f"A/Album-{i // 3}") for i in range(12)]
    historical = select_balanced(songs, 700, 2, seed=91)
    disabled = select_balanced(songs, 700, 2, seed=91, max_per_artist=0)
    assert [song.relative_path for song in disabled] == [song.relative_path for song in historical]


def test_artist_quota_applies_across_albums(song_factory: Callable[..., Song]) -> None:
    songs = [
        song_factory(artist=("Same Artist",), album_directory=f"Artist/Album-{album}")
        for album in range(4)
    ]
    assert len(select_balanced(songs, 1_000, 2, seed=3, max_per_artist=2)) == 2


def test_collaboration_consumes_quota_for_both_artists(
    song_factory: Callable[..., Song],
) -> None:
    songs = [
        song_factory(name="collab.mp3", artist=("Ana", "Bob"), album_directory="X/One"),
        song_factory(name="ana.mp3", artist=("Ana",), album_directory="X/Two"),
        song_factory(name="bob.mp3", artist=("Bob",), album_directory="X/Three"),
    ]
    selected = select_balanced(songs, 1_000, 2, seed=4, max_per_artist=1)
    counts = Counter(artist for song in selected for artist in set(song.artist))
    assert all(count <= 1 for count in counts.values())


def test_artist_quota_interacts_with_album_and_size_limits(
    song_factory: Callable[..., Song],
) -> None:
    songs = [
        song_factory(artist=(artist,), album_directory=album, size_bytes=size)
        for artist, album, size in [
            ("A", "A/One", 250),
            ("A", "A/One", 100),
            ("B", "B/Two", 200),
            ("C", "C/Three", 200),
        ]
    ]
    selected = select_balanced(songs, 400, 1, seed=8, max_per_artist=1)
    assert sum(song.size_bytes for song in selected) <= 400
    assert max(Counter(song.album_directory for song in selected).values()) <= 1
    assert max(Counter(artist for song in selected for artist in song.artist).values()) <= 1


def test_quota_rejection_keeps_trying_later_candidates_reproducibly(
    song_factory: Callable[..., Song],
) -> None:
    songs = [
        song_factory(name=f"{index}.mp3", artist=(artist,), album_directory=album, size_bytes=size)
        for index, (artist, album, size) in enumerate(
            [("A", "A/One", 100), ("A", "B/Two", 100), ("B", "B/Two", 50)]
        )
    ]
    first = select_balanced(songs, 250, 2, seed=0, max_per_artist=1)
    second = select_balanced(list(reversed(songs)), 250, 2, seed=0, max_per_artist=1)
    assert [song.relative_path for song in first] == [song.relative_path for song in second]
    assert {song.artist for song in first} == {("A",), ("B",)}
