from __future__ import annotations

from pathlib import Path

from playlist_builder.config import load_config
from playlist_builder.deduplication import configure_deduplication
from playlist_builder.filters import filter_songs
from playlist_builder.models import FilterSpec


def _write_config(path: Path, *, deduplicate: str | None = None) -> Path:
    optional = f"deduplicate = {deduplicate}\n" if deduplicate is not None else ""
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
audio_extensions = .mp3, .flac
surprise_mode = false
preview_entries = 5
copy_structure = flat
"""
        + optional,
        encoding="utf-8",
    )
    return path


def test_old_config_defaults_deduplication_off(tmp_path: Path) -> None:
    old_settings = load_config(_write_config(tmp_path / "old.ini"))
    enabled_settings = load_config(_write_config(tmp_path / "on.ini", deduplicate="true"))

    assert old_settings.deduplicate is False
    assert enabled_settings.deduplicate is True


def test_filtered_deduplication_is_cached_per_spec(song_factory, monkeypatch) -> None:
    duplicate = song_factory(name="z.mp3", size_bytes=4)
    representative = song_factory(name="a.mp3", size_bytes=4)
    duplicate.path.write_bytes(b"same")
    representative.path.write_bytes(b"same")
    spec = FilterSpec()

    calls = 0

    def counted_hash(_path: Path) -> str:
        nonlocal calls
        calls += 1
        return "same"

    monkeypatch.setattr("playlist_builder.deduplication._sha256", counted_hash)
    configure_deduplication(True)
    try:
        assert filter_songs([duplicate, representative], spec) == [representative]
        assert filter_songs([duplicate, representative], spec) == [representative]
    finally:
        configure_deduplication(False)

    assert calls == 2
    assert filter_songs([duplicate, representative], spec) == [
        duplicate,
        representative,
    ]
