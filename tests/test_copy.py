from collections.abc import Callable
from pathlib import Path

import pytest

from playlist_builder import copier
from playlist_builder.copier import CopyTransactionError, copy_and_write_playlist
from playlist_builder.models import Song


def test_copy_preserves_tree_and_handles_collision(
    tmp_path: Path, song_factory: Callable[..., Song]
) -> None:
    song = song_factory(name="same.mp3", album_directory="Artist/Album", size_bytes=5)
    destination = tmp_path / "export"
    conflict = destination / "Music" / song.relative_path
    conflict.parent.mkdir(parents=True)
    conflict.write_bytes(b"other content")
    result = copy_and_write_playlist(destination, "Viaje.m3u", [song])
    copied = result.copied_paths[song.path]
    assert copied.name == "same (2).mp3"
    assert copied.read_bytes() == song.path.read_bytes()
    assert "Music/Artist/Album/same (2).mp3" in result.playlist_path.read_text(encoding="utf-8")


def test_partial_copy_failure_publishes_nothing(
    tmp_path: Path, song_factory: Callable[..., Song], monkeypatch: pytest.MonkeyPatch
) -> None:
    songs = [song_factory(), song_factory()]
    real_copy2 = copier.shutil.copy2
    calls = 0

    def failing_copy(source: Path, target: Path) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated")
        return real_copy2(source, target)

    monkeypatch.setattr(copier.shutil, "copy2", failing_copy)
    destination = tmp_path / "export"
    with pytest.raises(CopyTransactionError):
        copy_and_write_playlist(destination, "Failed.m3u", songs)
    assert not (destination / "Failed.m3u").exists()
    assert (
        not list((destination / "Music").rglob("*")) if (destination / "Music").exists() else True
    )
