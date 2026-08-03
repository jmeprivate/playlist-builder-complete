from pathlib import Path

import pytest
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document

from playlist_builder.ui import (
    FirstMatchSuggestion,
    SelectionState,
    SubstringCompleter,
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


def test_substring_completion_ignores_case_and_accents() -> None:
    completer = SubstringCompleter(["Björk", "Talking Heads", "Talk Talk"])
    assert completer.matches("+bjork") == ["Björk"]
    assert completer.matches("-HEADS") == ["Talking Heads"]
    suggestion = FirstMatchSuggestion(completer).get_suggestion(Buffer(), Document("+talk"))
    assert suggestion is not None
    assert suggestion.text == "ing Heads"


def test_playlist_filename_sanitizing_and_increment(tmp_path: Path) -> None:
    assert sanitize_playlist_name("Mi lista", platform="posix") == "Mi lista.m3u"
    assert sanitize_playlist_name("Björk.m3u", platform="posix") == "Björk.m3u"
    assert sanitize_playlist_name("bad:name", platform="nt") == "bad_name.m3u"
    with pytest.raises(ValueError):
        sanitize_playlist_name("..", platform="posix")
    (tmp_path / "Lista.m3u").write_text("existing", encoding="utf-8")
    assert available_playlist_name(tmp_path, "Lista.m3u") == "Lista (2).m3u"
