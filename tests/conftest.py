from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from playlist_builder.models import Song


@pytest.fixture
def song_factory(tmp_path: Path) -> Callable[..., Song]:
    counter = 0

    def make_song(
        *,
        name: str | None = None,
        artist: tuple[str, ...] = ("Artist",),
        genres: tuple[str, ...] = ("Rock",),
        year: int | None = 2000,
        album_directory: str = "A/Artist/Album",
        size_bytes: int = 100,
        title: str | None = "Title",
        duration_seconds: float | None = 123.8,
        create: bool = True,
    ) -> Song:
        nonlocal counter
        counter += 1
        filename = name or f"track-{counter}.mp3"
        relative = Path(album_directory) / filename
        path = tmp_path / relative
        if create:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(bytes([counter % 256]) * size_bytes)
        return Song(
            path=path,
            relative_path=relative,
            artist=artist,
            genres=genres,
            year=year,
            album=Path(album_directory).name,
            album_directory=Path(album_directory),
            size_bytes=size_bytes,
            title=title,
            duration_seconds=duration_seconds,
        )

    return make_song
