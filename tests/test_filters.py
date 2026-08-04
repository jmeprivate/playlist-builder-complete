from collections.abc import Callable

from playlist_builder.filters import song_matches
from playlist_builder.models import FilterSpec, Song


def test_artist_and_genre_inclusions_are_or_with_exclusions_first(
    song_factory: Callable[..., Song],
) -> None:
    song = song_factory(artist=("Björk", "Guest"), genres=("Art Pop", "Electronic"))
    assert song_matches(
        song,
        FilterSpec(
            included_artists=frozenset({"bjork", "other"}),
            included_genres=frozenset({"electronic"}),
        ),
    )
    assert not song_matches(
        song,
        FilterSpec(included_artists=frozenset({"bjork"}), excluded_artists=frozenset({"guest"})),
    )
    assert not song_matches(
        song,
        FilterSpec(
            included_genres=frozenset({"electronic"}), excluded_genres=frozenset({"art pop"})
        ),
    )


def test_missing_tags_only_fail_positive_filters(song_factory: Callable[..., Song]) -> None:
    song = song_factory(artist=(), genres=(), year=None)
    assert song_matches(song, FilterSpec())
    assert not song_matches(song, FilterSpec(included_artists=frozenset({"artist"})))
    assert not song_matches(song, FilterSpec(included_genres=frozenset({"rock"})))
    assert not song_matches(song, FilterSpec(year_min=1990, year_max=2000))


def test_year_interval_is_inclusive(song_factory: Callable[..., Song]) -> None:
    assert song_matches(song_factory(year=2000), FilterSpec(year_min=2000, year_max=2000))
    assert not song_matches(song_factory(year=1999), FilterSpec(year_min=2000, year_max=2010))


def test_album_artist_has_independent_inclusion_exclusion_and_exclusion_wins(
    song_factory: Callable[..., Song],
) -> None:
    compilation = song_factory(
        artist=("The Hoffpauir Family",), album_artists=("Various Artists", "Curator")
    )
    assert not song_matches(
        compilation, FilterSpec(included_artists=frozenset({"various artists"}))
    )
    assert song_matches(
        compilation, FilterSpec(included_album_artists=frozenset({"various artists", "other"}))
    )
    assert not song_matches(
        compilation,
        FilterSpec(
            included_album_artists=frozenset({"various artists"}),
            excluded_album_artists=frozenset({"curator"}),
        ),
    )


def test_missing_album_artist_only_fails_positive_album_artist_filter(
    song_factory: Callable[..., Song],
) -> None:
    song = song_factory(album_artists=())
    assert song_matches(song, FilterSpec())
    assert song_matches(song, FilterSpec(excluded_album_artists=frozenset({"various artists"})))
    assert not song_matches(song, FilterSpec(included_album_artists=frozenset({"various artists"})))
