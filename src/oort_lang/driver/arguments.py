#! /usr/bin/env python

import argparse
from collections.abc import Sequence

from .. import __version__

COMPILER_MODE_HELPS = {
    "ast": "Print AST.",
    "astm": "Print AST with metadata.",
    "bc": "Compile to bytecode and print disassembly.",
    "eval": "Evaluate the AST (default).",
}


def get_main_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Oort compiler.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("input_file", nargs="?", help="Input filename")
    parser.add_argument(
        "script_args",
        nargs="*",
        metavar="ARG",
        help="Arguments passed to the Oort program (os.args)",
    )
    parser.add_argument("--version", action="version", version=f"Oort {__version__}")
    parser.add_argument(
        "-l",
        "--logging-level",
        type=str,
        default="WARNING",
        help="Logging level, default to %(default)r",
    )

    _help_strs = ["Output target format, default to %(default)r"]
    for mode, help_str in COMPILER_MODE_HELPS.items():
        _help_strs.append(f"- {mode}: {help_str}")
    parser.add_argument(
        "-t",
        "--target",
        type=str,
        default="eval",
        choices=list(COMPILER_MODE_HELPS),
        help="\n".join(_help_strs),
    )
    parser.add_argument(
        "-c",
        "--cmd",
        type=str,
        default=None,
        help="Program passed in as string",
    )
    parser.add_argument(
        "-I",
        "--module-path",
        action="append",
        default=[],
        metavar="DIR",
        help=(
            "Add DIR to the module search path (repeatable).\n"
            "Unlike Python's -I, this does not enable isolated mode."
        ),
    )

    return parser


def parse_main_args(
    parser: argparse.ArgumentParser, argv: str | Sequence[str] | None = None
) -> argparse.Namespace:
    if argv is None:
        arg_list = None
    elif isinstance(argv, str):
        arg_list = argv.split()
    else:
        arg_list = list(argv)
    args = parser.parse_args(arg_list)
    args.logging_level = args.logging_level.upper()

    if args.cmd is not None and args.input_file is not None:
        # argparse cannot distinguish `-c CODE ARG...`: a positional after
        # `-c` lands in `input_file`. Treat it (and the rest) as program args.
        args.script_args.insert(0, args.input_file)
        args.input_file = None

    return args
