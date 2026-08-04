from __future__ import annotations

import builtins
import logging
from pathlib import Path

from playlist_builder.cli import build_parser
from playlist_builder.deduplication import deduplicate_songs
from playlist_builder.selector import select_balanced


def test_identical_content_keeps_stable_relative_path(song_factory) -> None:
    later = song_factory(name="z.mp3", size_bytes=4)
    earlier = song_factory(name="a.mp3", size_bytes=4)
    later.path.write_bytes(b"same")
    earlier.path.write_bytes(b"same")

    assert deduplicate_songs([later, earlier]) == [earlier]


def test_different_sizes_are_never_opened(song_factory, monkeypatch) -> None:
    songs = [song_factory(size_bytes=3), song_factory(size_bytes=4)]

    def unexpected_open(*args, **kwargs):
        raise AssertionError("no se debe calcular ningún hash")

    monkeypatch.setattr(Path, "open", unexpected_open)
    assert deduplicate_songs(songs) == songs


def test_same_size_with_different_content_is_retained(song_factory) -> None:
    songs = [song_factory(size_bytes=4), song_factory(size_bytes=4)]

    assert deduplicate_songs(songs) == songs


def test_deduplication_is_deterministic_and_preserves_seed(song_factory) -> None:
    duplicate = song_factory(name="z.mp3", size_bytes=4)
    representative = song_factory(name="a.mp3", size_bytes=4)
    other = song_factory(name="other.mp3", album_directory="B", size_bytes=4)
    duplicate.path.write_bytes(b"same")
    representative.path.write_bytes(b"same")
    other.path.write_bytes(b"else")

    first = deduplicate_songs([duplicate, other, representative])
    second = deduplicate_songs([representative, duplicate, other])
    assert {song.relative_path for song in first} == {song.relative_path for song in second}
    assert select_balanced(first, 100, 2, seed=19) == select_balanced(first, 100, 2, seed=19)


def test_hash_read_failure_is_logged_and_file_is_retained(
    song_factory, monkeypatch, caplog
) -> None:
    failed = song_factory(name="failed.mp3", size_bytes=4)
    readable = song_factory(name="readable.mp3", size_bytes=4)
    readable.path.write_bytes(b"data")
    original_open = builtins.open

    def selective_open(self: Path, *args, **kwargs):
        if self == failed.path:
            raise PermissionError("denegado")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", selective_open)
    with caplog.at_level(logging.WARNING):
        assert deduplicate_songs([failed, readable]) == [failed, readable]
    assert "No se pudo calcular SHA-256" in caplog.text


def test_deduplication_is_disabled_by_default() -> None:
    assert build_parser().parse_args([]).deduplicate is False
    assert build_parser().parse_args(["--deduplicate"]).deduplicate is True
