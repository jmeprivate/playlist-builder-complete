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
    if year_min is not None:
        inferred = year_min + margin
        return year_min, min(inferred, available_max) if available_max is not None else inferred
    if year_max is not None:
        inferred = year_max - margin
        return max(inferred, available_min) if available_min is not None else inferred, year_max
    return None, None


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
