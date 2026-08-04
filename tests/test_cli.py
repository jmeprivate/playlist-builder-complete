from pathlib import Path

import pytest

from playlist_builder.cli import _run, build_parser, resolve_surprise
from playlist_builder.config import load_config


def _write_config(path: Path, *, surprise: bool = False) -> Path:
    path.write_text(
        "[playlist_builder]\n"
        "music_root = music\n"
        "default_year_margin = 5\n"
        "default_size_mb = 8000\n"
        "default_max_album = 2\n"
        "retry_error_after_days = 7\n"
        "cache_filename = .cache.json\n"
        "min_reasonable_year = 1000\n"
        "max_reasonable_year_offset = 1\n"
        "audio_extensions = .mp3, .flac\n"
        f"surprise_mode = {'true' if surprise else 'false'}\n"
        "preview_entries = 5\n"
        "copy_structure = flat\n",
        encoding="utf-8",
    )
    return path


def test_cli_accepts_decimal_size_and_rejects_invalid_values() -> None:
    args = build_parser().parse_args(["--size", "12.5", "--max-album", "3"])
    assert args.size == 12.5
    assert args.max_album == 3
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--size", "0"])
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--max-album", "1.5"])


def test_surprise_flags_are_explicit_and_mutually_exclusive() -> None:
    assert build_parser().parse_args([]).surprise is None
    assert build_parser().parse_args(["--surprise"]).surprise is True
    assert build_parser().parse_args(["--no-surprise"]).surprise is False
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--surprise", "--no-surprise"])


def test_surprise_cli_value_precedes_config() -> None:
    assert resolve_surprise(None, True) is True
    assert resolve_surprise(None, False) is False
    assert resolve_surprise(True, False) is True
    assert resolve_surprise(False, True) is False


def test_full_audit_is_rejected_before_scanning_in_surprise_mode(
    tmp_path: Path,
) -> None:
    settings = load_config(_write_config(tmp_path / "config.ini", surprise=True))
    with pytest.raises(ValueError, match="audit full"):
        _run(build_parser(settings).parse_args(["--audit", "full"]), settings)
