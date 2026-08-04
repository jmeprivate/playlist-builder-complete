from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class Song:
    path: Path
    relative_path: Path
    artist: tuple[str, ...]
    genres: tuple[str, ...]
    year: int | None
    album: str
    album_directory: Path
    size_bytes: int
    title: str | None = None
    duration_seconds: float | None = None
    album_artists: tuple[str, ...] = ()

    @property
    def artists(self) -> tuple[str, ...]:
        """Alias legible para consumidores que prefieren el plural."""
        return self.artist

    def to_cache_dict(self) -> dict[str, Any]:
        return {
            "relative_path": self.relative_path.as_posix(),
            "artist": list(self.artist),
            "album_artists": list(self.album_artists),
            "genres": list(self.genres),
            "year": self.year,
            "album": self.album,
            "album_directory": self.album_directory.as_posix(),
            "size_bytes": self.size_bytes,
            "title": self.title,
            "duration_seconds": self.duration_seconds,
        }

    @classmethod
    def from_cache_dict(cls, root: Path, data: dict[str, Any]) -> Song:
        relative_path = Path(str(data["relative_path"]))
        return cls(
            path=root / relative_path,
            relative_path=relative_path,
            artist=tuple(str(value) for value in data.get("artist", [])),
            album_artists=tuple(str(value) for value in data.get("album_artists", [])),
            genres=tuple(str(value) for value in data.get("genres", [])),
            year=int(data["year"]) if data.get("year") is not None else None,
            album=str(data["album"]),
            album_directory=Path(str(data["album_directory"])),
            size_bytes=int(data["size_bytes"]),
            title=str(data["title"]) if data.get("title") is not None else None,
            duration_seconds=(
                float(data["duration_seconds"])
                if data.get("duration_seconds") is not None
                else None
            ),
        )


@dataclass(frozen=True, slots=True)
class AuditIssue:
    relative_path: Path
    missing_tags: tuple[str, ...] = ()
    error: str | None = None
    informational_tags: tuple[str, ...] = ()


@dataclass(slots=True)
class AuditReport:
    total_audio_files: int = 0
    issues: list[AuditIssue] = field(default_factory=list)

    @property
    def unreadable_count(self) -> int:
        return sum(issue.error is not None for issue in self.issues)

    def missing_count(self, tag: str) -> int:
        return sum(tag in issue.missing_tags for issue in self.issues)

    @property
    def missing_any_count(self) -> int:
        return sum(bool(issue.missing_tags) for issue in self.issues)


@dataclass(frozen=True, slots=True)
class FilterSpec:
    included_artists: frozenset[str] = frozenset()
    excluded_artists: frozenset[str] = frozenset()
    included_album_artists: frozenset[str] = frozenset()
    excluded_album_artists: frozenset[str] = frozenset()
    included_genres: frozenset[str] = frozenset()
    excluded_genres: frozenset[str] = frozenset()
    year_min: int | None = None
    year_max: int | None = None


@dataclass(frozen=True, slots=True)
class CopyResult:
    playlist_path: Path
    copied_paths: dict[Path, Path]
