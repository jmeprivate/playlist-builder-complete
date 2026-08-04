from pathlib import Path

import pytest

from playlist_builder.ui import (
    SelectionState,
    available_playlist_name,
    format_preview,
    sanitize_playlist_name,
)


def test_selection_state_moves_and_undoes_last_real_operation() -> None:
    state = SelectionState()
    state.add("+", "Björk")
    state.add("-", "Talk Talk")
    state.add("-", "Björk")
    assert state.included == []
    assert state.excluded == ["Talk Talk", "Björk"]
    state.undo()
    assert state.excluded == ["Talk Talk"]


def test_playlist_filename_sanitizing_and_increment(tmp_path: Path) -> None:
    assert sanitize_playlist_name("Mi lista", platform="posix") == "Mi lista.m3u"
    assert sanitize_playlist_name("Björk.m3u", platform="posix") == "Björk.m3u"
    assert sanitize_playlist_name("bad:name", platform="nt") == "bad_name.m3u"
    with pytest.raises(ValueError):
        sanitize_playlist_name("..", platform="posix")
    (tmp_path / "Lista.m3u").write_text("existing", encoding="utf-8")
    assert available_playlist_name(tmp_path, "Lista.m3u") == "Lista (2).m3u"


def test_preview_is_numbered_and_truncates_both_ends(song_factory) -> None:  # type: ignore[no-untyped-def]
    songs = [song_factory(title=f"Title {number}") for number in range(6)]
    preview = format_preview(songs, max_size_bytes=1_000, max_per_album=2, edge_entries=2)
    assert "1. Artist - Title 0" in preview
    assert "2 canciones omitidas" in preview
    assert "6. Artist - Title 5" in preview
    assert "3. Artist - Title 2" not in preview
    full = format_preview(songs, max_size_bytes=1_000, max_per_album=2, edge_entries=2, full=True)
    assert "3. Artist - Title 2" in full
