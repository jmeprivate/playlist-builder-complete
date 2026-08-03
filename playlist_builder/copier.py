from __future__ import annotations

import filecmp
import os
import shutil
import tempfile
from pathlib import Path

from .m3u import write_m3u_atomic
from .models import CopyResult, Song


class CopyTransactionError(RuntimeError):
    pass


def _collision_free_target(target: Path, source: Path) -> tuple[Path, bool]:
    if not target.exists():
        return target, False
    try:
        if filecmp.cmp(source, target, shallow=False):
            return target, True
    except OSError:
        pass
    index = 2
    while True:
        candidate = target.with_name(f"{target.stem} ({index}){target.suffix}")
        if not candidate.exists():
            return candidate, False
        try:
            if filecmp.cmp(source, candidate, shallow=False):
                return candidate, True
        except OSError:
            pass
        index += 1


def copy_and_write_playlist(destination: Path, playlist_name: str, songs: list[Song]) -> CopyResult:
    destination = destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    if not os.access(destination, os.W_OK):
        raise PermissionError(f"El destino no es escribible: {destination}")
    stage = Path(tempfile.mkdtemp(prefix=".playlist-copy-", dir=destination))
    created: list[Path] = []
    mapping: dict[Path, Path] = {}
    staged_items: list[tuple[Path, Path, bool]] = []
    try:
        for index, song in enumerate(songs):
            final_target, reuse = _collision_free_target(
                destination / "Music" / song.relative_path, song.path
            )
            mapping[song.path] = final_target
            if reuse:
                staged_items.append((Path(), final_target, True))
                continue
            staged = stage / f"{index:08d}{song.path.suffix}"
            try:
                shutil.copy2(song.path, staged)
            except OSError as exc:
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
    except BaseException:
        for path in reversed(created):
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        for path in reversed(created):
            parent = path.parent
            while parent != destination and destination in parent.parents:
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
        raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)
