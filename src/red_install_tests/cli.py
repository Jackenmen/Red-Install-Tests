import argparse
from collections.abc import Callable
from typing import Any, Protocol


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
