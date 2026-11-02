import argparse
import logging
import os
import platform
import sys
from pathlib import Path

from ymtools.src import const
from ymtools.src.logger import setup_cli_logging
from ymtools.src.structure._validator import raise_if_invalid
from ymtools.src.structure.apk import APK
from ymtools.src.structure.exceptions import IdxException, ValidationException
from ymtools.src.structure.idx import IDX
from ymtools.src.unpacker.unpack import Unpacker

log = logging.getLogger(__name__)

LOG_LEVELS: dict[str, int | None] = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warn": logging.WARNING,
    "err": logging.ERROR,
    "no": None,
}


def print_env(args: argparse.Namespace) -> None:
    log.debug("[Environment]")
    log.debug(f"  ymtools   : v{const.VERSION}")
    log.debug(f"  python    : {platform.python_version()} ({platform.python_implementation()})")
    log.debug(f"  platform  : {platform.platform()} / {platform.machine()}")
    log.debug(f"  cpu count : {os.cpu_count()}")
    log.debug(f"  frozen    : {getattr(sys, 'frozen', False)}")
    log.debug(f"  executable: {sys.executable}")
    log.debug(f"  cwd       : {Path.cwd()}")
    log.debug(f"  argv      : {sys.argv}")

    log.debug("[Arguments]")
    for key, value in sorted(vars(args).items()):
        if key != "handler":
            log.debug(f"  {key}: {value!r}")


def run_unpack(args: argparse.Namespace) -> int:
    return Unpacker(args.input, args.output, args.combine_fs, args.worker_num).run()


def run_check_apk(args: argparse.Namespace) -> int:
    APK.read_apk(args.input)  # read_apk validates and raises on violations
    return 0


def run_check_idx(args: argparse.Namespace) -> int:
    idx = IDX.read_idx(args.input)  # validates the basic structure; raises on violations
    violations = idx.validate_detail(args.input.parent, args.base)
    raise_if_invalid(violations, IdxException)
    return 0


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

    # sub commend for apk checker
    apk_checker = sub_cmd.add_parser("validate-apk", help="Validate an apk file. This may not be perfect")
    apk_checker.add_argument("-i", "--input", type=Path, required=True, help="Path to the input apk file")
    apk_checker.set_defaults(handler=run_check_apk)

    # sub commend for idx checker
    idx_checker = sub_cmd.add_parser("validate-idx", help="Validate an idx file. This may not be perfect")
    idx_checker.add_argument("-i", "--input", type=Path, required=True, help="Path to the input idx file. The associated apk files are located automatically, relative to the location of the idx file")
    idx_checker.add_argument("-b", "--base", type=Path, required=False, help="Specifies the base path where the apk and idx files are located. See the documentation for details")
    idx_checker.set_defaults(handler=run_check_idx)

    args = parser.parse_args(argv)
    log_level = args.log or ("debug" if args.verbose else "info")  # -l/--log takes priority over -v/--verbose
    listener, _queue = setup_cli_logging(LOG_LEVELS[log_level], args.log_file)

    try:
        log.info(f"ymtools v{const.VERSION} by akio7624")
        if args.verbose and args.log not in (None, "debug"):
            log.warning(f"-v/--verbose is ignored because --log {args.log} is specified")
        if log_level == "debug":
            print_env(args)

        return args.handler(args)
    except ValidationException:
        return 1
    finally:
        listener.stop()
