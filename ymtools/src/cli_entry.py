import argparse
import logging
import os
import platform
import sys
from pathlib import Path

from ymtools.src import const
from ymtools.src.apkidx.idxgen.exceptions import IdxGenException
from ymtools.src.apkidx.idxgen.gen import IdxGenerator
from ymtools.src.apkidx.packer.exceptions import PackerException
from ymtools.src.apkidx.packer.pack import Packer
from ymtools.src.apkidx.structure import raise_if_invalid
from ymtools.src.apkidx.structure.apk import APK
from ymtools.src.apkidx.structure.exceptions import IdxException, ValidationException
from ymtools.src.apkidx.structure.idx import IDX
from ymtools.src.apkidx.unpacker.unpack import Unpacker
from ymtools.src.gop.dumper import GopDumper
from ymtools.src.gop.exceptions import GopDumpException
from ymtools.src.gop.patcher import GopPatcher
from ymtools.src.logger import setup_cli_logging

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


def run_apk_unpack(args: argparse.Namespace) -> int:
    return Unpacker(args.input, args.output, args.worker_num).run()


def run_apk_pack(args: argparse.Namespace) -> int:
    return Packer(args.input, args.output).run()


def run_apk_idxgen(args: argparse.Namespace) -> int:
    return IdxGenerator(args.input, args.output).run()


def run_apk_check_apk(args: argparse.Namespace) -> int:
    APK.read_apk(args.input)  # read_apk validates and raises on violations
    return 0


def run_apk_check_idx(args: argparse.Namespace) -> int:
    idx = IDX.read_idx(args.input)  # validates the basic structure; raises on violations
    violations = idx.validate_detail(args.input.parent, args.base)
    raise_if_invalid(violations, IdxException)
    return 0


def run_gop_dump(args: argparse.Namespace) -> int:
    return GopDumper(args.input, args.output, args.format).run()


def run_gop_patch_xlsx(args: argparse.Namespace) -> int:
    return GopPatcher(args.txt, args.xlsx, args.output).run()


def run_gop_gen(args: argparse.Namespace) -> int:
    # TODO
    return 0


def run_gop_check(args: argparse.Namespace) -> int:
    # TODO
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
    unpack = sub_cmd.add_parser("apk-unpack", help="Unpack an apk file")
    unpack.add_argument("-i", "--input", type=Path, required=True, help="Path to the input apk file")
    unpack.add_argument("-o", "--output", type=Path, required=True, help="Directory to extract files into")
    unpack.add_argument("-w", "--worker-num", type=int, default=2, help="Number of worker processes (default: %(default)s)")
    unpack.set_defaults(handler=run_apk_unpack)

    # sub commend for packer
    pack = sub_cmd.add_parser("apk-pack", help="Pack a directory into a single apk file")
    pack.add_argument("-i", "--input", type=Path, required=True, help="Path to the source directory. It must have the same layout as the output of the unpack command")
    pack.add_argument("-o", "--output", type=Path, required=True, help="Path to the output apk file")
    pack.set_defaults(handler=run_apk_pack)

    # sub commend for idx generator
    idxgen = sub_cmd.add_parser("idx-gen", help="Generate an idx file from apk files")
    idxgen.add_argument("-i", "--input", type=Path, nargs="+", required=True, help="Paths to the input apk files. They are merged into one idx file")
    idxgen.add_argument("-o", "--output", type=Path, required=True, help="Path to the output idx file")
    idxgen.set_defaults(handler=run_apk_idxgen)

    # sub commend for apk checker
    apk_checker = sub_cmd.add_parser("validate-apk", help="Validate an apk file. This may not be perfect")
    apk_checker.add_argument("-i", "--input", type=Path, required=True, help="Path to the input apk file")
    apk_checker.set_defaults(handler=run_apk_check_apk)

    # sub commend for idx checker
    idx_checker = sub_cmd.add_parser("validate-idx", help="Validate an idx file. This may not be perfect")
    idx_checker.add_argument("-i", "--input", type=Path, required=True, help="Path to the input idx file. The associated apk files are located automatically, relative to the location of the idx file")
    idx_checker.add_argument("-b", "--base", type=Path, required=False, help="Specifies the base path where the apk and idx files are located. See the documentation for details")
    idx_checker.set_defaults(handler=run_apk_check_idx)

    # sub commend for gop dumper
    gop_dump = sub_cmd.add_parser("gop-dump", help="Dump a gop file into xlsx and txt files")
    gop_dump.add_argument("-i", "--input", type=Path, required=True, help="Path to the input gop file")
    gop_dump.add_argument("-o", "--output", type=Path, required=True, help="Directory to write the files into. The file names are the same as the gop file. If --format is given, it may be the path of the output file instead")
    gop_dump.add_argument("-f", "--format", choices=["xlsx", "txt"], default=None, help="Dump only this format (default: both xlsx and txt). Only xlsx can be used with gop-gen")
    gop_dump.set_defaults(handler=run_gop_dump)

    # sub commend for patching xlsx with txt
    patch_xlsx = sub_cmd.add_parser("patch-xlsx", help="Patch the values of an xlsx file created by gop-dump with an edited txt file")
    patch_xlsx.add_argument("-x", "--xlsx", type=Path, required=True, help="Path to the xlsx file to patch")
    patch_xlsx.add_argument("-t", "--txt", type=Path, required=True, help="Path to the txt file created by gop-dump. Its columns and record count must be the same as the xlsx file")
    patch_xlsx.add_argument("-o", "--output", type=Path, required=False, help="Path to the output xlsx file (default: overwrite the input xlsx file)")
    patch_xlsx.set_defaults(handler=run_gop_patch_xlsx)

    # sub commend for gop generator
    gop_gen = sub_cmd.add_parser("gop-gen", help="Generate a gop file from an xlsx file created by gop-dump")
    gop_gen.add_argument("-i", "--input", type=Path, required=True, help="Path to the input xlsx file")
    gop_gen.add_argument("-o", "--output", type=Path, required=True, help="Path to the output gop file")
    gop_gen.set_defaults(handler=run_gop_gen)

    # sub commend for gop checker
    gop_checker = sub_cmd.add_parser("validate-gop", help="Validate a gop file. This may not be perfect")
    gop_checker.add_argument("-i", "--input", type=Path, required=True, help="Path to the input gop file")
    gop_checker.set_defaults(handler=run_gop_check)

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
    except (PackerException, IdxGenException, GopDumpException) as e:
        log.error(str(e))
        return 1
    finally:
        listener.stop()
