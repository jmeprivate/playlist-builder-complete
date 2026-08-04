from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from playlist_builder import ui
from playlist_builder.models import Song


def _drive_prompts(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> None:
    responses: Iterator[str] = iter(answers)
    monkeypatch.setattr(ui, "select_values", lambda *args: "")
    monkeypatch.setattr(ui, "_simple_prompt", lambda *args, **kwargs: next(responses))
    monkeypatch.setattr(ui, "print_formatted_text", lambda *args, **kwargs: None)


def test_preview_selection_is_the_selection_returned_for_writing(
    tmp_path: Path,
    song_factory: Callable[..., Song],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    songs = [song_factory(title="First"), song_factory(title="Second")]
    rendered: list[list[Song]] = []
    real_format = ui.format_preview

    def capture(selected: list[Song], **kwargs: object) -> str:
        rendered.append(list(selected))
        return real_format(selected, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(ui, "format_preview", capture)
    _drive_prompts(monkeypatch, ["", "", "a", "Lista", "s"])
    result = ui.run_interactive(
        songs,
        max_size_bytes=1_000,
        max_per_album=2,
        destination=tmp_path,
        seed=7,
    )
    assert result is not None
    assert rendered == [result[1]]


def test_surprise_never_calls_preview_formatter(
    tmp_path: Path,
    song_factory: Callable[..., Song],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    song = song_factory(title="Secret title", artist=("Secret artist",))
    monkeypatch.setattr(
        ui,
        "format_preview",
        lambda *args, **kwargs: pytest.fail("surprise rendered the preview"),
    )
    _drive_prompts(monkeypatch, ["", "", "Sorpresa", "s"])
    result = ui.run_interactive(
        [song],
        max_size_bytes=1_000,
        max_per_album=1,
        destination=tmp_path,
        seed=3,
        surprise=True,
    )
    assert result == ("Sorpresa.m3u", [song])


def test_retry_reuses_candidates_and_limits(
    tmp_path: Path,
    song_factory: Callable[..., Song],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    songs = [song_factory(title="First"), song_factory(title="Second")]
    calls: list[tuple[list[Song], int, int]] = []

    def select(candidates: list[Song], size: int, album: int, seed: object) -> list[Song]:
        calls.append((list(candidates), size, album))
        return list(reversed(candidates)) if len(calls) == 1 else list(candidates)

    monkeypatch.setattr(ui, "select_balanced", select)
    _drive_prompts(monkeypatch, ["", "", "r", "a", "Lista", "s"])
    result = ui.run_interactive(
        songs,
        max_size_bytes=321,
        max_per_album=1,
        destination=tmp_path,
        seed=None,
    )
    assert result is not None
    assert len(calls) == 2
    assert calls[0] == calls[1] == (songs, 321, 1)
    assert result[1] == songs
