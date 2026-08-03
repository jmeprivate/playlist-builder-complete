import re
import unicodedata
from collections.abc import Iterable

_SPACES = re.compile(r"\s+")


def normalize_for_search(value: str) -> str:
    """Normaliza para comparar sin alterar el valor que se muestra al usuario."""
    normalized = unicodedata.normalize("NFKD", value)
    without_marks = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return _SPACES.sub(" ", without_marks).strip().casefold()


def deduplicate_display_values(values: Iterable[str]) -> tuple[str, ...]:
    by_normalized: dict[str, str] = {}
    for raw in values:
        display = _SPACES.sub(" ", str(raw)).strip()
        key = normalize_for_search(display)
        if key and key not in by_normalized:
            by_normalized[key] = display
    return tuple(by_normalized.values())
