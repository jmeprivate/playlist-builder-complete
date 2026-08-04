from pathlib import Path

import pytest

from playlist_builder import cli
from playlist_builder.cli import _run, build_parser, resolve_surprise
from playlist_builder.config import load_config
from playlist_builder.profiles import FilterProfile, save_profiles_atomic


def _write_config(path: Path, *, surprise: bool = False) -> Path:
    path.write_text(
        "[playlist_builder]\n"
        "music_root = music\n"
        "default_size_mb = 8000\n"
        "default_max_album = 2\n"
        "default_max_artist = 0\n"
        "cache_filename = .cache.json\n"
        "max_reasonable_year_offset = 5\n"
        f"surprise_mode = {'true' if surprise else 'false'}\n",
        encoding="utf-8",
    )
    return path


def test_cli_accepts_decimal_size_and_rejects_invalid_values() -> None:
    args = build_parser().parse_args(["--size", "12.5", "--max-album", "3", "--max-artist", "2"])
    assert args.size == 12.5
    assert args.max_album == 3
    assert args.max_artist == 2
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--size", "0"])
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--max-album", "1.5"])
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--siz", "12"])
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--copy-structure", "tree"])


@pytest.mark.parametrize("value", ["0", "", "sin límite", "sin limite"])
def test_cli_accepts_unlimited_artist_quota(value: str) -> None:
    assert build_parser().parse_args(["--max-artist", value]).max_artist is None


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


def test_normal_run_does_not_read_optional_profiles(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_config(tmp_path / "config.ini")
    monkeypatch.setattr(cli, "load_profiles", lambda *_args: pytest.fail("profiles were loaded"))
    monkeypatch.setattr(cli, "_run", lambda *_args: 0)

    assert cli.main(["--config", str(config_path)]) == 0


def test_explicit_cli_limits_override_loaded_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = _write_config(tmp_path / "config.ini")
    save_profiles_atomic(
        tmp_path / "filter_profiles.json",
        {"Viaje": FilterProfile(size_mb=900, max_album=5, max_artist=6)},
    )
    captured: list[tuple[float, int, int | None]] = []

    def run(args, _settings):  # type: ignore[no-untyped-def]
        captured.append((args.size, args.max_album, args.max_artist))
        return 0

    monkeypatch.setattr(cli, "_run", run)
    result = cli.main(
        [
            "--config",
            str(config_path),
            "--profile",
            "Viaje",
            "--size",
            "12",
            "--max-album",
            "2",
            "--max-artist",
            "3",
        ]
    )

    assert result == 0
    assert captured == [(12.0, 2, 3)]
