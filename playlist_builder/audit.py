from __future__ import annotations

from .models import AuditReport


def format_audit(report: AuditReport, mode: str) -> str:
    lines = [
        "Informe de auditoría",
        f"- Archivos de audio examinados: {report.total_audio_files}",
        f"- Canciones sin Artist: {report.missing_count('Artist')}",
        f"- Canciones sin Genre: {report.missing_count('Genre')}",
        f"- Canciones sin Year: {report.missing_count('Year')}",
        f"- Con al menos una etiqueta ausente: {report.missing_any_count}",
        f"- Ilegibles o con error de metadatos: {report.unreadable_count}",
    ]
    if mode == "full":
        for issue in report.issues:
            details: list[str] = []
            if issue.missing_tags:
                details.append("faltan " + ", ".join(issue.missing_tags))
            if issue.error:
                details.append("error: " + issue.error)
            lines.append(f"  * {issue.relative_path.as_posix()}: {'; '.join(details)}")
    return "\n".join(lines)
