import argparse
import os
import re
import shutil
import subprocess
import sys
import time

from red_install_tests.cli import add_job_dir_option, log_group, parser_spec, positive_int, run
from red_install_tests.job_config import get_job_config


def _compile_pattern(pattern: bytes) -> re.Pattern[bytes]:
    return re.compile(
        b"".join(
            line for line in map(bytes.lstrip, pattern.splitlines()) if not line.startswith(b"#")
        )
    )


ANSI_CODES_PATTERN = re.compile(rb"(?i)\x1b\[([0-9]{1,2}(;[0-9]{1,2})?)?[a|b|m|k]")
TRANSIENT_ERROR_PATTERN = _compile_pattern(
    rb"""
    # timestamp
    ^\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2} (
        # install command transient errors
        ui error: ==> (
            windows-([a-z0-9\-]+)\.[a-z]+\.tests:
            \ The system cannot find the path specified\.$
            |((alma|amazon|oracle|rocky)-linux|centos|fedora)-([a-z0-9\-]+)\.[a-z]+\.tests:
            \  +- (
                nothing provides .+ needed by .+ from .+$
                |Curl error \((6|7|28|35|55|56)\):
            )
            |fedora-([a-z0-9\-]+)\.[a-z]+\.tests:
            \ >>> Status code: 503 for https://packages\.adoptium\.net
            |opensuse-tumbleweed-([a-z0-9\-]+)\.[a-z]+\.tests:
            \ Repository 'openSUSE-Tumbleweed-Oss' is invalid\.
            |(debian|ubuntu)-([a-z0-9\-]+)\.[a-z]+\.tests: (
                E: .+ Mirror sync in progress\?
                |W: Failed to fetch .+  50[023]  ([A-Za-z]+ )+\[IP: \d+(\.\d+){3} \d+\]$
                |lazr\.restfulclient\.errors\.ServerError: HTTP Error 500
            )
        )
    )
    """
)
PACKER_INIT_TRANSIENT_ERROR_PATTERN = re.compile(
    r"    \* could not get sha256 checksum file for [^ ]+\."
    r" Is the file present on the release and correctly named \?"
    r" GET https://[^ ]+_SHA256SUMS: (500|502|503|504) "
)


@parser_spec
def setup_parser(parser: argparse.ArgumentParser, /) -> None:
    add_job_dir_option(parser)
    parser.add_argument("--attempts", type=positive_int, default=1)
    parser.add_argument("extra_packer_args", nargs="*")
    parser.set_defaults(func=main)


def main(args: argparse.Namespace, /) -> None:
    job_dir = os.path.abspath(args.job_dir)
    job_config = get_job_config(job_dir)
    build_dir = os.path.join(job_dir, "packer-build")

    env = os.environ.copy()
    qemu_bin = os.path.join(os.path.dirname(sys.executable), "_red-install-tests-run-qemu")
    if sys.platform == "win32":
        qemu_bin += ".exe"
    env["RED_INSTALL_TESTS_PYTHON"] = sys.executable
    env["RED_INSTALL_TESTS_QEMU"] = qemu_bin
    env["RED_INSTALL_TESTS_ARCHITECTURE"] = job_config.image_spec["arch"]

    for attempt in range(1, 4):
        cp = subprocess.run(
            ("packer", "init", build_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        print(cp.stdout, flush=True)
        if not cp.returncode:
            break
        if not PACKER_INIT_TRANSIENT_ERROR_PATTERN.search(cp.stdout):
            print("Failure does not seem to be due to a transient error, will not retry.")
            raise SystemExit(cp.returncode)
        time.sleep(2**attempt)
    else:
        raise SystemExit(cp.returncode)

    env["PACKER_LOG"] = "1"
    for attempt in range(1, args.attempts + 1):
        log_file = os.path.join(build_dir, f"packer-{attempt}.log")
        env["RED_INSTALL_TESTS_ATTEMPT"] = str(attempt)
        env["RED_INSTALL_TESTS_SCREENCAST_PATH"] = os.path.join(build_dir, f"screen-{attempt}.mkv")
        env["PACKER_LOG_PATH"] = log_file
        with log_group(f"Build {job_config.image_spec['name']} - attempt {attempt}"):
            try:
                cp = subprocess.run(
                    ("packer", "build", "-force", *args.extra_packer_args, build_dir), env=env
                )
            except KeyboardInterrupt:
                raise SystemExit(2) from None
            finally:
                # sometimes Packer doesn't cleanup its output directory, let's do it ourselves
                output_dir = os.path.join(build_dir, "output")
                if os.path.exists(output_dir):
                    shutil.rmtree(output_dir)

            if not cp.returncode:
                break

            print(f"=== Attempt {attempt} failed with exit code {cp.returncode} ===")

            with open(log_file, "rb") as fp:
                for line in fp:
                    if TRANSIENT_ERROR_PATTERN.search(ANSI_CODES_PATTERN.sub(b"", line)):
                        break
                else:
                    print("Failure does not seem to be due to a transient error, will not retry.")
                    break

            if attempt != args.attempts:
                wait = 2**attempt
                print(f"Retrying in {wait} seconds...")
                time.sleep(wait)

        if attempt != args.attempts:
            print(f"=== Attempt {attempt + 1} ===")

    raise SystemExit(cp.returncode)


if __name__ == "__main__":
    run(setup_parser())
