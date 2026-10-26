import argparse
import hashlib
import lzma
import os
import shutil
import time

import pyhaul
import rich.progress
from platformdirs import user_cache_dir

from red_install_tests import http
from red_install_tests.cli import add_job_dir_option, parser_spec, run
from red_install_tests.image_location import DiskImageSpec
from red_install_tests.job_config import get_job_config

CHECKSUM_FILE_NAME = "checksum.txt"
CACHED_IMAGE_NAME = "system.img"


class ChecksumMismatchError(RuntimeError):
    def __init__(self, *, expected_hash: str, actual_hash: str) -> None:
        super().__init__(f"Mismatching checksum - expected {expected_hash}, got {actual_hash}")


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

    destination = os.path.join(cache_dir, CACHED_IMAGE_NAME)
    download_destination = f"{destination}.download.tmp"
    with (
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
        progress_task = progress.add_task("Downloading the image...")
        state = pyhaul.HaulState()
        content_length = image_spec["content_length_hint"] or 1

        def show_progress(state: pyhaul.HaulState) -> None:
            nonlocal content_length
            if state.reported_length:
                content_length = state.reported_length

            progress.update(progress_task, completed=state.valid_length, total=content_length)

        for attempt in range(1, 6):
            if attempt > 1:
                progress.update(
                    progress_task, description=f"Downloading the image (attempt {attempt})..."
                )
            wait = 0.0
            fail_reason = ""
            try:
                pyhaul.haul(
                    image_spec["url"],
                    http.session,
                    dest=download_destination,
                    state=state,
                    on_progress=show_progress,
                )
            except pyhaul.PartialHaulError as exc:
                if state.bytes_read == 0:
                    wait = min(2**attempt, 30)
                # else: retry immediately — connection works, just dropped
                fail_reason = exc.reason
            except pyhaul.UnexpectedStatusError as exc:
                wait = (
                    exc.retry_after_seconds
                    if exc.retry_after_seconds is not None
                    else min(2**attempt, 60)
                )
                fail_reason = exc.reason
                if not exc.is_transient:
                    raise
            else:
                break
            print(f"attempt {attempt}: {fail_reason}")
            if wait:
                time.sleep(wait)
        else:
            raise RuntimeError("download failed after 10 attempts")

        progress.update(progress_task, completed=content_length)

    with open(download_destination, "rb") as fp:
        h = hashlib.file_digest(fp, hash_name)

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
        raise ChecksumMismatchError(expected_hash=expected_hash, actual_hash=actual_hash)

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

    cached = False
    try:
        # Ruff thinks this doesn't use a context manager but it actually does
        # https://github.com/astral-sh/ruff/issues/8221
        fp = open(os.path.join(cache_dir, CHECKSUM_FILE_NAME), encoding="utf-8")  # noqa: SIM115
    except FileNotFoundError:
        pass
    else:
        with fp:
            cached_hash = fp.read().strip()
            if cached_hash == image_spec["checksum"] and os.path.isfile(cached_image):
                cached = True

    if not cached:
        try:
            _cache_image(image_spec, cache_dir)
        except ChecksumMismatchError as exc:
            print(str(exc))
            raise SystemExit(1) from None

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
