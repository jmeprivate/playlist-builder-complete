from __future__ import annotations

import filecmp
import os
import re
import shutil
import tempfile
from pathlib import Path

from .m3u import write_m3u_atomic
from .models import CopyResult, Song


class CopyTransactionError(RuntimeError):
    pass


def _collision_free_target(
    target: Path, source: Path, reserved: set[Path] | None = None
) -> tuple[Path, bool]:
    unavailable = reserved or set()
    if not target.exists() and target not in unavailable:
        return target, False
    if target not in unavailable:
        try:
            if filecmp.cmp(source, target, shallow=False):
                return target, True
        except OSError:
            pass
    index = 2
    while True:
        candidate = target.with_name(f"{target.stem} ({index}){target.suffix}")
        if not candidate.exists() and candidate not in unavailable:
            return candidate, False
        if candidate not in unavailable:
            try:
                if filecmp.cmp(source, candidate, shallow=False):
                    return candidate, True
            except OSError:
                pass
        index += 1


def _safe_component(value: str, platform: str | None = None) -> str:
    system = platform or os.name
    illegal = r'[<>:"/\\|?*\x00-\x1f]' if system == "nt" else r"[/\x00]"
    value = re.sub(illegal, "_", value)
    if system == "nt":
        value = value.rstrip(" .")
    return value or "Playlist"


def _normal_flat_name(index: int, song: Song) -> str:
    title = song.title or song.path.stem
    artist = ", ".join(song.artist) or "Artista desconocido"
    return f"{index} - {_safe_component(title)} ({_safe_component(artist)}){song.path.suffix}"


def copy_and_write_playlist(
    destination: Path,
    playlist_name: str,
    songs: list[Song],
    *,
    surprise: bool = False,
    copy_structure: str = "flat",
) -> CopyResult:
    destination = destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    if not os.access(destination, os.W_OK):
        raise PermissionError(f"El destino no es escribible: {destination}")
    stage = Path(tempfile.mkdtemp(prefix=".playlist-copy-", dir=destination))
    created: list[Path] = []
    mapping: dict[Path, Path] = {}
    staged_items: list[tuple[Path, Path, bool]] = []
    try:
        reserved: set[Path] = set()
        base_name = _safe_component(Path(playlist_name).stem)
        for index, song in enumerate(songs, 1):
            if surprise:
                relative = Path(f"{index} - {base_name}{song.path.suffix}")
            elif copy_structure == "tree":
                relative = song.relative_path
            else:
                relative = Path(_normal_flat_name(index, song))
            final_target, reuse = _collision_free_target(
                destination / "Music" / relative, song.path, reserved
            )
            reserved.add(final_target)
            mapping[song.path] = final_target
            if reuse:
                staged_items.append((Path(), final_target, True))
                continue
            staged = stage / f"{index:08d}{song.path.suffix}"
            try:
                shutil.copy2(song.path, staged)
            except OSError as exc:
                if surprise:
                    raise CopyTransactionError(
                        "Falló la copia de una canción seleccionada; no se publicó el M3U"
                    ) from exc
                raise CopyTransactionError(f"Falló la copia de {song.path}: {exc}") from exc
            staged_items.append((staged, final_target, False))
        for staged, target, reuse in staged_items:
            if reuse:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged, target)
            created.append(target)
        playlist_path = destination / playlist_name
        write_m3u_atomic(playlist_path, songs, mapping)
        return CopyResult(playlist_path, mapping)
    except (OSError, CopyTransactionError) as exc:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        if surprise and not isinstance(exc, CopyTransactionError):
            raise CopyTransactionError(
                "Falló la publicación de la copia en modo sorpresa; no se publicó el M3U"
            ) from exc
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)
