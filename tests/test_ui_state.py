from pathlib import Path

import pytest

from playlist_builder.ui import (
    SelectionState,
    UIState,
    available_playlist_name,
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


def test_album_artist_selection_has_independent_move_and_undo_state() -> None:
    state = UIState()
    state.album_artists.add("+", "Various Artists")
    state.album_artists.add("-", "Various Artists")
    assert state.artists.included == []
    assert state.album_artists.included == []
    assert state.album_artists.excluded == ["Various Artists"]
    state.album_artists.undo()
    assert state.album_artists.excluded == []
