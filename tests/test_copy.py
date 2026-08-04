from collections.abc import Callable
from pathlib import Path

import pytest

from playlist_builder import copier
from playlist_builder.copier import CopyTransactionError, copy_and_write_playlist
from playlist_builder.models import Song


def test_safe_component_only_replaces_characters_illegal_on_target_platform() -> None:
    value = "Tema: directo? * | ç 🎵"
    assert copier._safe_component(value, platform="posix") == value
    assert copier._safe_component(value, platform="nt") == "Tema_ directo_ _ _ ç 🎵"
    assert copier._safe_component("Final. ", platform="posix") == "Final. "
    assert copier._safe_component("Final. ", platform="nt") == "Final"


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


def test_keyboard_interrupt_rolls_back_files_and_new_directories(
    tmp_path: Path,
    song_factory: Callable[..., Song],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    songs = [song_factory(name="one.mp3"), song_factory(name="two.mp3")]
    real_replace = copier.os.replace
    calls = 0

    def interrupting_replace(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt
        real_replace(source, target)

    monkeypatch.setattr(copier.os, "replace", interrupting_replace)
    destination = tmp_path / "export"
    with pytest.raises(KeyboardInterrupt):
        copy_and_write_playlist(destination, "Interrupted.m3u", songs)
    assert not (destination / "Interrupted.m3u").exists()
    assert not list(destination.rglob("*.mp3"))
    assert not list(destination.glob(".playlist-copy-*"))


def test_surprise_copy_uses_playlist_name_unicode_and_final_collision_paths(
    tmp_path: Path, song_factory: Callable[..., Song]
) -> None:
    songs = [
        song_factory(name="one.mp3", title="Secret one"),
        song_factory(name="two.flac", title="Secret two"),
    ]
    destination = tmp_path / "export"
    conflict = destination / "Music" / "1 - Viaje agosto 🎵.mp3"
    conflict.parent.mkdir(parents=True)
    conflict.write_bytes(b"different")
    result = copy_and_write_playlist(destination, "Viaje agosto 🎵.m3u", songs, surprise=True)
    assert result.copied_paths[songs[0].path].name == "1 - Viaje agosto 🎵 (2).mp3"
    assert result.copied_paths[songs[1].path].name == "2 - Viaje agosto 🎵.flac"
    content = result.playlist_path.read_text(encoding="utf-8")
    assert "Music/1 - Viaje agosto 🎵 (2).mp3" in content
    assert "Music/2 - Viaje agosto 🎵.flac" in content
    assert "#EXTINF:123,1 - Viaje agosto 🎵.mp3" in content
    assert "#EXTINF:123,2 - Viaje agosto 🎵.flac" in content
    assert "Secret" not in content


def test_normal_flat_copy_keeps_historical_name(
    tmp_path: Path, song_factory: Callable[..., Song]
) -> None:
    song = song_factory(name="original.mp3", artist=("Björk",), title="Jóga")
    result = copy_and_write_playlist(tmp_path / "out", "Lista.m3u", [song])
    assert result.copied_paths[song.path].name == "1 - Jóga (Björk).mp3"


def test_flat_names_follow_final_order_and_metadata_fallbacks(
    tmp_path: Path, song_factory: Callable[..., Song]
) -> None:
    first = song_factory(name="disk-name.FLAC", artist=(), title=None)
    second = song_factory(name="02.mp3", artist=("Sigur Rós",), title="Svefn-g-englar")

    result = copy_and_write_playlist(tmp_path / "out", "Lista.m3u", [second, first])

    assert result.copied_paths[second.path].name == "1 - Svefn-g-englar (Sigur Rós).mp3"
    assert result.copied_paths[first.path].name == ("2 - disk-name (Artista desconocido).FLAC")
    entries = [
        line
        for line in result.playlist_path.read_text(encoding="utf-8").splitlines()
        if line and not line.startswith("#")
    ]
    assert entries == [
        "Music/1 - Svefn-g-englar (Sigur Rós).mp3",
        "Music/2 - disk-name (Artista desconocido).FLAC",
    ]


def test_flat_copy_reuses_identical_content_and_suffixes_different_content(
    tmp_path: Path, song_factory: Callable[..., Song]
) -> None:
    song = song_factory(artist=("Ana",), title="Tema")
    destination = tmp_path / "out"
    expected = destination / "Music" / "1 - Tema (Ana).mp3"
    expected.parent.mkdir(parents=True)
    expected.write_bytes(song.path.read_bytes())

    reused = copy_and_write_playlist(destination, "Una.m3u", [song])
    assert reused.copied_paths[song.path] == expected

    expected.write_bytes(b"contenido ajeno")
    collided = copy_and_write_playlist(destination, "Dos.m3u", [song])
    assert collided.copied_paths[song.path].name == "1 - Tema (Ana) (2).mp3"
    assert expected.read_bytes() == b"contenido ajeno"


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
