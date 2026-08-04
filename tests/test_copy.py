from collections.abc import Callable
from pathlib import Path

import pytest

from playlist_builder import copier
from playlist_builder.copier import CopyTransactionError, copy_and_write_playlist
from playlist_builder.models import Song


def test_safe_component_only_replaces_characters_illegal_on_target_platform() -> None:
    value = "Tema: directo? * | \u00e7 🎵"
    assert copier._safe_component(value, platform="posix") == value
    assert copier._safe_component(value, platform="nt") == "Tema_ directo_ _ _ \u00e7 🎵"
    assert copier._safe_component("Final. ", platform="posix") == "Final. "
    assert copier._safe_component("Final. ", platform="nt") == "Final"


def test_copy_preserves_tree_and_handles_collision(
    tmp_path: Path, song_factory: Callable[..., Song]
) -> None:
    song = song_factory(name="same.mp3", album_directory="Artist/Album", size_bytes=5)
    destination = tmp_path / "export"
    conflict = destination / "Music" / song.relative_path
    conflict.parent.mkdir(parents=True)
    conflict.write_bytes(b"other content")
    result = copy_and_write_playlist(destination, "Viaje.m3u", [song], copy_structure="tree")
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


def test_surprise_copy_uses_playlist_name_unicode_and_final_collision_paths(
    tmp_path: Path, song_factory: Callable[..., Song]
) -> None:
    songs = [song_factory(name="one.mp3"), song_factory(name="two.flac")]
    destination = tmp_path / "export"
    conflict = destination / "Music" / "1 - Viaje agosto 🎵.mp3"
    conflict.parent.mkdir(parents=True)
    conflict.write_bytes(b"different")
    result = copy_and_write_playlist(
        destination, "Viaje agosto 🎵.m3u", songs, surprise=True, copy_structure="tree"
    )
    assert result.copied_paths[songs[0].path].name == "1 - Viaje agosto 🎵 (2).mp3"
    assert result.copied_paths[songs[1].path].name == "2 - Viaje agosto 🎵.flac"
    content = result.playlist_path.read_text(encoding="utf-8")
    assert "Music/1 - Viaje agosto 🎵 (2).mp3" in content
    assert "Music/2 - Viaje agosto 🎵.flac" in content
    assert "Title" not in "\n".join(path.name for path in result.copied_paths.values())


def test_normal_flat_copy_keeps_historical_name(
    tmp_path: Path, song_factory: Callable[..., Song]
) -> None:
    song = song_factory(name="original.mp3", artist=("Björk",), title="Jóga")
    result = copy_and_write_playlist(tmp_path / "out", "Lista.m3u", [song])
    assert result.copied_paths[song.path].name == "1 - Jóga (Björk).mp3"


def test_surprise_publication_failure_does_not_leak_song_path(
    tmp_path: Path,
    song_factory: Callable[..., Song],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    song = song_factory(name="secret-title.mp3")
    real_replace = copier.os.replace

    def fail_publishing(source: Path, target: Path) -> None:
        if target.suffix == ".mp3":
            raise OSError(f"cannot publish {target}")
        real_replace(source, target)

    monkeypatch.setattr(copier.os, "replace", fail_publishing)
    with pytest.raises(CopyTransactionError) as error:
        copy_and_write_playlist(tmp_path / "out", "Sorpresa.m3u", [song], surprise=True)
    assert "secret-title" not in str(error.value)
    assert not (tmp_path / "out" / "Sorpresa.m3u").exists()
