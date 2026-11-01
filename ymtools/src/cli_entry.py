import argparse
import logging
from pathlib import Path

from ymtools.src import const
from ymtools.src.logger import setup_cli_logging
from ymtools.src.unpacker.unpack import Unpacker

log = logging.getLogger(__name__)

LOG_LEVELS: dict[str, int | None] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warn": logging.WARNING,
    "err": logging.ERROR,
    "no": None,
}


def run_unpack(args: argparse.Namespace) -> int:
    return Unpacker(args.input, args.output, args.combine_fs, args.worker_num).run()


def main(argv: list[str] | None = None) -> int:
    # setup argparser
    parser = argparse.ArgumentParser(prog="ymtools", allow_abbrev=False, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"ymtools {const.VERSION}\nGitHub: {const.GITHUB_URL}")

    parser.add_argument("-l", "--log", choices=list(LOG_LEVELS), default=None, help=f"Log level({list(LOG_LEVELS)}) only logs at or above it are shown ('no' disables logging) (default: info)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Same as '--log debug' (ignored with a warning if --log is given with another level)")
    parser.add_argument("--log-file", type=Path, default=Path.cwd() / "ymtools.log", help="Path of the log file; always overwritten (default: working directory)")

    sub_cmd = parser.add_subparsers(dest="command", required=True)

    # sub commend for unpacker
    unpack = sub_cmd.add_parser("unpack", help="Unpack an apk file")
    unpack.add_argument("-i", "--input", type=Path, required=True, help="Path to the input apk file")
    unpack.add_argument("-o", "--output", type=Path, required=True, help="Directory to extract files into")
    unpack.add_argument("-c", "--combine-fs", action="store_true", help="Extract root files and file sets (FS) into one directory (cannot be repacked; files may be overwritten)")
    unpack.add_argument("-w", "--worker-num", type=int, default=2, help="Number of worker processes (default: %(default)s)")
    unpack.set_defaults(handler=run_unpack)

    # TODO sub commend for packer

    # TODO sub commend for checker

    args = parser.parse_args(argv)
    log_level = args.log or ("debug" if args.verbose else "info")  # -l/--log takes priority over -v/--verbose
    listener, _queue = setup_cli_logging(LOG_LEVELS[log_level], args.log_file)

    try:
        log.info(f"ymtools v{const.VERSION} by akio7624")
        if args.verbose and args.log not in (None, "debug"):
            log.warning(f"-v/--verbose is ignored because --log {args.log} is specified")

        return args.handler(args)
    finally:
        listener.stop()
