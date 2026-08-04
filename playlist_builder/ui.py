from __future__ import annotations

import os
import random
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from html import escape as escape_html
from pathlib import Path
from typing import Literal

from prompt_toolkit import PromptSession
from prompt_toolkit.application.current import get_app
from prompt_toolkit.auto_suggest import AutoSuggest, Suggestion
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.shortcuts import clear, confirm, print_formatted_text
from prompt_toolkit.styles import Style

from .config import EMPTY_GENRE_ALIASES, GenreAliases
from .filters import complete_year_range, filter_songs
from .m3u import surprise_display_name
from .models import FilterSpec, Song
from .normalization import deduplicate_display_values, normalize_for_search
from .profiles import FilterProfile
from .selector import SelectionResult, select_balanced_with_stats

BACK = "__BACK__"
_REDRAW = "__REDRAW__"
NoticeLevel = Literal["info", "warning", "error"]
_OPERATION = Literal["+", "-"]
_SELECTOR_STYLE = Style.from_dict(
    {
        "selection.include": "ansigreen",
        "selection.exclude": "ansired",
        "auto-suggestion": "ansibrightblack",
    }
)


@dataclass(slots=True)
class SelectionState:
    included: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    history: list[tuple[_OPERATION, str]] = field(default_factory=list)
    notice: str = ""

    def add(self, operation: _OPERATION, value: str) -> None:
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
        self.notice = f"{value} se movió a la última operación." if moved else ""

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


def _prefix_matches(options: list[str], text: str) -> list[str]:
    if text[:1] not in {"+", "-"}:
        return []
    query = normalize_for_search(text[1:])
    return [option for option in options if normalize_for_search(option).startswith(query)]


def _suggested_suffix(option: str, query: str) -> str:
    normalized_query = normalize_for_search(query)
    if not normalized_query:
        return option
    for index in range(len(option) + 1):
        if normalize_for_search(option[:index]) == normalized_query:
            return option[index:]
    return option[len(query) :]


@dataclass(slots=True)
class SelectionCursor:
    options: list[str]
    operation: _OPERATION | None = None
    query: str = ""
    matches: tuple[str, ...] = ()
    index: int = 0
    preselected: bool = False
    notice: str = ""

    def preselect(self, text: str) -> str | None:
        if text[:1] not in {"+", "-"}:
            self.notice = "Pulsa + para incluir o - para excluir."
            return None
        matches = tuple(_prefix_matches(self.options, text))
        if not matches:
            self.notice = "No hay valores que empiecen por ese texto."
            return None
        self.operation = "+" if text[0] == "+" else "-"
        self.query = text[1:]
        self.matches = matches
        self.index = 0
        self.preselected = True
        self.notice = ""
        return self.operation + self.matches[0]

    def cycle(self) -> str | None:
        if not self.preselected or self.operation is None or not self.matches:
            return None
        self.index = (self.index + 1) % len(self.matches)
        return self.operation + self.matches[self.index]

    def cancel(self) -> str:
        result = (self.operation or "") + self.query
        self.operation = None
        self.query = ""
        self.matches = ()
        self.index = 0
        self.preselected = False
        self.notice = ""
        return result

    def accept(self) -> str | None:
        if not self.preselected or self.operation is None or not self.matches:
            return None
        return self.operation + self.matches[self.index]


class PrefixSuggestion(AutoSuggest):
    def __init__(self, cursor: SelectionCursor) -> None:
        self.cursor = cursor

    def get_suggestion(self, buffer: Buffer, document: Document) -> Suggestion | None:
        if self.cursor.preselected:
            return None
        text = document.text_before_cursor
        matches = _prefix_matches(self.cursor.options, text)
        if not matches:
            return None
        return Suggestion(_suggested_suffix(matches[0], text[1:]))


class OperationLexer(Lexer):
    def lex_document(self, document: Document):  # type: ignore[no-untyped-def]
        text = document.text
        if text.startswith("+"):
            style = "class:selection.include"
        elif text.startswith("-"):
            style = "class:selection.exclude"
        else:
            style = ""
        return lambda _line: [(style, text)]


def _show_notice(message: str, level: NoticeLevel = "warning") -> None:
    style = {"info": "ansicyan", "warning": "ansiyellow", "error": "ansired"}[level]
    print_formatted_text(HTML(f"<{style}>{escape_html(message)}</{style}>"))
    print()


def _selection_toolbar(cursor: SelectionCursor) -> HTML:
    if cursor.notice:
        return HTML(f"<ansiyellow>{escape_html(cursor.notice)}</ansiyellow>")
    if cursor.preselected:
        return HTML(
            "<dim>Enter acepta · Tab muestra el siguiente · Esc quita la preselección</dim>"
        )
    text = get_app().current_buffer.text
    if not text:
        return HTML(
            "<dim><ansigreen>+ incluir</ansigreen> · <ansired>- excluir</ansired> · "
            "Enter todos · Esc volver · Backspace deshacer</dim>"
        )
    matches = _prefix_matches(cursor.options, text)
    if not matches:
        return HTML("<ansired>No hay valores que empiecen por ese texto.</ansired>")
    return HTML("<dim>Enter o Tab preselecciona · Esc vuelve</dim>")


def _set_buffer_text(buffer: Buffer, text: str) -> None:
    buffer.text = text
    buffer.cursor_position = len(text)


def _selection_bindings(state: SelectionState, cursor: SelectionCursor) -> KeyBindings:
    bindings = KeyBindings()

    @bindings.add("enter")
    def enter(event: KeyPressEvent) -> None:
        buffer = event.current_buffer
        if cursor.preselected:
            result = cursor.accept()
            if result is not None:
                get_app().exit(result=result)
            return
        if not buffer.text:
            get_app().exit(result="")
            return
        result = cursor.preselect(buffer.text)
        if result is not None:
            _set_buffer_text(buffer, result)
        get_app().invalidate()

    @bindings.add("tab")
    def tab(event: KeyPressEvent) -> None:
        buffer = event.current_buffer
        result = cursor.cycle() if cursor.preselected else cursor.preselect(buffer.text)
        if result is not None:
            _set_buffer_text(buffer, result)
        get_app().invalidate()

    @bindings.add("escape")
    def escape(event: KeyPressEvent) -> None:
        if cursor.preselected:
            _set_buffer_text(event.current_buffer, cursor.cancel())
            get_app().invalidate()
        else:
            get_app().exit(result=BACK)

    @bindings.add("backspace")
    def backspace(event: KeyPressEvent) -> None:
        buffer = event.current_buffer
        if cursor.preselected:
            _set_buffer_text(buffer, cursor.cancel())
            get_app().invalidate()
        elif buffer.text:
            buffer.delete_before_cursor(count=1)
            cursor.notice = ""
        else:
            state.undo()
            get_app().exit(result=_REDRAW)

    @bindings.add("<any>")
    def insert_text(event: KeyPressEvent) -> None:
        buffer = event.current_buffer
        if cursor.preselected:
            cursor.notice = "Enter acepta, Tab cambia y Esc quita la preselección."
        elif not buffer.text:
            if event.data in {"+", "-"}:
                buffer.insert_text(event.data)
                cursor.notice = ""
            else:
                cursor.notice = "Pulsa + para incluir o - para excluir."
        elif buffer.text[:1] in {"+", "-"}:
            buffer.insert_text(event.data)
            cursor.notice = ""
        else:
            cursor.notice = "Pulsa + para incluir o - para excluir."
        get_app().invalidate()

    return bindings


def _show_selections(label: str, state: SelectionState) -> None:
    print_formatted_text(HTML(f"<b><ansicyan>{escape_html(label)}</ansicyan></b>"))
    print("─" * 72)
    if not state.history:
        print_formatted_text(HTML("<ansibrightblack>Enter sin elegir = todos</ansibrightblack>"))
    else:
        for operation, value in state.history:
            color = "ansigreen" if operation == "+" else "ansired"
            print_formatted_text(HTML(f"<{color}>{operation} {escape_html(value)}</{color}>"))
    print()


def select_values(label: str, options: list[str], state: SelectionState) -> str:
    while True:
        clear()
        _show_selections(label, state)
        previous_notice = state.take_notice()
        if previous_notice:
            _show_notice(previous_notice)
        cursor = SelectionCursor(options)
        result = PromptSession[str](
            auto_suggest=PrefixSuggestion(cursor),
            lexer=OperationLexer(),
            key_bindings=_selection_bindings(state, cursor),
            style=_SELECTOR_STYLE,
        ).prompt("", bottom_toolbar=lambda: _selection_toolbar(cursor))
        if result in {"", BACK}:
            return result
        if result == _REDRAW:
            continue
        operation: _OPERATION = "+" if result[0] == "+" else "-"
        state.add(operation, result[1:])


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


def _year_prompt(label: str, available: int | None, default: int | None) -> str:
    bindings = KeyBindings()

    @bindings.add("escape")
    def escape(_event: KeyPressEvent) -> None:
        get_app().exit(result=BACK)

    available_text = str(available) if available is not None else "sin datos"
    message = HTML(
        f"<b>{escape_html(label)}</b> "
        f"<ansibrightblack>(encontrado: {escape_html(available_text)})</ansibrightblack>: "
    )
    return PromptSession[str](key_bindings=bindings).prompt(
        message,
        default=str(default) if default is not None else "",
        bottom_toolbar="Enter vacío = todos · Esc = volver",
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
    details = [
        value
        for value in (song.album, str(song.year) if song.year is not None else "")
        if value
    ]
    suffix = f" — {' · '.join(details)}" if details else ""
    return f"{artist} - {title}{suffix}"


def format_preview(
    selected: list[Song],
    *,
    max_size_bytes: int,
    max_per_album: int,
    playlist_name: str,
    surprise: bool = False,
) -> str:
    lines = [
        "\nPreview de la selección",
        f"{len(selected)} canciones · {_format_mb(sum(song.size_bytes for song in selected))}",
        f"Límites: {_format_mb(max_size_bytes)} · máximo {max_per_album} por álbum",
    ]
    for index, song in enumerate(selected, 1):
        if surprise:
            lines.append(surprise_display_name(index, playlist_name, song))
        else:
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
    result = SelectionResult(previous, 0)
    for _ in range(8):
        result = select_balanced_with_stats(
            candidates, max_size_bytes, max_per_album, rng, max_per_artist
        )
        if result.songs != previous or len(candidates) < 2:
            break
    return result


def run_interactive(
    songs: list[Song],
    *,
    max_size_bytes: int,
    max_per_album: int,
    max_per_artist: int | None = None,
    destination: Path,
    seed: int | None,
    surprise: bool = False,
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
    print(
        f"\nEncontrados:\n- {len(artists)} artistas de pista\n"
        f"- {len(album_artists)} artistas de álbum\n- {len(genres)} géneros\n"
        f"- {len(songs)} canciones\n- años disponibles: {year_text}\n"
    )
    if surprise:
        print(
            "Modo sorpresa activo: los nombres se mostrarán enmascarados "
            "hasta la reproducción.\n"
        )
    print(
        "Pulsa + para incluir, - para excluir, Enter para aceptar o avanzar "
        "y Esc para volver.\n"
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
        for label, filter_state, available, resolve in (
            ("artista de pista", state.artists, artists, normalize_for_search),
            ("artista de álbum", state.album_artists, album_artists, normalize_for_search),
            ("género", state.genres, genres, genre_aliases.resolve),
        ):
            known = {resolve(item) for item in available}
            missing.extend(
                f"{label}: {item}"
                for item in filter_state.included + filter_state.excluded
                if resolve(item) not in known
            )
        if missing:
            notice = "El perfil conserva selecciones sin coincidencia actual: " + "; ".join(missing)
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
            minimum = (
                str(initial_profile.year_min)
                if initial_profile.year_min is not None
                else "…"
            )
            maximum = (
                str(initial_profile.year_max)
                if initial_profile.year_max is not None
                else "…"
            )
            year_notice = (
                "El perfil conserva un intervalo de años sin coincidencia actual: "
                f"{minimum}-{maximum}"
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
            result = _year_prompt("Año mínimo", available_min, state.year_min_input)
            if result == BACK:
                screen = 2
                continue
            try:
                state.year_min_input = int(result) if result.strip() else None
                screen = 4
            except ValueError:
                print("Valor no válido: el año debe ser un número entero")
        elif screen == 4:
            result = _year_prompt("Año máximo", available_max, state.year_max_input)
            if result == BACK:
                screen = 3
                continue
            try:
                state.year_max_input = int(result) if result.strip() else None
                state.year_min, state.year_max = complete_year_range(
                    state.year_min_input,
                    state.year_max_input,
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
            screen = 6
        elif screen == 6:
            result = _simple_prompt("¿Qué nombre le damos a la playlist? ", state.playlist_name)
            if result == BACK:
                screen = 4
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
            candidate_size = _format_mb(sum(song.size_bytes for song in candidates))
            selected_size = _format_mb(sum(song.size_bytes for song in state.selected))
            print(f"Canciones candidatas: {len(candidates)} ({candidate_size})")
            if max_per_artist is not None:
                print(f"Candidatas omitidas por cuota de artista: {skipped_by_artist_quota}")
            print(f"Canciones que entrarán: {len(state.selected)} ({selected_size})")
            if surprise:
                print("Modo sorpresa activo: nombres enmascarados")
            print(
                format_preview(
                    state.selected,
                    max_size_bytes=max_size_bytes,
                    max_per_album=max_per_album,
                    playlist_name=state.playlist_name,
                    surprise=surprise,
                )
            )
            choice = _normalize_choice(
                _simple_prompt(
                    "[s] confirmar / [r]ehacer / [n] cambiar nombre / [f]iltros / [c] cancelar: "
                )
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
            if choice == "r":
                if seed is not None:
                    print("La selección está fijada por --seed y no puede rehacerse.")
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
            elif choice == "n":
                screen = 6
            elif choice in {"f", BACK}:
                screen = 4
            elif choice == "c":
                return None
