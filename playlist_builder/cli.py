from __future__ import annotations

import argparse
import logging
import math
import sys
from pathlib import Path

from . import config as config_module
from .audit import format_audit
from .config import ConfigError, Settings, default_config_path, load_config
from .copier import CopyTransactionError, copy_and_write_playlist
from .deduplication import configure_deduplication
from .m3u import match_playlist_songs, write_m3u_atomic
from .profiles import (
    FilterProfile,
    ProfileError,
    format_profile_summary,
    load_profiles,
    save_profiles_atomic,
    validate_name,
)
from .progress import ConsoleScanProgress
from .scanner import scan_library


def positive_decimal(value: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("debe ser un número positivo") from exc
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("debe ser un número finito mayor que cero")
    return number


def positive_integer(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("debe ser un entero positivo") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("debe ser mayor que cero")
    return number


def optional_quota(value: str) -> int | None:
    normalized = value.strip().casefold()
    if normalized in {"", "0", "sin límite", "sin limite"}:
        return None
    return positive_integer(value)


def build_parser(settings: Settings | None = None) -> argparse.ArgumentParser:
    size = settings.default_size_mb if settings else config_module.DEFAULT_SIZE_MB
    max_album = settings.default_max_album if settings else config_module.DEFAULT_MAX_ALBUM
    max_artist = settings.default_max_artist if settings else config_module.DEFAULT_MAX_ARTIST
    deduplicate_default = settings.deduplicate if settings else config_module.DEFAULT_DEDUPLICATE
    source = settings.source if settings else default_config_path()
    parser = argparse.ArgumentParser(
        description="Genera playlists M3U equilibradas desde una discoteca local.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--size",
        type=positive_decimal,
        default=size,
        metavar="N",
        help=f"tamaño máximo en MB decimales (configuración: {size:g})",
    )
    parser.add_argument(
        "--max-album",
        type=positive_integer,
        default=max_album,
        metavar="N",
        help=f"máximo de canciones por álbum (configuración: {max_album})",
    )
    parser.add_argument(
        "--max-artist",
        type=optional_quota,
        default=max_artist or None,
        metavar="N",
        help=(
            "máximo por artista de pista; 0 o 'sin límite' lo desactiva "
            f"(configuración: {max_artist or 'sin límite'})"
        ),
    )
    parser.add_argument("--copy", type=Path, metavar="RUTA", help="copia la selección al destino")
    parser.add_argument(
        "--audit", choices=("simple", "full"), help="muestra auditoría del catálogo"
    )
    parser.add_argument(
        "--audit-only", action="store_true", help="audita y termina sin abrir la interfaz"
    )
    parser.add_argument("--seed", type=int, help="semilla para una selección reproducible")
    deduplicate = parser.add_mutually_exclusive_group()
    deduplicate.add_argument(
        "--deduplicate",
        dest="deduplicate",
        action="store_true",
        help="elimina duplicados por contenido de las candidatas filtradas",
    )
    deduplicate.add_argument(
        "--no-deduplicate",
        dest="deduplicate",
        action="store_false",
        help="desactiva la deduplicación configurada",
    )
    parser.set_defaults(deduplicate=deduplicate_default)
    parser.add_argument(
        "--from-playlist",
        type=Path,
        action="append",
        default=[],
        metavar="RUTA",
        help="restringe las candidatas a canciones de esta M3U/M3U8 (repetible)",
    )
    parser.add_argument(
        "--exclude-playlist",
        type=Path,
        action="append",
        default=[],
        metavar="RUTA",
        help="excluye canciones de esta M3U/M3U8 (repetible)",
    )
    surprise = parser.add_mutually_exclusive_group()
    surprise.add_argument(
        "--surprise",
        dest="surprise",
        action="store_true",
        help="enmascara los nombres de las canciones hasta reproducirlas",
    )
    surprise.add_argument(
        "--no-surprise",
        dest="surprise",
        action="store_false",
        help="muestra los nombres reales en la preview",
    )
    parser.set_defaults(surprise=None)
    parser.add_argument(
        "--rescan",
        action="store_true",
        help="reconstruye la caché y reintenta los metadatos fallidos",
    )
    parser.add_argument("--verbose", action="store_true", help="muestra información detallada")
    parser.add_argument(
        "--debug", action="store_true", help="activa logs de depuración y tracebacks"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=source,
        metavar="RUTA",
        help=f"archivo INI de configuración (por defecto: {source})",
    )
    parser.add_argument("--profile", metavar="NOMBRE", help="carga un perfil de filtros")
    parser.add_argument(
        "--save-profile", metavar="NOMBRE", help="guarda los filtros confirmados como perfil"
    )
    parser.add_argument(
        "--list-profiles", action="store_true", help="lista los perfiles sin abrir la interfaz"
    )
    parser.add_argument(
        "--force", action="store_true", help="reemplaza un perfil existente sin preguntar"
    )
    return parser


def _configure_logging(verbose: bool, debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


def resolve_surprise(cli_value: bool | None, configured_value: bool) -> bool:
    return configured_value if cli_value is None else cli_value


def _run(args: argparse.Namespace, settings: Settings) -> int:
    surprise = resolve_surprise(args.surprise, settings.surprise_mode)
    if surprise and args.audit == "full":
        raise ValueError(
            "--audit full revela rutas y no es compatible con modo sorpresa; "
            "use --audit simple o --no-surprise"
        )
    root = settings.music_root
    destination = args.copy.expanduser().resolve() if args.copy else root
    excluded = destination / "Music" if args.copy else None
    progress = None if args.audit_only else ConsoleScanProgress(sys.stderr)
    songs, audit_report = scan_library(
        root,
        rescan=args.rescan,
        excluded_root=excluded,
        settings=settings,
        progress=progress,
    )
    if args.audit or args.audit_only:
        print(format_audit(audit_report, args.audit or "simple"))
    if args.audit_only:
        return 0
    if not songs:
        print("No se encontró ninguna canción legible en la colección.", file=sys.stderr)
        return 2

    catalog = songs
    if args.from_playlist:
        included, playlist_report = match_playlist_songs(songs, root, args.from_playlist)
        logging.getLogger(__name__).info(
            "Playlists fuente: %d coincidencias; %d entradas ignoradas "
            "(inexistentes=%d, fuera=%d, no escaneadas=%d, no admitidas=%d)",
            playlist_report.matched,
            playlist_report.ignored,
            playlist_report.missing,
            playlist_report.outside_root,
            playlist_report.not_scanned,
            playlist_report.unsupported,
        )
        songs = [song for song in songs if song.path in included]
        if not songs:
            raise ValueError("--from-playlist no contiene ninguna canción válida de la discoteca")
    if args.exclude_playlist:
        excluded_paths, playlist_report = match_playlist_songs(catalog, root, args.exclude_playlist)
        logging.getLogger(__name__).info(
            "Playlists de exclusión: %d coincidencias; %d entradas ignoradas "
            "(inexistentes=%d, fuera=%d, no escaneadas=%d, no admitidas=%d)",
            playlist_report.matched,
            playlist_report.ignored,
            playlist_report.missing,
            playlist_report.outside_root,
            playlist_report.not_scanned,
            playlist_report.unsupported,
        )
        songs = [song for song in songs if song.path not in excluded_paths]
        if not songs:
            raise ValueError(
                "--exclude-playlist excluyó todas las canciones candidatas de la discoteca"
            )

    from . import ui

    def save_confirmed(profile: FilterProfile) -> None:
        if not args.save_profile:
            return
        profiles = load_profiles(settings.profiles_file)
        if args.save_profile in profiles and not args.force:
            from prompt_toolkit.shortcuts import confirm

            if not confirm(f"El perfil {args.save_profile!r} ya existe. ¿Reemplazarlo?"):
                print("Perfil no reemplazado; la playlist continuará.")
                return
        profiles[args.save_profile] = profile
        save_profiles_atomic(settings.profiles_file, profiles)
        print(f"Perfil guardado: {args.save_profile}")

    configure_deduplication(args.deduplicate)
    try:
        result = ui.run_interactive(
            songs,
            max_size_bytes=int(args.size * 1_000_000),
            max_per_album=args.max_album,
            max_per_artist=args.max_artist,
            destination=destination,
            seed=args.seed,
            surprise=surprise,
            initial_profile=getattr(args, "loaded_profile", None),
            on_confirm=save_confirmed if args.save_profile else None,
            genre_aliases=settings.genre_aliases,
        )
    finally:
        configure_deduplication(False)
    if result is None:
        print("Operación cancelada; no se creó ningún archivo.")
        return 1
    playlist_name, selected = result
    missing = [song.path for song in selected if not song.path.is_file()]
    if missing:
        rendered = "\n".join(f"- {path}" for path in missing)
        raise FileNotFoundError(
            "Algunas canciones fueron eliminadas después del escaneo; vuelva a ejecutar:\n"
            + rendered
        )
    if args.copy:
        final_path = copy_and_write_playlist(
            destination,
            playlist_name,
            selected,
            surprise=surprise,
        ).playlist_path
    else:
        final_path = root / playlist_name
        write_m3u_atomic(
            final_path,
            selected,
            surprise=surprise,
            playlist_name=playlist_name,
        )
    print(
        f"Playlist creada: {final_path}\n{len(selected)} canciones · "
        f"{sum(song.size_bytes for song in selected) / 1_000_000:.2f} MB"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    raw_args = sys.argv[1:] if argv is None else argv
    if "-h" in raw_args or "--help" in raw_args:
        build_parser().parse_args(raw_args)
        return 0

    bootstrap = argparse.ArgumentParser(add_help=False)
    bootstrap.add_argument("--config", type=Path)
    bootstrap.add_argument("--debug", action="store_true")
    preliminary, _ = bootstrap.parse_known_args(raw_args)
    try:
        settings = load_config(preliminary.config)
    except ConfigError as exc:
        if preliminary.debug:
            raise
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    args = build_parser(settings).parse_args(raw_args)
    _configure_logging(args.verbose, args.debug)
    try:
        if args.force and not args.save_profile:
            raise ValueError("--force solo puede usarse junto con --save-profile")
        if args.profile:
            validate_name(args.profile)
        if args.save_profile:
            validate_name(args.save_profile)
        profiles = (
            load_profiles(settings.profiles_file)
            if args.profile or args.save_profile or args.list_profiles
            else {}
        )
        if args.list_profiles:
            for name, profile in sorted(profiles.items()):
                print(format_profile_summary(name, profile))
            if not profiles:
                print("No hay perfiles guardados.")
            return 0
        if args.profile:
            try:
                loaded = profiles[args.profile]
            except KeyError as exc:
                raise ProfileError(f"no existe el perfil {args.profile!r}") from exc
            args.loaded_profile = loaded

            def explicit(option: str) -> bool:
                return any(item == option or item.startswith(option + "=") for item in raw_args)

            if not explicit("--size"):
                args.size = loaded.size_mb
            if not explicit("--max-album"):
                args.max_album = loaded.max_album
            if not explicit("--max-artist"):
                args.max_artist = loaded.max_artist
        return _run(args, settings)
    except KeyboardInterrupt:
        print(
            "\nCancelado por el usuario; no se han publicado archivos temporales.", file=sys.stderr
        )
        return 130
    except EOFError:
        print("\nLa entrada del terminal se cerró; operación cancelada.", file=sys.stderr)
        return 1
    except (OSError, ValueError, ProfileError, CopyTransactionError) as exc:
        if args.debug:
            raise
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        if args.debug:
            raise
        logging.getLogger(__name__).error("Fallo inesperado: %s", exc)
        print(f"Error inesperado: {exc}. Use --debug para obtener el traceback.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
