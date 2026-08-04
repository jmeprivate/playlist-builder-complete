from pathlib import Path

import pytest
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document

from playlist_builder.ui import (
    BACK,
    FirstMatchSuggestion,
    SelectionState,
    SubstringCompleter,
    UIState,
    _normalize_choice,
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


def test_selection_notice_is_consumed_once() -> None:
    state = SelectionState()
    state.add("+", "Björk")
    assert state.take_notice() == "Añadido: Björk"
    assert state.take_notice() == ""


def test_substring_completion_and_back_sentinel() -> None:
    completer = SubstringCompleter(["Björk", "Talking Heads", "Talk Talk"])
    assert completer.matches("+bjork") == ["Björk"]
    assert completer.matches("-HEADS") == ["Talking Heads"]
    suggestion = FirstMatchSuggestion(completer).get_suggestion(Buffer(), Document("+talk"))
    assert suggestion is not None and suggestion.text == "ing Heads"
    assert _normalize_choice(BACK) == BACK
    assert _normalize_choice(" V ") == "v"


def test_playlist_filename_sanitizing_and_increment(tmp_path: Path) -> None:
    assert sanitize_playlist_name("Mi lista", platform="posix") == "Mi lista.m3u"
    assert sanitize_playlist_name("Björk.m3u", platform="posix") == "Björk.m3u"
    assert sanitize_playlist_name("bad:name", platform="nt") == "bad_name.m3u"
    with pytest.raises(ValueError):
        sanitize_playlist_name("..", platform="posix")
    (tmp_path / "Lista.m3u").write_text("existing", encoding="utf-8")
    assert available_playlist_name(tmp_path, "Lista.m3u") == "Lista (2).m3u"


def test_preview_always_contains_the_full_selection(song_factory) -> None:  # type: ignore[no-untyped-def]
    songs = [song_factory(title=f"Title {number}") for number in range(6)]
    preview = format_preview(
        songs,
        max_size_bytes=1_000,
        max_per_album=2,
        playlist_name="Lista.m3u",
    )
    assert "1. Artist - Title 0" in preview
    assert "3. Artist - Title 2" in preview
    assert "6. Artist - Title 5" in preview
    assert "omitidas" not in preview


def test_surprise_preview_masks_every_song_name(song_factory) -> None:  # type: ignore[no-untyped-def]
    songs = [
        song_factory(name="secret-one.mp3", title="Secret one"),
        song_factory(name="secret-two.flac", title="Secret two"),
    ]
    preview = format_preview(
        songs,
        max_size_bytes=1_000,
        max_per_album=2,
        playlist_name="Viaje.m3u",
        surprise=True,
    )
    assert "1 - Viaje.mp3" in preview
    assert "2 - Viaje.flac" in preview
    assert "Secret" not in preview
    assert "secret-" not in preview


def test_album_artist_selection_has_independent_move_and_undo_state() -> None:
    state = UIState()
    state.album_artists.add("+", "Various Artists")
    state.album_artists.add("-", "Various Artists")
    assert state.artists.included == []
    assert state.album_artists.included == []
    assert state.album_artists.excluded == ["Various Artists"]
    state.album_artists.undo()
    assert state.album_artists.excluded == []
