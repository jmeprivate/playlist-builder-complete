from __future__ import annotations

from .config import DEFAULT_YEAR_MARGIN, EMPTY_GENRE_ALIASES, GenreAliases
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


def song_matches(
    song: Song,
    spec: FilterSpec,
    genre_aliases: GenreAliases = EMPTY_GENRE_ALIASES,
    *,
    included_genres: set[str] | None = None,
    excluded_genres: set[str] | None = None,
) -> bool:
    artists = {normalize_for_search(value) for value in song.artist}
    album_artists = {normalize_for_search(value) for value in song.album_artists}
    genres = {genre_aliases.resolve(value) for value in song.genres}
    if included_genres is None:
        included_genres = {genre_aliases.resolve(value) for value in spec.included_genres}
    if excluded_genres is None:
        excluded_genres = {genre_aliases.resolve(value) for value in spec.excluded_genres}
    if (
        artists & spec.excluded_artists
        or album_artists & spec.excluded_album_artists
        or genres & excluded_genres
    ):
        return False
    if spec.included_artists and not artists & spec.included_artists:
        return False
    if spec.included_album_artists and not album_artists & spec.included_album_artists:
        return False
    if included_genres and not genres & included_genres:
        return False
    if spec.year_min is not None or spec.year_max is not None:
        if song.year is None:
            return False
        if spec.year_min is not None and song.year < spec.year_min:
            return False
        if spec.year_max is not None and song.year > spec.year_max:
            return False
    return True


def filter_songs(
    songs: list[Song], spec: FilterSpec, genre_aliases: GenreAliases = EMPTY_GENRE_ALIASES
) -> list[Song]:
    included_genres = {genre_aliases.resolve(value) for value in spec.included_genres}
    excluded_genres = {genre_aliases.resolve(value) for value in spec.excluded_genres}
    return [
        song
        for song in songs
        if song_matches(
            song,
            spec,
            genre_aliases,
            included_genres=included_genres,
            excluded_genres=excluded_genres,
        )
    ]
