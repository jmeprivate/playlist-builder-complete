from pathlib import Path

from playlist_builder.audit import format_audit
from playlist_builder.models import AuditIssue, AuditReport


def test_simple_and_full_audit() -> None:
    report = AuditReport(
        total_audio_files=4,
        issues=[
            AuditIssue(Path("a.mp3"), ("Artist", "Year")),
            AuditIssue(Path("b.flac"), ("Genre",)),
            AuditIssue(Path("compilation.mp3"), informational_tags=("AlbumArtist",)),
            AuditIssue(Path("bad.wma"), error="ValueError: corrupto"),
        ],
    )
    simple = format_audit(report, "simple")
    assert "Canciones sin Artist: 1" in simple
    assert "Con al menos una etiqueta ausente: 2" in simple
    assert "Ilegibles o con error de metadatos: 1" in simple
    assert "a.mp3" not in simple
    assert "compilation.mp3" not in simple
    full = format_audit(report, "full")
    assert "a.mp3: faltan Artist, Year" in full
    assert "compilation.mp3: sin AlbumArtist (informativo)" in full
    assert "bad.wma: error: ValueError: corrupto" in full
