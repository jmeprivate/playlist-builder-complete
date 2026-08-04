from __future__ import annotations

from pathlib import Path

import pytest

from playlist_builder.config import ConfigError, load_config
from playlist_builder.filters import song_matches
from playlist_builder.models import FilterSpec


def write_config(path: Path) -> Path:
    path.write_text(
        """[playlist_builder]
music_root = music
default_year_margin = 5
default_size_mb = 8000
default_max_album = 2
retry_error_after_days = 7
default_max_artist = 0
cache_filename = .cache.json
min_reasonable_year = 1000
max_reasonable_year_offset = 1
surprise_mode = false
preview_entries = 5
""",
        encoding="utf-8",
    )
    return path


def add_aliases(path: Path, body: str) -> Path:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(f"\n[genre_aliases]\n{body}")
    return path


def test_each_alias_accents_and_equivalent_unicode_match(tmp_path: Path, song_factory) -> None:
    settings = load_config(
        add_aliases(
            write_config(tmp_path / "aliases.ini"),
            "Electrónica = electronic; electrónica; ELECTRONICA\n",
        )
    )
    spec = FilterSpec(included_genres=frozenset({"Electrónica"}))

    for genre in ("electronic", "electrónica", "ELECTRONICA", "Electrónica"):
        assert song_matches(song_factory(genres=(genre,)), spec, settings.genre_aliases)


def test_ungrouped_genre_is_unchanged_and_options_are_deduplicated(
    tmp_path: Path, song_factory
) -> None:
    settings = load_config(
        add_aliases(write_config(tmp_path / "aliases.ini"), "Jazz = fusion; jazz/fusion\n")
    )
    aliases = settings.genre_aliases

    assert aliases.display_options(["fusion", "JAZZ", "jazz/fusion", "Rock"]) == ("Jazz", "Rock")
    assert song_matches(
        song_factory(genres=("Rock",)),
        FilterSpec(included_genres=frozenset({"rock"})),
        aliases,
    )


def test_exclusion_keeps_precedence_when_both_filters_use_aliases(
    tmp_path: Path, song_factory
) -> None:
    aliases = load_config(
        add_aliases(write_config(tmp_path / "aliases.ini"), "Jazz = fusion; jazz/fusion\n")
    ).genre_aliases
    song = song_factory(genres=("fusion",))

    assert song_matches(song, FilterSpec(included_genres=frozenset({"Jazz"})), aliases)
    assert not song_matches(
        song,
        FilterSpec(
            included_genres=frozenset({"jazz/fusion"}),
            excluded_genres=frozenset({"Jazz"}),
        ),
        aliases,
    )


def test_playlist_builder_keys_remain_case_insensitive(tmp_path: Path) -> None:
    path = write_config(tmp_path / "mixed-case.ini")
    text = path.read_text(encoding="utf-8").replace("music_root", "Music_Root")
    path.write_text(text, encoding="utf-8")

    settings = load_config(path)

    assert settings.music_root == (tmp_path / "music").resolve()


@pytest.mark.parametrize(
    "body, message",
    [
        ("Jazz = fusion;\n", "vacíos"),
        ("Jazz = \n", "vacíos"),
        (" = fusion\n", "clave canónica"),
        ("Jazz = fusion\nRock = FÚSION\n", "ambiguo"),
        ("Jazz = rock\nROCK = metal\n", "ambiguo"),
    ],
)
def test_malformed_or_ambiguous_aliases_are_rejected(
    tmp_path: Path, body: str, message: str
) -> None:
    path = add_aliases(write_config(tmp_path / "bad.ini"), body)
    with pytest.raises(ConfigError, match=message):
        load_config(path)
