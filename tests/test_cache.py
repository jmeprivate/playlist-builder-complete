import json
from collections.abc import Callable
from pathlib import Path

from mutagen import MutagenError

from playlist_builder.config import CACHE_FILENAME
from playlist_builder.models import Song
from playlist_builder.scanner import scan_library


def test_cache_valid_stale_removed_corrupt_and_modified(
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
    assert "one.mp3" not in cache_path.read_text(encoding="utf-8")
    cache_path.write_text("{broken", encoding="utf-8")
    audio.write_bytes(b"new")
    scan_library(root, metadata_reader=reader)
    assert len(calls) == 4


def test_scan_excludes_copy_tree_and_continues_after_reader_errors(tmp_path: Path) -> None:
    root = tmp_path / "library"
    original = root / "Artist" / "Album" / "original.mp3"
    second = root / "Artist" / "Album" / "second.mp3"
    copied = root / "Export" / "Music" / "Artist" / "Album" / "copy.mp3"
    stale = root / "Export" / ".playlist-copy-old" / "stale.mp3"
    for path in (original, second, copied, stale):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"audio")

    def broken_reader(path: Path, music_root: Path) -> Song:
        if path.name == "original.mp3":
            raise MutagenError("cabecera corrupta")
        raise RuntimeError("error inesperado aislado")

    songs, report = scan_library(
        root,
        excluded_root=root / "Export" / "Music",
        metadata_reader=broken_reader,
    )
    assert songs == []
    assert report.total_audio_files == 2
    assert report.unreadable_count == 2
    assert {issue.relative_path for issue in report.issues} == {
        original.relative_to(root),
        second.relative_to(root),
    }
