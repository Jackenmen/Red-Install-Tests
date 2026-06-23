import argparse
import hashlib
import lzma
import os
import shutil

import niquests
import rich.progress
from platformdirs import user_cache_dir

from red_install_tests import http
from red_install_tests.cli import add_job_dir_option, parser_spec, run
from red_install_tests.image_location import DiskImageSpec
from red_install_tests.job_config import get_job_config

CHECKSUM_FILE_NAME = "checksum.txt"
CACHED_IMAGE_NAME = "system.img"


@parser_spec
def setup_parser(parser: argparse.ArgumentParser, /) -> None:
    parser.add_argument("destination")
    add_job_dir_option(parser, with_default=True)
    parser.set_defaults(func=main)


def _cache_image(image_spec: DiskImageSpec, cache_dir: str) -> None:
    checksum_file = os.path.join(cache_dir, CHECKSUM_FILE_NAME)
    if os.path.isdir(checksum_file):
        shutil.rmtree(checksum_file)
    else:
        try:
            os.remove(checksum_file)
        except FileNotFoundError:
            pass
    os.makedirs(cache_dir, exist_ok=True)

    hash_name, _, expected_hash = image_spec["checksum"].partition(":")
    h = hashlib.new(hash_name)

    destination = os.path.join(cache_dir, CACHED_IMAGE_NAME)
    download_destination = f"{destination}.download.tmp"
    with (
        open(download_destination, "wb") as fp,
        rich.progress.Progress(
            rich.progress.TextColumn("[bold blue]{task.description}", justify="right"),
            rich.progress.BarColumn(bar_width=None),
            "[progress.percentage]{task.percentage:>3.1f}%",
            "•",
            rich.progress.DownloadColumn(),
            "•",
            rich.progress.TransferSpeedColumn(),
            "•",
            rich.progress.TimeRemainingColumn(),
        ) as progress,
    ):
        r = http.get(image_spec["url"], stream=True)
        # download progress requires content length but it is not always present
        content_length = int(
            r.headers.get("content-length")
            or http.head(image_spec["url"], allow_redirects=True).headers["content-length"]
        )
        progress_task = progress.add_task("Downloading the image...")
        for chunk in r.iter_content():
            if r.download_progress is None:
                r.download_progress = niquests.models.TransferProgress()
            fp.write(chunk)
            h.update(chunk)
            progress.update(
                progress_task,
                completed=r.download_progress.total,
                total=content_length,
            )
        progress.update(progress_task, completed=content_length)

    _, _, compression = image_spec["image_format"].partition("+")
    if not compression:
        uncompressed_destination = download_destination
    elif compression == "xz":
        uncompressed_destination = f"{destination}.tmp"
        with lzma.open(download_destination) as src, open(uncompressed_destination, "wb") as dst:
            shutil.copyfileobj(src, dst)
        os.remove(download_destination)
    else:
        raise RuntimeError("unexpected compression type")

    actual_hash = h.hexdigest()
    if actual_hash != expected_hash:
        raise RuntimeError(f"Mismatching checksum - expected {expected_hash}, got {actual_hash}")

    os.replace(uncompressed_destination, destination)
    with open(checksum_file, "w", encoding="utf-8") as fp:
        fp.write(f"{image_spec['checksum']}\n")

    print("Image downloaded and verified.")


def main(args: argparse.Namespace, /) -> None:
    job_config = get_job_config(args.job_dir)
    image_spec = job_config.image_spec

    if image_spec["spec_type"] != "disk":
        raise ValueError("This is not a downloadable image!")

    cache_dir = os.path.join(
        user_cache_dir("Red-Install-Tests", appauthor=False), image_spec["name"]
    )
    cached_image = os.path.join(cache_dir, CACHED_IMAGE_NAME)

    try:
        # Ruff thinks this doesn't use a context manager but it actually does
        # https://github.com/astral-sh/ruff/issues/8221
        fp = open(os.path.join(cache_dir, CHECKSUM_FILE_NAME), encoding="utf-8")  # noqa: SIM115
    except FileNotFoundError:
        _cache_image(image_spec, cache_dir)
    else:
        with fp:
            cached_hash = fp.read().strip()
            if cached_hash != image_spec["checksum"] or not os.path.isfile(cached_image):
                _cache_image(image_spec, cache_dir)

    destination = os.path.abspath(args.destination)
    try:
        os.link(cached_image, destination)
    except OSError:
        try:
            os.symlink(cached_image, destination)
        except OSError:
            shutil.copyfile(cached_image, destination)

    print("Image ready.")


if __name__ == "__main__":
    run(setup_parser())
