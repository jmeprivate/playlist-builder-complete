from __future__ import annotations

import os
import tempfile
import unicodedata
from collections.abc import Mapping
from pathlib import Path

from .models import Song


def _safe_extinf_text(value: str) -> str:
    cleaned = "".join(" " if unicodedata.category(char).startswith("C") else char for char in value)
    return " ".join(cleaned.split())


def _display_title(song: Song) -> str:
    if song.title and song.artist:
        return _safe_extinf_text(f"{', '.join(song.artist)} - {song.title}")
    if song.title:
        return _safe_extinf_text(song.title)
    return _safe_extinf_text(song.path.stem)


def render_m3u(
    songs: list[Song], playlist_directory: Path, path_overrides: Mapping[Path, Path] | None = None
) -> str:
    overrides = path_overrides or {}
    lines = ["#EXTM3U"]
    for song in songs:
        duration = int(song.duration_seconds) if song.duration_seconds is not None else -1
        target = overrides.get(song.path, song.path)
        try:
            entry = os.path.relpath(target, playlist_directory)
        except ValueError:
            entry = str(target)
        portable_entry = Path(entry).as_posix()
        if "\n" in portable_entry or "\r" in portable_entry:
            raise ValueError(f"La ruta no se puede representar de forma segura en M3U: {target}")
        lines.extend((f"#EXTINF:{duration},{_display_title(song)}", portable_entry))
    return "\n".join(lines) + "\n"


def write_m3u_atomic(
    path: Path, songs: list[Song], path_overrides: Mapping[Path, Path] | None = None
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = render_m3u(songs, path.parent, path_overrides)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
