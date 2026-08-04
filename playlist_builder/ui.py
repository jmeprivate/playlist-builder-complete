from __future__ import annotations

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from html import escape as escape_html
from pathlib import Path
from typing import Literal

from prompt_toolkit import PromptSession
from prompt_toolkit.application.current import get_app
from prompt_toolkit.auto_suggest import AutoSuggest, Suggestion
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.shortcuts import confirm, print_formatted_text

from .config import MAX_REASONABLE_YEAR_OFFSET, MIN_REASONABLE_YEAR
from .filters import complete_year_range, filter_songs
from .models import FilterSpec, Song
from .normalization import deduplicate_display_values, normalize_for_search
from .selector import select_balanced

BACK = "__BACK__"


@dataclass(slots=True)
class SelectionState:
    included: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    history: list[tuple[Literal["+", "-"], str]] = field(default_factory=list)
    notice: str = ""

    def add(self, operation: Literal["+", "-"], value: str) -> None:
        own = self.included if operation == "+" else self.excluded
        other = self.excluded if operation == "+" else self.included
        moved = value in other
        if value in own:
            own.remove(value)
        if moved:
            other.remove(value)
        self.history = [(op, item) for op, item in self.history if item != value]
        own.append(value)
        self.history.append((operation, value))
        self.notice = f"{value} movido a la última operación." if moved else ""

    def undo(self) -> None:
        if not self.history:
            self.notice = "No hay selecciones que eliminar."
            return
        operation, value = self.history.pop()
        target = self.included if operation == "+" else self.excluded
        if value in target:
            target.remove(value)
        self.notice = f"Eliminado: {value}"


@dataclass(slots=True)
class UIState:
    artists: SelectionState = field(default_factory=SelectionState)
    album_artists: SelectionState = field(default_factory=SelectionState)
    genres: SelectionState = field(default_factory=SelectionState)
    year_min_input: int | None = None
    year_max_input: int | None = None
    year_min: int | None = None
    year_max: int | None = None
    playlist_name: str = ""


class SubstringCompleter(Completer):
    def __init__(self, options: list[str]) -> None:
        self.options = options

    def matches(self, text: str) -> list[str]:
        query = text[1:] if text[:1] in {"+", "-"} else text
        normalized = normalize_for_search(query)
        if not normalized:
            return []
        return [option for option in self.options if normalized in normalize_for_search(option)]

    def get_completions(
        self, document: Document, complete_event: CompleteEvent
    ) -> Iterable[Completion]:  # pragma: no cover - prompt_toolkit drives this generator
        text = document.text_before_cursor
        query = text[1:] if text[:1] in {"+", "-"} else text
        for option in self.matches(text):
            yield Completion(option, start_position=-len(query), display=option)


class FirstMatchSuggestion(AutoSuggest):
    def __init__(self, completer: SubstringCompleter) -> None:
        self.completer = completer

    def get_suggestion(self, buffer: Buffer, document: Document) -> Suggestion | None:
        text = document.text_before_cursor
        query = text[1:] if text[:1] in {"+", "-"} else text
        matches = self.completer.matches(text)
        if matches and normalize_for_search(matches[0]).startswith(normalize_for_search(query)):
            return Suggestion(matches[0][len(query) :])
        return None


def _selection_bindings(state: SelectionState, completer: SubstringCompleter) -> KeyBindings:
    bindings = KeyBindings()

    @bindings.add("enter")
    def accept(event: KeyPressEvent) -> None:
        buffer = event.current_buffer
        text = buffer.text
        if not text:
            get_app().exit(result="")
            return
        if text[:1] not in {"+", "-"}:
            state.notice = "Empieza con + para incluir o - para excluir."
            get_app().invalidate()
            return
        query = text[1:].strip()
        matches = completer.matches(text)
        exact = next(
            (
                item
                for item in completer.options
                if normalize_for_search(item) == normalize_for_search(query)
            ),
            None,
        )
        chosen = exact or (matches[0] if matches else None)
        if chosen is None:
            state.notice = "No existe una opción válida con ese texto."
            get_app().invalidate()
            return
        get_app().exit(result=text[0] + chosen)

    @bindings.add("escape")
    def escape(event: KeyPressEvent) -> None:
        buffer = event.current_buffer
        if buffer.text:
            buffer.text = ""
            state.notice = "Búsqueda parcial cancelada."
        else:
            get_app().exit(result=BACK)

    @bindings.add("backspace")
    def backspace(event: KeyPressEvent) -> None:
        buffer = event.current_buffer
        if buffer.text:
            buffer.delete_before_cursor(count=1)
        else:
            state.undo()
            get_app().invalidate()

    return bindings


def _show_selections(label: str, state: SelectionState) -> None:
    print_formatted_text(HTML(f"<b>{escape_html(label)}</b>"))
    included = escape_html(", ".join(state.included) or "—")
    excluded = escape_html(", ".join(state.excluded) or "—")
    print_formatted_text(HTML(f"  <ansigreen>Incluidos: {included}</ansigreen>"))
    print_formatted_text(HTML(f"  <ansired>Excluidos: {excluded}</ansired>"))
    if state.notice:
        print_formatted_text(HTML(f"  <ansiyellow>{escape_html(state.notice)}</ansiyellow>"))


def select_values(label: str, options: list[str], state: SelectionState) -> str:
    completer = SubstringCompleter(options)
    while True:
        _show_selections(label, state)
        session: PromptSession[str] = PromptSession(
            completer=completer,
            complete_while_typing=True,
            auto_suggest=FirstMatchSuggestion(completer),
            key_bindings=_selection_bindings(state, completer),
        )
        result = session.prompt(
            "+ incluir / - excluir (Enter vacío: continuar): ",
            bottom_toolbar=(
                "Tab/Shift+Tab: coincidencias · Esc: cancelar/volver · Backspace vacío: deshacer"
            ),
        )
        state.notice = ""
        if result in {"", BACK}:
            return result
        state.add(result[0], result[1:])  # type: ignore[arg-type]


def _simple_prompt(message: str, default: str = "") -> str:
    bindings = KeyBindings()

    @bindings.add("escape")
    def escape(event: KeyPressEvent) -> None:
        buffer = event.current_buffer
        if buffer.text:
            buffer.text = ""
        else:
            get_app().exit(result=BACK)

    return PromptSession[str](key_bindings=bindings).prompt(message, default=default)


def sanitize_playlist_name(value: str, platform: str | None = None) -> str:
    name = value.strip()
    if name in {"", ".", ".."}:
        raise ValueError("el nombre de la playlist no puede estar vacío, ser '.' ni '..'")
    system = platform or os.name
    illegal = r'[<>:"/\\|?*\x00-\x1f]' if system == "nt" else r"[/\x00]"
    name = re.sub(illegal, "_", name)
    if system == "nt":
        name = name.rstrip(" .")
        stem = Path(name).stem.casefold()
        reserved = {
            "con",
            "prn",
            "aux",
            "nul",
            *(f"com{i}" for i in range(1, 10)),
            *(f"lpt{i}" for i in range(1, 10)),
        }
        if stem in reserved:
            name = "_" + name
    if name.casefold().endswith(".m3u"):
        name = name[:-4] + ".m3u"
    else:
        name += ".m3u"
    if name in {".m3u", "..m3u"} or not Path(name).stem.strip(". "):
        raise ValueError("el nombre de la playlist no puede estar vacío, ser '.' ni '..'")
    return name


def available_playlist_name(directory: Path, requested: str) -> str:
    target = directory / requested
    if not target.exists():
        return requested
    index = 2
    while True:
        candidate = f"{target.stem} ({index}){target.suffix}"
        if not (directory / candidate).exists():
            return candidate
        index += 1


def _to_filter_spec(state: UIState) -> FilterSpec:
    norm = normalize_for_search
    return FilterSpec(
        included_artists=frozenset(map(norm, state.artists.included)),
        excluded_artists=frozenset(map(norm, state.artists.excluded)),
        included_album_artists=frozenset(map(norm, state.album_artists.included)),
        excluded_album_artists=frozenset(map(norm, state.album_artists.excluded)),
        included_genres=frozenset(map(norm, state.genres.included)),
        excluded_genres=frozenset(map(norm, state.genres.excluded)),
        year_min=state.year_min,
        year_max=state.year_max,
    )


def _format_mb(size: int) -> str:
    return f"{size / 1_000_000:.2f} MB"


def _validate_year(
    year: int | None,
    available_min: int | None,
    available_max: int | None,
    label: str,
) -> None:
    if year is None:
        return
    maximum_reasonable = datetime.now().year + MAX_REASONABLE_YEAR_OFFSET
    if not MIN_REASONABLE_YEAR <= year <= maximum_reasonable:
        raise ValueError(f"{label} debe estar entre {MIN_REASONABLE_YEAR} y {maximum_reasonable}")
    if available_min is not None and year < available_min:
        raise ValueError(f"{label} es menor que el mínimo disponible ({available_min})")
    if available_max is not None and year > available_max:
        raise ValueError(f"{label} es mayor que el máximo disponible ({available_max})")


def run_interactive(
    songs: list[Song],
    *,
    max_size_bytes: int,
    max_per_album: int,
    destination: Path,
    seed: int | None,
) -> tuple[str, list[Song]] | None:
    artists = sorted(
        deduplicate_display_values(value for song in songs for value in song.artist),
        key=normalize_for_search,
    )
    album_artists = sorted(
        deduplicate_display_values(value for song in songs for value in song.album_artists),
        key=normalize_for_search,
    )
    genres = sorted(
        deduplicate_display_values(value for song in songs for value in song.genres),
        key=normalize_for_search,
    )
    years = [song.year for song in songs if song.year is not None]
    available_min = min(years) if years else None
    available_max = max(years) if years else None
    year_text = f"{available_min}-{available_max}" if years else "sin años válidos"
    print_formatted_text(HTML("<b>¡Creemos una playlist!</b>"))
    print(
        f"\nEncontrados:\n- {len(artists)} artistas de pista\n"
        f"- {len(album_artists)} artistas de álbum\n- {len(genres)} géneros\n"
        f"- {len(songs)} canciones\n- años disponibles: {year_text}\n"
    )
    print(
        "Usa + para incluir, - para excluir, Tab para coincidencias, "
        "Enter para aceptar y Esc para volver.\n"
    )

    state = UIState()
    screen = 0
    while True:
        if screen == 0:
            result = select_values("Artistas de pista", artists, state.artists)
            if result == BACK:
                if confirm("¿Salir sin crear nada?"):
                    return None
            else:
                screen = 1
        elif screen == 1:
            result = select_values("Artistas de álbum", album_artists, state.album_artists)
            screen = 0 if result == BACK else 2
        elif screen == 2:
            result = select_values("Géneros", genres, state.genres)
            screen = 1 if result == BACK else 3
        elif screen == 3:
            result = _simple_prompt(
                f"Desde el año (mín. {available_min or '—'}): ",
                str(state.year_min_input or ""),
            )
            if result == BACK:
                screen = 2
                continue
            try:
                state.year_min_input = int(result) if result.strip() else None
                _validate_year(state.year_min_input, available_min, available_max, "el año mínimo")
                screen = 4
            except ValueError as exc:
                print(f"Valor no válido: {exc}")
        elif screen == 4:
            result = _simple_prompt(
                f"Hasta el año (máx. {available_max or '—'}): ",
                str(state.year_max_input or ""),
            )
            if result == BACK:
                screen = 3
                continue
            try:
                state.year_max_input = int(result) if result.strip() else None
                _validate_year(state.year_max_input, available_min, available_max, "el año máximo")
                state.year_min, state.year_max = complete_year_range(
                    state.year_min_input,
                    state.year_max_input,
                    available_min,
                    available_max,
                )
                screen = 5
            except ValueError as exc:
                print(f"Valor no válido: {exc}")
        elif screen == 5:
            result = _simple_prompt("¿Qué nombre le damos a la playlist? ", state.playlist_name)
            if result == BACK:
                screen = 4
                continue
            try:
                requested = sanitize_playlist_name(result)
                state.playlist_name = available_playlist_name(destination, requested)
                if state.playlist_name != requested:
                    print(f"Ya existía; se usará: {state.playlist_name}")
                screen = 6
            except ValueError as exc:
                print(f"Nombre no válido: {exc}")
        else:
            spec = _to_filter_spec(state)
            candidates = filter_songs(songs, spec)
            selected = select_balanced(candidates, max_size_bytes, max_per_album, seed)
            print("\nResumen")
            print(f"Artistas incluidos: {', '.join(state.artists.included) or 'cualquiera'}")
            print(f"Artistas excluidos: {', '.join(state.artists.excluded) or 'ninguno'}")
            print(
                "Artistas de álbum incluidos: "
                f"{', '.join(state.album_artists.included) or 'cualquiera'}"
            )
            print(
                "Artistas de álbum excluidos: "
                f"{', '.join(state.album_artists.excluded) or 'ninguno'}"
            )
            print(f"Géneros incluidos: {', '.join(state.genres.included) or 'cualquiera'}")
            print(f"Géneros excluidos: {', '.join(state.genres.excluded) or 'ninguno'}")
            years_summary = (
                f"{state.year_min}-{state.year_max}" if state.year_min is not None else "sin filtro"
            )
            print(f"Años: {years_summary}")
            print(f"Tamaño máximo: {_format_mb(max_size_bytes)}")
            print(f"Máximo por álbum: {max_per_album}")
            print(f"Destino: {destination}")
            candidate_size = _format_mb(sum(song.size_bytes for song in candidates))
            selected_size = _format_mb(sum(song.size_bytes for song in selected))
            print(f"Canciones candidatas: {len(candidates)} ({candidate_size})")
            print(f"Canciones que entrarán: {len(selected)} ({selected_size})")
            if not selected:
                choice = (
                    _simple_prompt("No hay canciones seleccionables. [v]olver / [c]ancelar: ")
                    .strip()
                    .casefold()
                )
                if choice == "v" or choice == BACK:
                    screen = 5
                elif choice == "c":
                    return None
                continue
            choice = (
                _simple_prompt("[s] confirmar / [v] volver / [c] cancelar: ").strip().casefold()
            )
            if choice == "s":
                return state.playlist_name, selected
            if choice == "v" or choice == BACK:
                screen = 5
            elif choice == "c":
                return None
