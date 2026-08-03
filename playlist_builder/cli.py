from __future__ import annotations

import argparse
import logging
import math
import sys
from pathlib import Path

from .audit import format_audit
from .config import DEFAULT_MAX_ALBUM, DEFAULT_SIZE_MB, MUSIC_ROOT
from .copier import CopyTransactionError, copy_and_write_playlist
from .m3u import write_m3u_atomic
from .scanner import scan_library
from .ui import run_interactive


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
    parser.add_argument("--copy", type=Path, metavar="RUTA", help="copia la selección al destino")
    parser.add_argument(
        "--audit", choices=("simple", "full"), help="muestra auditoría del catálogo"
    )
    parser.add_argument(
        "--audit-only", action="store_true", help="audita y termina sin abrir la interfaz"
    )
    parser.add_argument("--seed", type=int, help="semilla para una selección reproducible")
    parser.add_argument("--rescan", action="store_true", help="ignora y reconstruye la caché")
    parser.add_argument("--verbose", action="store_true", help="muestra información detallada")
    parser.add_argument(
        "--debug", action="store_true", help="activa logs de depuración y tracebacks"
    )
    return parser


def _configure_logging(verbose: bool, debug: bool) -> None:
    level = logging.DEBUG if debug else logging.INFO if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s: %(message)s")


def _run(args: argparse.Namespace) -> int:
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
        copy_result = copy_and_write_playlist(destination, playlist_name, selected)
        final_path = copy_result.playlist_path
    else:
        final_path = root / playlist_name
        write_m3u_atomic(final_path, selected)
    print(
        f"Playlist creada: {final_path}\n"
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
            "\nCancelado por el usuario; se han retirado los archivos parciales.",
            file=sys.stderr,
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
