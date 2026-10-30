import argparse
import os
from pathlib import Path

from ymtools.src import const
from ymtools.src.unpacker.unpack import Unpacker


def run_unpack(args: argparse.Namespace) -> int:
    return Unpacker(args.input, args.output, args.combine_fs, args.worker_num).run()


def main(argv: list[str] | None = None) -> int:
    # setup argparser
    parser = argparse.ArgumentParser(prog="ymtools", allow_abbrev=False, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-v", "--version", action="version", version=f"ymtools {const.VERSION}\nGitHub: {const.GITHUB_URL}")

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
    return args.handler(args)
