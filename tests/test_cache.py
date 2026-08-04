import json
from collections.abc import Callable
from pathlib import Path

import pytest
from mutagen import MutagenError

from playlist_builder import cache, scanner
from playlist_builder.cache import CacheEntry, load_cache, load_catalog_cache, write_cache
from playlist_builder.config import CACHE_FILENAME
from playlist_builder.models import Song
from playlist_builder.scanner import scan_library


def test_cache_interrupt_removes_temporary_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "cache.json"
    monkeypatch.setattr(cache.os, "replace", lambda *args: (_ for _ in ()).throw(KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        write_cache(target, {})
    assert not list(tmp_path.glob(".cache.json.*"))


def test_directory_walk_errors_are_reported_but_not_counted_as_audio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "library"
    blocked = root / "blocked"
    root.mkdir()

    def broken_walk(path: Path, *, topdown: bool, onerror):  # type: ignore[no-untyped-def]
        onerror(PermissionError(13, "denegado", str(blocked)))
        return iter(())

    monkeypatch.setattr(scanner.os, "walk", broken_walk)
    songs, report = scan_library(root)
    assert songs == []
    assert report.total_audio_files == 0
    assert report.unreadable_count == 0
    assert report.issues[0].is_directory is True


def test_cache_valid_stale_removed_and_corrupt(
    tmp_path: Path, song_factory: Callable[..., Song]
) -> None:
    root = tmp_path / "library"
    audio = root / "Artist" / "Album" / "one.mp3"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"one")
    calls: list[Path] = []

    def reader(path: Path, music_root: Path) -> Song:
        calls.append(path)
        relative = path.relative_to(music_root)
        return Song(
            path,
            relative,
            ("Artist",),
            ("Rock",),
            2000,
            "Album",
            relative.parent,
            path.stat().st_size,
        )

    songs, _ = scan_library(root, metadata_reader=reader)
    assert len(songs) == 1 and len(calls) == 1
    scan_library(root, metadata_reader=reader)
    assert len(calls) == 1
    cache_path = root / CACHE_FILENAME
    cache = json.loads(cache_path.read_text(encoding="utf-8"))
    cache["files"]["Artist/Album/one.mp3"]["size"] += 1
    cache_path.write_text(json.dumps(cache), encoding="utf-8")
    scan_library(root, metadata_reader=reader)
    assert len(calls) == 2
    audio.write_bytes(b"changed-size")
    scan_library(root, metadata_reader=reader)
    assert len(calls) == 3
    audio.unlink()
    scan_library(root, metadata_reader=reader)
    assert "one.mp3" not in (root / CACHE_FILENAME).read_text(encoding="utf-8")
    (root / CACHE_FILENAME).write_text("{broken", encoding="utf-8")
    audio.write_bytes(b"new")
    scan_library(root, metadata_reader=reader)
    assert len(calls) == 4


def test_scan_isolates_unexpected_reader_errors(tmp_path: Path) -> None:
    root = tmp_path / "library"
    for name in ("one.mp3", "two.mp3"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"audio")

    def broken_reader(path: Path, music_root: Path) -> Song:
        raise RuntimeError(f"fallo inesperado: {path.name}")

    songs, report = scan_library(root, metadata_reader=broken_reader)
    assert songs == []
    assert report.total_audio_files == 2
    assert report.unreadable_count == 2


def test_scan_excludes_copy_tree_and_continues_after_mutagen_error(tmp_path: Path) -> None:
    root = tmp_path / "library"
    original = root / "Artist" / "Album" / "original.mp3"
    copied = root / "Export" / "Music" / "Artist" / "Album" / "copy.mp3"
    stale = root / "Export" / ".playlist-copy-old" / "stale.mp3"
    for path in (original, copied, stale):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"audio")

    def broken_reader(path: Path, music_root: Path) -> Song:
        raise MutagenError("cabecera corrupta")

    songs, report = scan_library(
        root,
        excluded_root=root / "Export" / "Music",
        metadata_reader=broken_reader,
    )
    assert songs == []
    assert report.total_audio_files == 1
    assert report.unreadable_count == 1
    assert report.issues[0].relative_path == original.relative_to(root)


def test_scan_excludes_marked_copy_destination_on_later_runs(tmp_path: Path) -> None:
    root = tmp_path / "library"
    original = root / "Artist" / "original.mp3"
    copied_music = root / "Export" / "Music"
    copied = copied_music / "1 - Copia (Artist).mp3"
    for path in (original, copied):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"audio")
    (copied_music / ".playlist-builder-copy-root").write_text("marker", encoding="utf-8")

    seen: list[Path] = []

    def reader(path: Path, music_root: Path) -> Song:
        seen.append(path)
        return Song(
            path=path,
            relative_path=path.relative_to(music_root),
            artist=("Artist",),
            genres=(),
            year=None,
            album="",
            album_directory=Path("Artist"),
            size_bytes=path.stat().st_size,
        )

    songs, report = scan_library(root, metadata_reader=reader)
    assert [song.path for song in songs] == [original]
    assert seen == [original]
    assert report.total_audio_files == 1


def test_cache_invalidates_v1_and_deserializes_legacy_song_without_album_artists(
    tmp_path: Path, song_factory: Callable[..., Song]
) -> None:
    cache_path = tmp_path / "cache.json"
    song = song_factory(album_artists=("Various Artists",))
    old_song = song.to_cache_dict()
    old_song.pop("album_artists")
    cache_path.write_text(
        json.dumps(
            {
                "version": 1,
                "files": {
                    song.relative_path.as_posix(): {
                        "size": song.size_bytes,
                        "mtime_ns": 1,
                        "song": old_song,
                        "error": None,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    assert load_cache(cache_path, tmp_path) == {}
    assert Song.from_cache_dict(tmp_path, old_song).album_artists == ()

    write_cache(cache_path, {"track": CacheEntry(song.size_bytes, 1, song, None)})
    loaded_new = load_cache(cache_path, tmp_path)
    cached_song = loaded_new["track"].song
    assert cached_song is not None
    assert cached_song.album_artists == ("Various Artists",)


def test_interrupted_scan_is_incomplete_and_does_not_prune(tmp_path: Path) -> None:
    root = tmp_path / "library"
    audio = root / "one.mp3"
    root.mkdir()
    audio.write_bytes(b"x")

    def interrupt(_path: Path, _root: Path) -> Song:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        scan_library(root, metadata_reader=interrupt)
    cache = load_catalog_cache(root / CACHE_FILENAME, root)
    assert not cache.health.completed
    assert cache.health.scan_started_at
    assert cache.health.scan_finished_at is None


def test_cached_error_retries_by_age_rescan_and_change(tmp_path: Path) -> None:
    root = tmp_path / "library"
    audio = root / "one.mp3"
    root.mkdir()
    audio.write_bytes(b"x")
    calls = 0

    def broken(_path: Path, _root: Path) -> Song:
        nonlocal calls
        calls += 1
        raise ValueError("bad")

    scan_library(root, metadata_reader=broken, retry_error_after_days=10)
    scan_library(root, metadata_reader=broken, retry_error_after_days=10)
    assert calls == 1
    scan_library(root, metadata_reader=broken, retry_error_after_days=0)
    scan_library(root, metadata_reader=broken, rescan=True, retry_error_after_days=10)
    audio.write_bytes(b"changed")
    scan_library(root, metadata_reader=broken, retry_error_after_days=10)
    assert calls == 4


def test_residual_temporary_and_write_failure_do_not_lose_memory_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "library"
    audio = root / "one.mp3"
    root.mkdir()
    audio.write_bytes(b"x")
    (root / f".{CACHE_FILENAME}.orphan").write_text("{broken", encoding="utf-8")
    song = Song(audio, Path("one.mp3"), ("Artist",), ("Rock",), 2000, "", Path("."), 1)
    monkeypatch.setattr("playlist_builder.scanner.write_catalog_cache", lambda *_args: False)
    songs, _ = scan_library(root, metadata_reader=lambda *_args: song)
    assert songs == [song]
