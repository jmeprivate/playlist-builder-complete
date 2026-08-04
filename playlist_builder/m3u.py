from __future__ import annotations

import os
import re
import tempfile
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .models import Song

_URI = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")


@dataclass(frozen=True, slots=True)
class PlaylistMatchReport:
    """Resultado de relacionar entradas locales de playlists con el catálogo."""

    entries: int = 0
    matched: int = 0
    missing: int = 0
    outside_root: int = 0
    not_scanned: int = 0
    unsupported: int = 0

    @property
    def ignored(self) -> int:
        return self.entries - self.matched


def read_m3u(path: Path) -> list[str]:
    """Lee las entradas de una playlist M3U local, sin abrir sus destinos."""

    if path.suffix.casefold() not in {".m3u", ".m3u8"}:
        raise ValueError(f"El formato de playlist no es M3U/M3U8: {path}")
    # utf-8-sig acepta tanto UTF-8 normal como el BOM habitual de M3U8.
    try:
        text = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(
            f"No se pudo leer la playlist como UTF-8 (¿codificación heredada?): {path}"
        ) from exc
    except OSError as exc:
        raise ValueError(f"No se pudo abrir la playlist: {path} ({exc.strerror or exc})") from exc
    lines = text.splitlines()
    return [line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")]


def _canonical_key(path: Path) -> str:
    return unicodedata.normalize("NFC", str(path.resolve(strict=False)))


def _casefold_key(path: Path) -> str:
    return _canonical_key(path).casefold()


def match_playlist_songs(
    songs: list[Song], music_root: Path, playlists: list[Path]
) -> tuple[set[Path], PlaylistMatchReport]:
    """Devuelve rutas canónicas de canciones citadas por una unión de M3U locales."""

    root = music_root.expanduser().resolve()
    catalog = {_canonical_key(song.path): song.path for song in songs}
    # Índice auxiliar insensible a mayúsculas para sistemas de archivos que
    # preservan la escritura pero no distinguen mayúsculas (p. ej. macOS).
    catalog_ci = {_casefold_key(song.path): song.path for song in songs}
    matched: set[Path] = set()
    entries = matched_entries = missing = outside = not_scanned = unsupported = 0
    for playlist in playlists:
        playlist = playlist.expanduser().resolve()
        for entry in read_m3u(playlist):
            entries += 1
            if _URI.match(entry):
                unsupported += 1
                continue
            candidate = Path(entry).expanduser()
            if not candidate.is_absolute():
                candidate = playlist.parent / candidate
            resolved = candidate.resolve(strict=False)
            try:
                resolved.relative_to(root)
            except ValueError:
                outside += 1
                continue
            song_path = catalog.get(_canonical_key(resolved))
            if song_path is None:
                song_path = catalog_ci.get(_casefold_key(resolved))
            if song_path is not None and song_path.is_file():
                matched.add(song_path)
                matched_entries += 1
            elif not resolved.is_file():
                missing += 1
            else:
                not_scanned += 1
    report = PlaylistMatchReport(
        entries, matched_entries, missing, outside, not_scanned, unsupported
    )
    return matched, report


def _safe_extinf_text(value: str) -> str:
    cleaned = "".join(
        " " if unicodedata.category(char) in {"Cc", "Zl", "Zp"} else char for char in value
    )
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
