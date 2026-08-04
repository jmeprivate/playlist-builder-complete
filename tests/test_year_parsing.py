import pytest

from playlist_builder.filters import complete_year_range
from playlist_builder.metadata import parse_year


@pytest.mark.parametrize("raw", ["1986", "1986-04-01", "published 1986/04/01", ["1986"]])
def test_parse_year_formats(raw: object) -> None:
    assert parse_year(raw, current_year=2026) == 1986


def test_parse_year_rejects_unreasonable_values() -> None:
    assert parse_year("0999", current_year=2026) is None
    assert parse_year("2099", current_year=2026) is None


def test_complete_year_range_margin_and_bounds() -> None:
    assert complete_year_range(2000, None, 1918, 2003, 5) == (1995, 2003)
    assert complete_year_range(None, 2000, 1918, 2003, 5) == (1995, 2003)
    assert complete_year_range(None, 1920, 1918, 2026, 5) == (1918, 1925)
    assert complete_year_range(2024, None, 1918, 2026, 5) == (2019, 2026)
    assert complete_year_range(None, None, 1918, 2026) == (None, None)


def test_single_year_outside_catalog_keeps_a_non_inverted_profile_range() -> None:
    assert complete_year_range(1900, None, 1918, 2026, 5) == (1895, 1905)
    assert complete_year_range(None, 2040, 1918, 2026, 5) == (2035, 2045)


def test_complete_year_range_rejects_inverse() -> None:
    with pytest.raises(ValueError):
        complete_year_range(2001, 2000, 1900, 2026)
