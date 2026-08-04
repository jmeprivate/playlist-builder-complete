import pytest

from playlist_builder.filters import complete_year_range
from playlist_builder.metadata import parse_year


@pytest.mark.parametrize("raw", ["1986", "1986-04-01", "published 1986/04/01", ["1986"]])
def test_parse_year_formats(raw: object) -> None:
    assert parse_year(raw) == 1986


def test_parse_year_accepts_any_four_digit_value() -> None:
    assert parse_year("0999") == 999
    assert parse_year("2099") == 2099


def test_single_year_uses_symmetric_offset_without_catalog_clipping() -> None:
    assert complete_year_range(1000, None, 5) == (995, 1005)
    assert complete_year_range(None, 1000, 5) == (995, 1005)
    assert complete_year_range(-20, None, 5) == (-25, -15)
    assert complete_year_range(None, None, 5) == (None, None)


def test_explicit_year_range_is_preserved() -> None:
    assert complete_year_range(1000, 2000, 5) == (1000, 2000)


def test_complete_year_range_rejects_inverse_or_negative_offset() -> None:
    with pytest.raises(ValueError):
        complete_year_range(2001, 2000, 5)
    with pytest.raises(ValueError):
        complete_year_range(2000, None, -1)
