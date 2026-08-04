from __future__ import annotations

from pathlib import Path

import pytest

from playlist_builder import cli, config
from playlist_builder.config import ConfigError, load_config


def write_config(path: Path, **changes: str) -> Path:
    values = {
        "music_root": "music",
        "default_size_mb": "8000",
        "default_max_album": "2",
        "default_max_artist": "0",
        "cache_filename": ".cache.json",
        "max_reasonable_year_offset": "5",
        "surprise_mode": "false",
    } | changes
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[playlist_builder]\n" + "".join(f"{key} = {value}\n" for key, value in values.items()),
        encoding="utf-8",
    )
    return path


def test_load_valid_config_normalizes_values(tmp_path: Path) -> None:
    settings = load_config(write_config(tmp_path / "custom.ini"))
    assert settings.music_root == (tmp_path / "music").resolve()
    assert settings.audio_extensions == frozenset(
        {".mp3", ".flac", ".m4a", ".mp4", ".ogg", ".opus", ".ape"}
    )
    assert settings.profiles_file == (tmp_path / "filter_profiles.json").resolve()
    assert settings.default_size_mb == 8000
    assert settings.default_max_artist == 0
    assert settings.max_reasonable_year_offset == 5
    assert settings.surprise_mode is False


def test_cli_values_override_ini(tmp_path: Path) -> None:
    settings = load_config(
        write_config(tmp_path / "custom.ini", default_size_mb="10", default_max_artist="4")
    )
    args = cli.build_parser(settings).parse_args(["--size", "12.5", "--max-album", "7"])
    assert (args.size, args.max_album, args.max_artist) == (12.5, 7, 4)


def test_help_does_not_require_valid_config(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as caught:
        cli.main(["--config", str(tmp_path / "missing.ini"), "--help"])
    assert caught.value.code == 0


def test_installed_default_is_copied_to_user_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    package = tmp_path / "site-packages" / "playlist_builder"
    template = package / "config.ini"
    write_config(template)
    user_config = tmp_path / "user" / "config.ini"
    monkeypatch.setattr(config, "__file__", str(package / "config.py"))
    monkeypatch.setattr(config, "_user_config_path", lambda: user_config)
    monkeypatch.setattr(config.sys, "argv", [str(tmp_path / "bin" / "python")])

    settings = load_config()

    assert settings.source == user_config.resolve()
    assert user_config.read_text(encoding="utf-8") == template.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "changes, key",
    [
        ({"music_root": ""}, "music_root"),
        ({"default_size_mb": "nan"}, "default_size_mb"),
        ({"cache_filename": "folder\\cache.json"}, "cache_filename"),
        ({"surprise_mode": "perhaps"}, "surprise_mode"),
        ({"default_max_artist": "-1"}, "default_max_artist"),
        ({"max_reasonable_year_offset": "-1"}, "max_reasonable_year_offset"),
    ],
)
def test_invalid_values_identify_file_section_and_key(
    tmp_path: Path, changes: dict[str, str], key: str
) -> None:
    path = write_config(tmp_path / "bad.ini", **changes)
    with pytest.raises(ConfigError) as caught:
        load_config(path)
    message = str(caught.value)
    assert str(path) in message and "[playlist_builder]" in message and key in message


@pytest.mark.parametrize(
    "key, value",
    [
        ("audio_extensions", ".mp3"),
        ("copy_structure", "tree"),
        ("profiles_file", "other.json"),
        ("default_year_margin", "5"),
        ("retry_error_after_days", "7"),
        ("min_reasonable_year", "1000"),
        ("preview_entries", "5"),
    ],
)
def test_fixed_or_removed_behaviors_cannot_be_configured(
    tmp_path: Path, key: str, value: str
) -> None:
    path = write_config(tmp_path / "unsupported.ini", **{key: value})
    with pytest.raises(ConfigError, match=rf"{key}: clave desconocida"):
        load_config(path)


def test_unknown_section_is_rejected(tmp_path: Path) -> None:
    path = write_config(tmp_path / "extra.ini")
    with path.open("a", encoding="utf-8") as stream:
        stream.write("\n[playlsit_builder]\nmusic_root = typo\n")
    with pytest.raises(ConfigError, match=r"\[playlsit_builder\].*sección desconocida"):
        load_config(path)


def test_shipped_formats_match_supported_catalog() -> None:
    settings = load_config()
    assert settings.audio_extensions == frozenset(
        {".mp3", ".flac", ".m4a", ".mp4", ".ogg", ".opus", ".ape"}
    )
