import pytest

from playlist_builder.cli import _run, build_parser, resolve_surprise


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
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:  # type: ignore[no-untyped-def]
    (tmp_path / "config.ini").write_text(
        "[playlist_builder]\nsurprise_mode = true\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ValueError, match="audit full"):
        _run(build_parser().parse_args(["--audit", "full"]))
