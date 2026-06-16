import argparse
import os
import shutil
import tarfile
from io import BytesIO
from urllib.parse import urlsplit

import niquests

from red_install_tests.cli import add_run_dir_option, parser_spec, run
from red_install_tests.run_config import get_run_config

if not hasattr(tarfile, "data_filter"):
    raise RuntimeError("Current Python version does not support extraction filters!")


def top_level_dir_filter(member: tarfile.TarInfo, path: str, /) -> tarfile.TarInfo | None:
    ret = tarfile.data_filter(member, path)
    if ret is None:
        return ret
    _, _, ret.name = ret.name.partition("/")
    return ret


@parser_spec
def setup_parser(parser: argparse.ArgumentParser, /) -> None:
    add_run_dir_option(parser)
    parser.set_defaults(func=main)


def main(args: argparse.Namespace, /) -> None:
    run_config = get_run_config(args.run_dir)

    ref = run_config.ref
    if not ref:
        resp = niquests.head(f"{run_config.repo_url}/releases/latest", allow_redirects=True)
        resp.raise_for_status()
        latest_tag = urlsplit(resp.url or "").path.rsplit("/", 1)[1]
        ref = f"refs/tags/{latest_tag}"

    repo_dir = os.path.join(args.run_dir, "repos", "Red-DiscordBot")
    if os.path.exists(repo_dir):
        shutil.rmtree(repo_dir)

    r = niquests.get(f"{run_config.repo_url}/tarball/{ref}").raise_for_status()
    with tarfile.open(fileobj=BytesIO(r.content or b"")) as archive:
        setattr(archive, "extraction_filter", top_level_dir_filter)
        archive.extractall(repo_dir)


if __name__ == "__main__":
    run(setup_parser())
