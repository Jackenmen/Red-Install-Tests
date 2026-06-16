import argparse
import os
from collections.abc import Callable
from typing import Any, Protocol

from .run_config import DEFAULT_RUN_DIR


class ParserSetupFunc(Protocol):
    def __call__(
        self, parser: argparse.ArgumentParser | None = None, /
    ) -> argparse.ArgumentParser: ...


def parser_spec(func: Callable[[argparse.ArgumentParser], Any]) -> ParserSetupFunc:
    def setup_parser(parser: argparse.ArgumentParser | None = None, /) -> argparse.ArgumentParser:
        if parser is None:
            parser = argparse.ArgumentParser()
        func(parser)
        return parser

    return setup_parser


def run(parser: argparse.ArgumentParser) -> None:
    args = parser.parse_args()
    args.func(args)


def add_run_dir_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-dir", "--rundir", default=DEFAULT_RUN_DIR)


def add_job_dir_option(parser: argparse.ArgumentParser, *, with_default: bool = False) -> None:
    parser.add_argument("--job-dir", "--jobdir", default=DEFAULT_RUN_DIR if with_default else None)


def add_deps_dir_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--deps-dir", "--depsdir", default=os.path.join(os.getcwd(), "deps"))
