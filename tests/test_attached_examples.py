from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from playlist_builder import metadata
from playlist_builder.m3u import write_m3u_atomic
from playlist_builder.models import Song


class FakeAudio:
    def __init__(self, tags: dict[str, list[str]], duration: float) -> None:
        self.tags = tags
        self.info = SimpleNamespace(length=duration)


def test_attached_mp3_keeps_track_artist_separate_from_album_artist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "Various Artists" / "Album" / "02 Clefs De La Prison.mp3"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"example")
    audio = FakeAudio(
        {
            "album": ["Cajun & Creole Music 1934-1937"],
            "title": ["Clefs De La Prison"],
            "artist": ["The Hoffpauir Family"],
            "albumartist": ["Various Artists"],
            "genre": ["Folk, Blues, Country Blues, Cajun, USA"],
            "date": ["1999"],
        },
        106.97785,
    )
    monkeypatch.setattr(metadata, "MutagenFile", lambda *_args, **_kwargs: audio)

    song = metadata.read_song(path, tmp_path)

    assert song.artist == ("The Hoffpauir Family",)
    assert song.album_artists == ("Various Artists",)
    assert "Various Artists" not in song.artist
    assert song.genres == ("Folk", "Blues", "Country Blues", "Cajun", "USA")
    assert song.year == 1999
    assert song.album == "Cajun & Creole Music 1934-1937"
    assert song.title == "Clefs De La Prison"
    assert song.duration_seconds == pytest.approx(106.97785)


def test_attached_flac_splits_genres_and_reads_all_primary_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "Gateway" / "[1995] Homecoming" / "01 Homecoming.flac"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"example")
    audio = FakeAudio(
        {
            "date": ["1995"],
            "album": ["Homecoming"],
            "albumartist": ["Gateway"],
            "genre": ["Jazz, Contemporary Jazz"],
            "artist": ["Gateway"],
            "title": ["Homecoming"],
        },
        757.3733333333333,
    )
    monkeypatch.setattr(metadata, "MutagenFile", lambda *_args, **_kwargs: audio)

    song = metadata.read_song(path, tmp_path)

    assert song.artist == ("Gateway",)
    assert song.album_artists == ("Gateway",)
    assert song.genres == ("Jazz", "Contemporary Jazz")
    assert song.year == 1995
    assert song.album == "Homecoming"
    assert song.album_directory == Path("Gateway/[1995] Homecoming")
    assert song.title == "Homecoming"
    assert song.duration_seconds == pytest.approx(757.3733333333333)


def test_sample_m3u_unicode_decomposition_spaces_and_lf_are_preserved(
    tmp_path: Path, song_factory: Callable[..., Song]
) -> None:
    decomposed_spanish = "PopEspan\u0303ol"
    song = song_factory(
        name="(Amaral) Co\u0301mo Hablar.mp3",
        album_directory=f"Various Artists/[2026] {decomposed_spanish}",
        artist=("Amaral",),
        title="Co\u0301mo Hablar",
    )
    playlist = tmp_path / f"{decomposed_spanish}.m3u"

    write_m3u_atomic(playlist, [song])

    raw = playlist.read_bytes()
    decoded = raw.decode("utf-8")
    assert b"\r\n" not in raw
    assert playlist.name == "PopEspan\u0303ol.m3u"
    assert "#EXTINF:123,Amaral - Co\u0301mo Hablar" in decoded
    assert "Various Artists/[2026] PopEspan\u0303ol/(Amaral) Co\u0301mo Hablar.mp3" in decoded
