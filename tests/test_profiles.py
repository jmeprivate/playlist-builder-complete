from __future__ import annotations

import json
from pathlib import Path

import pytest

from playlist_builder.profiles import (
    FilterProfile,
    ProfileError,
    load_profiles,
    save_profiles_atomic,
    validate_name,
)


def test_create_load_and_replace_profile_atomically(tmp_path: Path) -> None:
    path = tmp_path / "profiles.json"
    save_profiles_atomic(
        path,
        {"Favorito": FilterProfile(included_artists=["Björk"], included_genres=["Art Pop"])},
    )
    assert load_profiles(path)["Favorito"].included_artists == ["Björk"]

    save_profiles_atomic(
        path,
        {"Favorito": FilterProfile(included_artists=["ROSALÍA"], max_artist=3, size_mb=12.5)},
    )
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["version"] == 1
    assert document["profiles"]["Favorito"]["included_artists"] == ["ROSALÍA"]
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize(
    "content, message",
    [
        ("{", "no se pudo leer"),
        ('{"version": 99, "profiles": {}}', "versión desconocida"),
        ('{"version": 1, "profiles": {"x": {}}}', "no contiene el campo"),
    ],
)
def test_invalid_documents_are_clear_and_unchanged(
    tmp_path: Path, content: str, message: str
) -> None:
    path = tmp_path / "profiles.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ProfileError, match=message):
        load_profiles(path)
    assert path.read_text(encoding="utf-8") == content


@pytest.mark.parametrize("name", ["", " bad", "bad/thing", "bad\\thing", "bad\nthing"])
def test_invalid_profile_names(name: str) -> None:
    with pytest.raises(ProfileError, match="nombre"):
        validate_name(name)


def test_replace_failure_preserves_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "profiles.json"
    path.write_text("original", encoding="utf-8")

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("simulated")

    monkeypatch.setattr("playlist_builder.profiles.os.replace", fail_replace)
    with pytest.raises(ProfileError, match="simulated"):
        save_profiles_atomic(path, {"x": FilterProfile()})
    assert path.read_text(encoding="utf-8") == "original"
