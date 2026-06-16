import argparse
from typing import Protocol

from red_install_tests.cli import ParserSetupFunc

from . import (
    configure_run,
    download_red_repo,
)


class _CmdModule(Protocol):
    __name__: str
    setup_parser: ParserSetupFunc


def _add_parser(subparsers: argparse._SubParsersAction, module: _CmdModule) -> None:
    cmd_name = module.__name__.rsplit(".", 1)[-1].replace("_", "-")
    module.setup_parser(subparsers.add_parser(cmd_name))


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(required=True)

    _add_parser(subparsers, configure_run)
    _add_parser(subparsers, download_red_repo)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
