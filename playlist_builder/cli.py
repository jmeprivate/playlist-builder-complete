from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .audit import format_audit
from .config import DEFAULT_MAX_ALBUM, DEFAULT_SIZE_MB, MUSIC_ROOT, load_user_config
from .copier import CopyTransactionError, copy_and_write_playlist
from .m3u import write_m3u_atomic
from .scanner import scan_library
from .ui import run_interactive


def positive_decimal(value: str) -> float:
    try:
        number = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("debe ser un número positivo") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("debe ser mayor que cero")
    return number


def positive_integer(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("debe ser un entero positivo") from exc
    if number <= 0:
        raise argparse.ArgumentTypeError("debe ser mayor que cero")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Genera playlists M3U equilibradas desde una discoteca local."
    )
    parser.add_argument(
        "--size",
        type=positive_decimal,
        default=DEFAULT_SIZE_MB,
        metavar="N",
        help=f"tamaño máximo en MB decimales (por defecto: {DEFAULT_SIZE_MB:g})",
    )
    parser.add_argument(
        "--max-album",
        type=positive_integer,
        default=DEFAULT_MAX_ALBUM,
        metavar="N",
        help=f"máximo de canciones por álbum (por defecto: {DEFAULT_MAX_ALBUM})",
    )
    parser.add_argument(
        "--copy",
        type=Path,
        metavar="RUTA",
        help="copia a Music/; sorpresa fuerza nombres planos aunque copy_structure sea tree",
    )
    parser.add_argument(
        "--audit", choices=("simple", "full"), help="muestra auditoría del catálogo"
    )
    parser.add_argument(
        "--audit-only", action="store_true", help="audita y termina sin abrir la interfaz"
    )
    parser.add_argument("--seed", type=int, help="semilla para una selección reproducible")
    surprise = parser.add_mutually_exclusive_group()
    surprise.add_argument(
        "--surprise",
        dest="surprise",
        action="store_true",
        help="oculta la composición hasta crearla",
    )
    surprise.add_argument(
        "--no-surprise",
        dest="surprise",
        action="store_false",
        help="desactiva el modo sorpresa aunque config.ini lo active",
    )
    parser.set_defaults(surprise=None)
    parser.add_argument("--rescan", action="store_true", help="ignora y reconstruye la caché")
    parser.add_argument("--verbose", action="store_true", help="muestra información detallada")
    parser.add_argument(
        "--debug", action="store_true", help="activa logs de depuración y tracebacks"
    )
    return parser


def _configure_logging(verbose: bool, debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


def resolve_surprise(cli_value: bool | None, configured_value: bool) -> bool:
    return configured_value if cli_value is None else cli_value


def _run(args: argparse.Namespace) -> int:
    config = load_user_config()
    surprise = resolve_surprise(args.surprise, config.surprise_mode)
    if surprise and args.audit == "full":
        raise ValueError(
            "--audit full revela rutas y no es compatible con modo sorpresa; "
            "use --audit simple o --no-surprise"
        )
    root = MUSIC_ROOT.expanduser().resolve()
    destination = args.copy.expanduser().resolve() if args.copy else root
    excluded = destination / "Music" if args.copy else None
    songs, report = scan_library(root, rescan=args.rescan, excluded_root=excluded)
    if args.audit or args.audit_only:
        print(format_audit(report, args.audit or "simple"))
    if args.audit_only:
        return 0
    if not songs:
        print("No se encontró ninguna canción legible en la colección.", file=sys.stderr)
        return 2
    result = run_interactive(
        songs,
        max_size_bytes=int(args.size * 1_000_000),
        max_per_album=args.max_album,
        destination=destination,
        seed=args.seed,
        surprise=surprise,
        preview_entries=config.preview_entries,
    )
    if result is None:
        print("Operación cancelada; no se creó ningún archivo.")
        return 1
    playlist_name, selected = result
    missing = [song.path for song in selected if not song.path.is_file()]
    if missing:
        if surprise:
            raise FileNotFoundError(
                "Una o más canciones fueron eliminadas después de la selección; vuelva a ejecutar"
            )
        rendered = "\n".join(f"- {path}" for path in missing)
        raise FileNotFoundError(
            "Algunas canciones fueron eliminadas después del escaneo; vuelva a ejecutar:\n"
            + rendered
        )
    if args.copy:
        copy_result = copy_and_write_playlist(
            destination,
            playlist_name,
            selected,
            surprise=surprise,
            copy_structure=config.copy_structure,
        )
        final_path = copy_result.playlist_path
    else:
        final_path = root / playlist_name
        write_m3u_atomic(final_path, selected)
    print(f"Playlist creada: {final_path}")
    if not surprise:
        print(
            f"{len(selected)} canciones · "
            f"{sum(song.size_bytes for song in selected) / 1_000_000:.2f} MB"
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _configure_logging(args.verbose, args.debug)
    try:
        return _run(args)
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
    except Exception as exc:  # último límite: evita tracebacks en el modo normal
        if args.debug:
            raise
        logging.getLogger(__name__).error("Fallo inesperado: %s", exc)
        print(f"Error inesperado: {exc}. Use --debug para obtener el traceback.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
