from pathlib import Path

import pytest

from playlist_builder.config import UserConfig, load_user_config


def test_load_user_config_and_defaults(tmp_path: Path) -> None:
    missing = tmp_path / "missing.ini"
    assert load_user_config(missing) == UserConfig()
    configured = tmp_path / "config.ini"
    configured.write_text(
        "[playlist_builder]\nsurprise_mode = true\npreview_entries = 8\ncopy_structure = tree\n",
        encoding="utf-8",
    )
    assert load_user_config(configured) == UserConfig(True, 8, "tree")


@pytest.mark.parametrize(
    "setting",
    ("preview_entries = 0", "copy_structure = sideways", "surprise_mode = perhaps"),
)
def test_load_user_config_rejects_invalid_values(tmp_path: Path, setting: str) -> None:
    path = tmp_path / "config.ini"
    path.write_text(f"[playlist_builder]\n{setting}\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_user_config(path)
