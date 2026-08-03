from collections.abc import Callable
from pathlib import Path

from playlist_builder.m3u import render_m3u, write_m3u_atomic
from playlist_builder.models import Song


def test_m3u_relative_paths_unicode_spaces_and_extinf(
    tmp_path: Path, song_factory: Callable[..., Song]
) -> None:
    song = song_factory(
        name="01 - Jóga.flac", artist=("Björk",), title="Jóga", duration_seconds=238.9
    )
    content = render_m3u([song], tmp_path)
    assert content.startswith("#EXTM3U\n#EXTINF:238,Björk - Jóga\n")
    assert "A/Artist/Album/01 - Jóga.flac\n" in content
    assert "\\" not in content


def test_m3u_copy_override_is_relative(tmp_path: Path, song_factory: Callable[..., Song]) -> None:
    song = song_factory()
    copied = tmp_path / "export" / "Music" / song.relative_path
    content = render_m3u([song], tmp_path / "export", {song.path: copied})
    assert f"Music/{song.relative_path.as_posix()}" in content


def test_atomic_writer_uses_utf8_lf(tmp_path: Path, song_factory: Callable[..., Song]) -> None:
    target = tmp_path / "Lista música.m3u"
    write_m3u_atomic(target, [song_factory(artist=("Ólafur",), title="Sól")])
    raw = target.read_bytes()
    assert b"\r\n" not in raw
    assert "Ólafur - Sól" in raw.decode("utf-8")
