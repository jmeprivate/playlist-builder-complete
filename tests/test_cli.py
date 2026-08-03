import pytest

from playlist_builder.cli import build_parser


def test_cli_accepts_decimal_size_and_rejects_invalid_values() -> None:
    args = build_parser().parse_args(["--size", "12.5", "--max-album", "3"])
    assert args.size == 12.5
    assert args.max_album == 3
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--size", "0"])
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--max-album", "1.5"])
