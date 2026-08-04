import json
from collections.abc import Callable
from pathlib import Path

from mutagen import MutagenError

from playlist_builder.cache import CacheEntry, load_cache, write_cache
from playlist_builder.config import CACHE_FILENAME
from playlist_builder.models import Song
from playlist_builder.scanner import scan_library


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
    audio.write_bytes(b"changed-size")
    scan_library(root, metadata_reader=reader)
    assert len(calls) == 2
    audio.unlink()
    scan_library(root, metadata_reader=reader)
    assert "one.mp3" not in (root / CACHE_FILENAME).read_text(encoding="utf-8")
    (root / CACHE_FILENAME).write_text("{broken", encoding="utf-8")
    audio.write_bytes(b"new")
    scan_library(root, metadata_reader=reader)
    assert len(calls) == 3


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


def test_cache_loads_old_song_without_album_artists_and_round_trips_new_song(
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
    loaded_old = load_cache(cache_path, tmp_path)
    assert loaded_old[song.relative_path.as_posix()].song is not None
    assert loaded_old[song.relative_path.as_posix()].song.album_artists == ()  # type: ignore[union-attr]

    write_cache(cache_path, {"track": CacheEntry(song.size_bytes, 1, song, None)})
    loaded_new = load_cache(cache_path, tmp_path)
    assert loaded_new["track"].song is not None
    assert loaded_new["track"].song.album_artists == ("Various Artists",)  # type: ignore[union-attr]
