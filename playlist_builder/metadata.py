from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from mutagen import File as MutagenFile

from .config import MAX_REASONABLE_YEAR_OFFSET, MIN_REASONABLE_YEAR
from .models import Song
from .normalization import deduplicate_display_values

LOGGER = logging.getLogger(__name__)
_YEAR_RE = re.compile(r"(?<!\d)(\d{4})(?!\d)")
_MULTI_VALUE_RE = re.compile(r"[;\x00]+")
_GENRE_MULTI_VALUE_RE = re.compile(r"[,;\x00]+")


def parse_year(value: object, current_year: int | None = None) -> int | None:
    ceiling = (current_year or datetime.now().year) + MAX_REASONABLE_YEAR_OFFSET
    values: Iterable[object] = value if isinstance(value, (list, tuple)) else (value,)
    for item in values:
        match = _YEAR_RE.search(str(item))
        if match:
            year = int(match.group(1))
            if MIN_REASONABLE_YEAR <= year <= ceiling:
                return year
    return None


def _tag_values(
    tags: Mapping[str, Any] | None,
    names: tuple[str, ...],
    separator: re.Pattern[str] = _MULTI_VALUE_RE,
) -> list[str]:
    if not tags:
        return []
    lowered = {str(key).casefold(): value for key, value in tags.items()}
    result: list[str] = []
    for name in names:
        raw = lowered.get(name.casefold())
        if raw is None:
            continue
        items = raw if isinstance(raw, (list, tuple)) else (raw,)
        for item in items:
            result.extend(separator.split(str(item)))
    return list(deduplicate_display_values(result))


def read_song(path: Path, root: Path) -> Song:
    audio = MutagenFile(path, easy=True)
    if audio is None:
        raise ValueError("mutagen no reconoce el formato o no pudo abrirlo")
    tags: Mapping[str, Any] | None = audio.tags
    artists = _tag_values(tags, ("artist",))
    if not artists:
        # Algunos WMA/ASF exponen Artist bajo Author. AlbumArtist no es un sustituto:
        # en recopilatorios suele ser "Various Artists" y alteraría los filtros.
        artists = _tag_values(tags, ("author",))
    album_artists = _tag_values(tags, ("albumartist",))
    genres = _tag_values(tags, ("genre",), _GENRE_MULTI_VALUE_RE)
    years = _tag_values(tags, ("date", "year", "originaldate"))
    albums = _tag_values(tags, ("album",))
    titles = _tag_values(tags, ("title",))
    relative = path.relative_to(root)
    album_directory = relative.parent
    duration_raw = getattr(getattr(audio, "info", None), "length", None)
    duration = float(duration_raw) if isinstance(duration_raw, (float, int)) else None
    return Song(
        path=path,
        relative_path=relative,
        artist=tuple(artists),
        album_artists=tuple(album_artists),
        genres=tuple(genres),
        year=parse_year(years),
        album=albums[0] if albums else path.parent.name,
        album_directory=album_directory,
        size_bytes=path.stat().st_size,
        title=titles[0] if titles else None,
        duration_seconds=duration,
    )
