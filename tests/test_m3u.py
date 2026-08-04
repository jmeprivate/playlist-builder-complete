import unicodedata
from collections.abc import Callable
from pathlib import Path

import pytest

from playlist_builder.m3u import match_playlist_songs, read_m3u, render_m3u, write_m3u_atomic
from playlist_builder.models import Song
from playlist_builder.selector import select_balanced


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
    assert str(song.path) not in content


def test_extinf_controls_are_flattened_without_removing_format_characters(
    tmp_path: Path, song_factory: Callable[..., Song]
) -> None:
    song = song_factory(
        artist=("Artist\nInjected",),
        title="Emoji 👩‍💻\r\nSecond line",
    )
    content = render_m3u([song], tmp_path)
    assert "#EXTINF:123,Artist Injected - Emoji 👩‍💻 Second line\n" in content
    assert len(content.splitlines()) == 3


def test_atomic_writer_uses_utf8_lf(tmp_path: Path, song_factory: Callable[..., Song]) -> None:
    target = tmp_path / "Lista música.m3u"
    write_m3u_atomic(target, [song_factory(artist=("Ólafur",), title="Sól")])
    raw = target.read_bytes()
    assert b"\r\n" not in raw
    assert "Ólafur - Sól" in raw.decode("utf-8")


def test_reader_handles_simple_extended_bom_and_relative_absolute_paths(
    tmp_path: Path, song_factory: Callable[..., Song]
) -> None:
    relative_song = song_factory(name="Canción con espacios.mp3")
    absolute_song = song_factory(name="absoluta.flac")
    playlist = tmp_path / "mezcla.m3u8"
    relative = relative_song.path.relative_to(tmp_path).as_posix()
    playlist.write_text(
        f"\ufeff#EXTM3U\n#EXTINF:123,Una pista\n{relative}\n\n{absolute_song.path}\n",
        encoding="utf-8",
    )

    assert read_m3u(playlist) == [relative, str(absolute_song.path)]
    matched, report = match_playlist_songs([relative_song, absolute_song], tmp_path, [playlist])
    assert matched == {relative_song.path, absolute_song.path}
    assert (report.entries, report.matched, report.ignored) == (2, 2, 0)


def test_matching_normalizes_unicode_and_reports_ignored_entries(
    tmp_path: Path, song_factory: Callable[..., Song]
) -> None:
    song = song_factory(name="Café del Mar.mp3")
    unscanned = tmp_path / "other.mp3"
    unscanned.write_bytes(b"audio")
    outside = tmp_path.parent / "outside.mp3"
    playlist = tmp_path / "input.m3u"
    nfd = unicodedata.normalize("NFD", song.path.relative_to(tmp_path).as_posix())
    playlist.write_text(
        f"{nfd}\nmissing.mp3\n{unscanned}\n{outside}\nfile:///tmp/song.mp3\nhttps://x/list.m3u\n",
        encoding="utf-8",
    )

    matched, report = match_playlist_songs([song], tmp_path, [playlist])
    assert matched == {song.path}
    assert report.matched == 1
    assert report.missing == 1
    assert report.not_scanned == 1
    assert report.outside_root == 1
    assert report.unsupported == 2
    assert report.ignored == 5


def test_matching_does_not_accept_wrong_case_on_case_sensitive_filesystem(
    tmp_path: Path, song_factory: Callable[..., Song]
) -> None:
    song = song_factory(name="Song.mp3")
    wrong_case = song.path.with_name("song.mp3")
    if wrong_case.exists():
        pytest.skip("el sistema de archivos no distingue mayúsculas")
    playlist = tmp_path / "wrong-case.m3u"
    playlist.write_text(f"{wrong_case}\n", encoding="utf-8")

    matched, report = match_playlist_songs([song], tmp_path, [playlist])

    assert matched == set()
    assert report.matched == 0
    assert report.missing == 1


def test_multiple_playlists_form_a_union_and_exclusions_can_be_applied_afterward(
    tmp_path: Path, song_factory: Callable[..., Song]
) -> None:
    first, second, third = song_factory(), song_factory(), song_factory()
    one = tmp_path / "one.m3u"
    two = tmp_path / "two.m3u8"
    excluded = tmp_path / "excluded.m3u"
    one.write_text(f"{first.path}\n{second.path}\n", encoding="utf-8")
    two.write_text(f"{third.path}\n", encoding="utf-8")
    excluded.write_text(f"{second.path}\n", encoding="utf-8")

    included, _ = match_playlist_songs([first, second, third], tmp_path, [one, two])
    removed, _ = match_playlist_songs([first, second, third], tmp_path, [excluded])
    assert included - removed == {first.path, third.path}


def test_reader_rejects_formats_other_than_local_m3u(tmp_path: Path) -> None:
    playlist = tmp_path / "playlist.pls"
    playlist.write_text("File1=song.mp3\n", encoding="utf-8")
    with pytest.raises(ValueError, match="M3U/M3U8"):
        read_m3u(playlist)


def test_playlist_candidates_preserve_balancing_and_seed(
    tmp_path: Path, song_factory: Callable[..., Song]
) -> None:
    songs = [song_factory(album_directory=f"Artist/Album-{index // 2}") for index in range(8)]
    playlist = tmp_path / "all.m3u"
    playlist.write_text("\n".join(str(song.path) for song in reversed(songs)), encoding="utf-8")
    included, _ = match_playlist_songs(songs, tmp_path, [playlist])
    candidates = [song for song in songs if song.path in included]

    first = select_balanced(candidates, 500, 1, seed=73)
    second = select_balanced(list(reversed(candidates)), 500, 1, seed=73)
    assert [song.path for song in first] == [song.path for song in second]
    assert len({song.album_directory for song in first}) == len(first)
