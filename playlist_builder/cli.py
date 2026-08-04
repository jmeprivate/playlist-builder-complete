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
from .m3u import write_m3u_atomic
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
    source = settings.source if settings else default_config_path()
    parser = argparse.ArgumentParser(
        description="Genera playlists M3U equilibradas desde una discoteca local."
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
    surprise = parser.add_mutually_exclusive_group()
    surprise.add_argument(
        "--surprise", dest="surprise", action="store_true", help="oculta la selección"
    )
    surprise.add_argument(
        "--no-surprise", dest="surprise", action="store_false", help="muestra la preview"
    )
    parser.set_defaults(surprise=None)
    parser.add_argument("--rescan", action="store_true", help="ignora y reconstruye la caché")
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
    songs, report = scan_library(
        root,
        rescan=args.rescan,
        excluded_root=excluded,
        settings=settings,
        progress=progress,
    )
    if args.audit or args.audit_only:
        print(format_audit(report, args.audit or "simple"))
    if args.audit_only:
        return 0
    if not songs:
        print("No se encontró ninguna canción legible en la colección.", file=sys.stderr)
        return 2

    # Import after load_config(): ui.py and filters.py receive the selected
    # compatibility defaults when they import values from config.py.
    from . import ui

    result = ui.run_interactive(
        songs,
        max_size_bytes=int(args.size * 1_000_000),
        max_per_album=args.max_album,
        max_per_artist=args.max_artist,
        destination=destination,
        seed=args.seed,
        surprise=surprise,
        preview_entries=settings.preview_entries,
    )
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
            copy_structure=settings.copy_structure,
        ).playlist_path
    else:
        final_path = root / playlist_name
        write_m3u_atomic(final_path, selected)
    print(
        f"Playlist creada: {final_path}\n{len(selected)} canciones · "
        f"{sum(song.size_bytes for song in selected) / 1_000_000:.2f} MB"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    raw_args = sys.argv[1:] if argv is None else argv

    # Help must remain available even when the INI is missing or malformed.
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
        return _run(args, settings)
    except KeyboardInterrupt:
        print(
            "\nCancelado por el usuario; no se han publicado archivos temporales.", file=sys.stderr
        )
        return 130
    except EOFError:
        print("\nLa entrada del terminal se cerró; operación cancelada.", file=sys.stderr)
        return 1
    except (OSError, ValueError, CopyTransactionError) as exc:
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
