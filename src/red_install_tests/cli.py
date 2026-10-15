import argparse
import contextlib
import os
from collections.abc import Callable, Generator
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


def add_name_patterns_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("patterns", metavar="pattern", nargs="*")


def positive_int(arg: str) -> int:
    try:
        x = int(arg)
    except ValueError:
        raise argparse.ArgumentTypeError("The argument has to be a number.") from None
    if x > 0:
        return x
    raise argparse.ArgumentTypeError("The argument has to be a positive integer.")


def is_github_actions_ci() -> bool:
    return os.getenv("GITHUB_ACTIONS") == "true"


@contextlib.contextmanager
def log_group(title: str) -> Generator[None]:
    if is_github_actions_ci():
        print(f"::group::{title}", flush=True)
    try:
        yield
    finally:
        if is_github_actions_ci():
            print("::endgroup::", flush=True)
