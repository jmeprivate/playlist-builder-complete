from __future__ import annotations

import os
import random
import re
from collections.abc import Callable, Iterable
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
from prompt_toolkit.shortcuts import clear, confirm, print_formatted_text

from .config import (
    EMPTY_GENRE_ALIASES,
    MAX_REASONABLE_YEAR_OFFSET,
    MIN_REASONABLE_YEAR,
    GenreAliases,
)
from .filters import complete_year_range, filter_songs
from .models import FilterSpec, Song
from .normalization import deduplicate_display_values, normalize_for_search
from .profiles import FilterProfile
from .selector import SelectionResult, select_balanced_with_stats

BACK = "__BACK__"
NoticeLevel = Literal["info", "warning", "error"]


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
        self.notice = f"{value} se movió a la última operación." if moved else f"Añadido: {value}"

    def undo(self) -> None:
        if not self.history:
            self.notice = "No hay selecciones que eliminar."
            return
        operation, value = self.history.pop()
        target = self.included if operation == "+" else self.excluded
        if value in target:
            target.remove(value)
        self.notice = f"Eliminado: {value}"

    def take_notice(self) -> str:
        notice = self.notice
        self.notice = ""
        return notice


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
    selected: list[Song] = field(default_factory=list)


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


def _show_notice(message: str, level: NoticeLevel = "warning") -> None:
    style = {"info": "ansicyan", "warning": "ansiyellow", "error": "ansired"}[level]
    print_formatted_text(HTML(f"<{style}>{escape_html(message)}</{style}>"))
    print()


def _selection_toolbar(state: SelectionState, completer: SubstringCompleter) -> HTML:
    if state.notice:
        return HTML(f"<ansiyellow>{escape_html(state.notice)}</ansiyellow>")
    text = get_app().current_buffer.text
    if not text:
        return HTML(
            "<dim>+ incluir · - excluir · Enter continuar · Esc volver · Backspace deshacer</dim>"
        )
    if text[:1] not in {"+", "-"}:
        return HTML("<ansired>Empieza con + para incluir o - para excluir.</ansired>")
    if len(text) == 1:
        action = "incluir" if text == "+" else "excluir"
        return HTML(f"<dim>Escribe para {action}; Tab recorre las coincidencias.</dim>")
    matches = completer.matches(text)
    if not matches:
        return HTML("<ansired>No hay coincidencias. Corrige el texto o pulsa Esc.</ansired>")
    return HTML(
        f"<ansicyan>{len(matches)} coincidencia(s)</ansicyan> · "
        f"<b>{escape_html(matches[0])}</b> · "
        "<dim>Tab/Shift+Tab para recorrer, Enter para aceptar</dim>"
    )


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
        if not query:
            state.notice = "Escribe un nombre antes de confirmar."
            get_app().invalidate()
            return
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
            buffer.reset()
            state.notice = "Búsqueda parcial cancelada."
            get_app().invalidate()
        else:
            get_app().exit(result=BACK)

    @bindings.add("backspace")
    def backspace(event: KeyPressEvent) -> None:
        buffer = event.current_buffer
        if buffer.text:
            buffer.delete_before_cursor(count=1)
            state.notice = ""
        else:
            state.undo()
            get_app().invalidate()

    @bindings.add("<any>")
    def insert_text(event: KeyPressEvent) -> None:
        state.notice = ""
        event.current_buffer.insert_text(event.data)

    return bindings


def _show_selections(label: str, state: SelectionState) -> None:
    print_formatted_text(HTML(f"<b><ansicyan>{escape_html(label)}</ansicyan></b>"))
    print("─" * 72)
    included = escape_html(", ".join(state.included) or "ninguno")
    excluded = escape_html(", ".join(state.excluded) or "ninguno")
    print_formatted_text(HTML(f"<ansigreen>  + Incluidos: {included}</ansigreen>"))
    print_formatted_text(HTML(f"<ansired>  - Excluidos: {excluded}</ansired>"))
    print()


def select_values(label: str, options: list[str], state: SelectionState) -> str:
    completer = SubstringCompleter(options)
    while True:
        clear()
        _show_selections(label, state)
        previous_notice = state.take_notice()
        if previous_notice:
            _show_notice(previous_notice)
        session: PromptSession[str] = PromptSession(
            completer=completer,
            complete_while_typing=True,
            auto_suggest=FirstMatchSuggestion(completer),
            key_bindings=_selection_bindings(state, completer),
        )
        result = session.prompt(
            "+/- búsqueda: ",
            bottom_toolbar=lambda: _selection_toolbar(state, completer),
        )
        if result in {"", BACK}:
            return result
        state.add(result[0], result[1:])  # type: ignore[arg-type]


def _simple_prompt(message: str, default: str = "") -> str:
    bindings = KeyBindings()

    @bindings.add("escape")
    def escape(event: KeyPressEvent) -> None:
        buffer = event.current_buffer
        if buffer.text:
            buffer.reset()
        else:
            get_app().exit(result=BACK)

    return PromptSession[str](key_bindings=bindings).prompt(
        message,
        default=default,
        bottom_toolbar="Esc borra la entrada; Esc de nuevo vuelve a la pantalla anterior",
    )


def _normalize_choice(raw: str) -> str:
    return BACK if raw == BACK else raw.strip().casefold()


def sanitize_playlist_name(value: str, platform: str | None = None) -> str:
    name = value.strip()
    if not name.strip(". "):
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


def format_song(song: Song) -> str:
    artist = ", ".join(song.artist) or "Artista desconocido"
    title = song.title or song.path.stem
    details = [value for value in (song.album, str(song.year) if song.year else "") if value]
    suffix = f" — {' · '.join(details)}" if details else ""
    return f"{artist} - {title}{suffix}"


def format_preview(
    selected: list[Song],
    *,
    max_size_bytes: int,
    max_per_album: int,
    edge_entries: int,
    full: bool = False,
) -> str:
    """Render a preview without changing selection or navigation state."""
    lines = [
        "\nPreview de la selección",
        f"{len(selected)} canciones · {_format_mb(sum(song.size_bytes for song in selected))}",
        f"Límites: {_format_mb(max_size_bytes)} · máximo {max_per_album} por álbum",
    ]
    indexed = list(enumerate(selected, 1))
    if not full and len(indexed) > edge_entries * 2:
        visible = indexed[:edge_entries] + indexed[-edge_entries:]
        omitted_at = edge_entries
    else:
        visible = indexed
        omitted_at = -1
    for position, (index, song) in enumerate(visible):
        if position == omitted_at:
            lines.append(f"… {len(indexed) - edge_entries * 2} canciones omitidas …")
        lines.append(f"{index}. {format_song(song)}")
    return "\n".join(lines)


def _different_selection(
    candidates: list[Song],
    previous: list[Song],
    max_size_bytes: int,
    max_per_album: int,
    rng: random.Random,
    max_per_artist: int | None,
) -> SelectionResult:
    """Retry a few unbiased shuffles when an alternative ordering exists."""
    result = SelectionResult(previous, 0)
    for _ in range(8):
        result = select_balanced_with_stats(
            candidates, max_size_bytes, max_per_album, rng, max_per_artist
        )
        if result.songs != previous or len(candidates) < 2:
            break
    return result


def _validate_year(
    year: int | None,
    available_min: int | None,
    available_max: int | None,
    label: str,
    *,
    allow_unavailable: bool = False,
) -> None:
    if year is None:
        return
    maximum_reasonable = datetime.now().year + MAX_REASONABLE_YEAR_OFFSET
    if not MIN_REASONABLE_YEAR <= year <= maximum_reasonable:
        raise ValueError(f"{label} debe estar entre {MIN_REASONABLE_YEAR} y {maximum_reasonable}")
    if not allow_unavailable and available_min is not None and year < available_min:
        raise ValueError(f"{label} es menor que el mínimo disponible ({available_min})")
    if not allow_unavailable and available_max is not None and year > available_max:
        raise ValueError(f"{label} es mayor que el máximo disponible ({available_max})")


def run_interactive(
    songs: list[Song],
    *,
    max_size_bytes: int,
    max_per_album: int,
    max_per_artist: int | None = None,
    destination: Path,
    seed: int | None,
    surprise: bool = False,
    preview_entries: int = 5,
    initial_profile: FilterProfile | None = None,
    on_confirm: Callable[[FilterProfile], None] | None = None,
    genre_aliases: GenreAliases = EMPTY_GENRE_ALIASES,
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
        genre_aliases.display_options(value for song in songs for value in song.genres),
        key=normalize_for_search,
    )
    years = [song.year for song in songs if song.year is not None]
    available_min = min(years) if years else None
    available_max = max(years) if years else None
    year_text = f"{available_min}-{available_max}" if years else "sin años válidos"
    print_formatted_text(HTML("<b>¡Creemos una playlist!</b>"))
    if surprise:
        print("\nModo sorpresa activo: el contenido permanecerá oculto hasta crear la playlist.\n")
    else:
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
    if initial_profile is not None:
        state.artists.included = list(initial_profile.included_artists)
        state.artists.excluded = list(initial_profile.excluded_artists)
        state.album_artists.included = list(initial_profile.included_album_artists)
        state.album_artists.excluded = list(initial_profile.excluded_album_artists)
        state.genres.included = list(initial_profile.included_genres)
        state.genres.excluded = list(initial_profile.excluded_genres)
        for filter_state in (state.artists, state.album_artists, state.genres):
            filter_state.history = [("+", item) for item in filter_state.included] + [
                ("-", item) for item in filter_state.excluded
            ]
        state.year_min_input = initial_profile.year_min
        state.year_max_input = initial_profile.year_max
        missing: list[str] = []
        for label, filter_state, available in (
            ("artista de pista", state.artists, artists),
            ("artista de álbum", state.album_artists, album_artists),
            ("género", state.genres, genres),
        ):
            known = {normalize_for_search(item) for item in available}
            missing.extend(
                f"{label}: {item}"
                for item in filter_state.included + filter_state.excluded
                if normalize_for_search(item) not in known
            )
        if missing:
            notice = "El perfil conserva selecciones sin coincidencia actual: " + "; ".join(missing)
            # select_values clears the terminal, so attach the warning to every
            # relevant first screen instead of printing a message that vanishes.
            state.artists.notice = notice
            state.album_artists.notice = notice
            state.genres.notice = notice
        profile_has_no_year_match = (
            not years
            and (initial_profile.year_min is not None or initial_profile.year_max is not None)
        ) or (
            available_min is not None
            and available_max is not None
            and (
                (initial_profile.year_min is not None and initial_profile.year_min > available_max)
                or (
                    initial_profile.year_max is not None
                    and initial_profile.year_max < available_min
                )
            )
        )
        if profile_has_no_year_match:
            year_notice = (
                "El perfil conserva un intervalo de años sin coincidencia actual: "
                f"{initial_profile.year_min or '…'}-{initial_profile.year_max or '…'}"
            )
            state.artists.notice = " ".join(filter(None, (state.artists.notice, year_notice)))
    session_rng = random.Random() if seed is None else random.Random(seed)
    candidates: list[Song] = []
    skipped_by_artist_quota = 0
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
                _validate_year(
                    state.year_min_input,
                    available_min,
                    available_max,
                    "el año mínimo",
                    allow_unavailable=(
                        initial_profile is not None
                        and state.year_min_input == initial_profile.year_min
                    ),
                )
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
                _validate_year(
                    state.year_max_input,
                    available_min,
                    available_max,
                    "el año máximo",
                    allow_unavailable=(
                        initial_profile is not None
                        and state.year_max_input == initial_profile.year_max
                    ),
                )
                state.year_min, state.year_max = complete_year_range(
                    state.year_min_input,
                    state.year_max_input,
                    available_min,
                    available_max,
                )
                state.selected = []
                skipped_by_artist_quota = 0
                screen = 5
            except ValueError as exc:
                print(f"Valor no válido: {exc}")
        elif screen == 5:
            spec = _to_filter_spec(state)
            candidates = filter_songs(songs, spec, genre_aliases)
            if not state.selected:
                selection = select_balanced_with_stats(
                    candidates,
                    max_size_bytes,
                    max_per_album,
                    seed if seed is not None else session_rng,
                    max_per_artist,
                )
                state.selected = selection.songs
                skipped_by_artist_quota = selection.skipped_by_artist_quota
            if not state.selected:
                choice = _normalize_choice(
                    _simple_prompt("No hay canciones seleccionables. [f]iltros / [c]ancelar: ")
                )
                if choice == "c":
                    return None
                if choice in {"f", BACK}:
                    screen = 4
                continue
            if surprise:
                screen = 6
                continue
            print(
                format_preview(
                    state.selected,
                    max_size_bytes=max_size_bytes,
                    max_per_album=max_per_album,
                    edge_entries=preview_entries,
                )
            )
            choice = _normalize_choice(
                _simple_prompt("[a]ceptar resultado / [r]ehacer / [v]er completa / [c]ancelar: ")
            )
            if choice == "a":
                screen = 6
            elif choice == "v":
                print(
                    format_preview(
                        state.selected,
                        max_size_bytes=max_size_bytes,
                        max_per_album=max_per_album,
                        edge_entries=preview_entries,
                        full=True,
                    )
                )
            elif choice == "r":
                if seed is not None:
                    print("La selección está fijada por --seed; no se cambiará silenciosamente.")
                    action = _normalize_choice(_simple_prompt("[f]iltros / [c]ancelar: "))
                    if action == "c":
                        return None
                    if action in {"f", BACK}:
                        screen = 4
                else:
                    selection = _different_selection(
                        candidates,
                        state.selected,
                        max_size_bytes,
                        max_per_album,
                        session_rng,
                        max_per_artist,
                    )
                    state.selected = selection.songs
                    skipped_by_artist_quota = selection.skipped_by_artist_quota
            elif choice == "c":
                return None
        elif screen == 6:
            result = _simple_prompt("¿Qué nombre le damos a la playlist? ", state.playlist_name)
            if result == BACK:
                screen = 5
                continue
            try:
                requested = sanitize_playlist_name(result)
                state.playlist_name = available_playlist_name(destination, requested)
                if state.playlist_name != requested:
                    print(f"Ya existía; se usará: {state.playlist_name}")
                screen = 7
            except ValueError as exc:
                print(f"Nombre no válido: {exc}")
        else:
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
            print(f"Máximo por artista de pista: {max_per_artist or 'sin límite'}")
            print(f"Destino: {destination}")
            if surprise:
                print("Modo sorpresa activo: composición oculta")
            else:
                candidate_size = _format_mb(sum(song.size_bytes for song in candidates))
                selected_size = _format_mb(sum(song.size_bytes for song in state.selected))
                print(f"Canciones candidatas: {len(candidates)} ({candidate_size})")
                if max_per_artist is not None:
                    print(f"Candidatas omitidas por cuota de artista: {skipped_by_artist_quota}")
                print(f"Canciones que entrarán: {len(state.selected)} ({selected_size})")
            choice = _normalize_choice(
                _simple_prompt("[s] confirmar / [v] volver / [c] cancelar: ")
            )
            if choice == "s":
                if on_confirm is not None:
                    on_confirm(
                        FilterProfile(
                            included_artists=list(state.artists.included),
                            excluded_artists=list(state.artists.excluded),
                            included_album_artists=list(state.album_artists.included),
                            excluded_album_artists=list(state.album_artists.excluded),
                            included_genres=list(state.genres.included),
                            excluded_genres=list(state.genres.excluded),
                            year_min=state.year_min_input,
                            year_max=state.year_max_input,
                            max_album=max_per_album,
                            max_artist=max_per_artist,
                            size_mb=max_size_bytes / 1_000_000,
                        )
                    )
                return state.playlist_name, state.selected
            if choice == "v" or choice == BACK:
                screen = 6
            elif choice == "c":
                return None
