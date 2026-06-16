import argparse
import json
import os

from red_install_tests.cli import add_run_dir_option, parser_spec, run
from red_install_tests.run_config import RUN_CONFIG_FILENAME, RunConfig


@parser_spec
def setup_parser(parser: argparse.ArgumentParser, /) -> None:
    add_run_dir_option(parser)
    parser.add_argument("--repo", default="Cog-Creators/Red-DiscordBot")
    ref_group = parser.add_mutually_exclusive_group()
    ref_group.add_argument("--branch", default="")
    ref_group.add_argument("--version", default="")
    ref_group.add_argument("--pull-request", "--pull", "--pr", default="")
    parser.set_defaults(func=main)


def main(args: argparse.Namespace, /) -> None:
    repo_url = f"https://github.com/{args.repo}"
    ref = None
    if args.branch:
        ref = f"refs/heads/{args.branch}"
    elif args.version:
        ref = f"refs/tags/{args.version}"
    elif args.pull_request:
        ref = f"refs/pull/{args.pull_request}/merge"
    run_config = RunConfig(repo_url=repo_url, ref=ref)

    os.makedirs(args.run_dir, exist_ok=True)
    with open(os.path.join(args.run_dir, RUN_CONFIG_FILENAME), "w", encoding="utf-8") as fp:
        json.dump(run_config.to_json_dict(), fp, separators=(",", ":"))


if __name__ == "__main__":
    run(setup_parser())
