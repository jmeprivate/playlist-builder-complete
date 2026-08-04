from __future__ import annotations

from .config import DEFAULT_YEAR_MARGIN
from .models import FilterSpec, Song
from .normalization import normalize_for_search


def complete_year_range(
    year_min: int | None,
    year_max: int | None,
    available_min: int | None,
    available_max: int | None,
    margin: int = DEFAULT_YEAR_MARGIN,
) -> tuple[int | None, int | None]:
    if year_min is not None and year_max is not None:
        if year_min > year_max:
            raise ValueError("el año mínimo no puede ser mayor que el máximo")
        return year_min, year_max
    year = year_min if year_min is not None else year_max
    if year is None:
        return None, None

    lower = year - margin
    upper = year + margin
    # Limit an overlapping interval to the catalog. If it is completely outside
    # (possible for a durable profile), preserve it so the UI shows a meaningful
    # empty range instead of an inverted one.
    if available_min is not None and upper >= available_min:
        lower = max(lower, available_min)
    if available_max is not None and lower <= available_max:
        upper = min(upper, available_max)
    return lower, upper


def song_matches(song: Song, spec: FilterSpec) -> bool:
    artists = {normalize_for_search(value) for value in song.artist}
    album_artists = {normalize_for_search(value) for value in song.album_artists}
    genres = {normalize_for_search(value) for value in song.genres}
    if (
        artists & spec.excluded_artists
        or album_artists & spec.excluded_album_artists
        or genres & spec.excluded_genres
    ):
        return False
    if spec.included_artists and not artists & spec.included_artists:
        return False
    if spec.included_album_artists and not album_artists & spec.included_album_artists:
        return False
    if spec.included_genres and not genres & spec.included_genres:
        return False
    if spec.year_min is not None or spec.year_max is not None:
        if song.year is None:
            return False
        if spec.year_min is not None and song.year < spec.year_min:
            return False
        if spec.year_max is not None and song.year > spec.year_max:
            return False
    return True


def filter_songs(songs: list[Song], spec: FilterSpec) -> list[Song]:
    return [song for song in songs if song_matches(song, spec)]
