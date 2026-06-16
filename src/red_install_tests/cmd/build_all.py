import argparse
import asyncio
import os
import sys
import traceback

from red_install_tests.cli import add_run_dir_option, parser_spec, run
from red_install_tests.job_config import JOBS_DIR


def positive_int(arg: str) -> int:
    try:
        x = int(arg)
    except ValueError:
        raise argparse.ArgumentTypeError("The argument has to be a number.") from None
    if x > 0:
        return x
    raise argparse.ArgumentTypeError("The argument has to be a positive integer.")


@parser_spec
def setup_parser(parser: argparse.ArgumentParser, /) -> None:
    add_run_dir_option(parser)
    parser.add_argument("--max-parallel-jobs", "-j", type=positive_int, default=1, nargs="*")
    parser.add_argument("extra_packer_args", nargs="*")
    parser.set_defaults(func=main)


async def _wait_for_process(
    proc: asyncio.subprocess.Process,
) -> tuple[asyncio.subprocess.Process, int]:
    return proc, await proc.wait()


async def _async_main(args: argparse.Namespace, /) -> None:
    job_dirs = [
        entry.path for entry in os.scandir(os.path.join(args.run_dir, JOBS_DIR)) if entry.is_dir()
    ]

    pending: set[asyncio.Task[tuple[asyncio.subprocess.Process, int]]] = set()

    max_parallel_jobs = args.max_parallel_jobs
    exit_code = 0
    for job_dir in job_dirs:
        while len(pending) >= max_parallel_jobs:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                try:
                    proc, returncode = task.result()
                except Exception as exc:
                    traceback.print_exception(exc)
                    returncode = 1
                if returncode:
                    exit_code = 1
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "red_install_tests.cmd.build",
            "--job-dir",
            job_dir,
            "--",
            *args.extra_packer_args,
        )
        pending.add(asyncio.create_task(_wait_for_process(proc)))

    raise SystemExit(exit_code)


def main(args: argparse.Namespace, /) -> None:
    asyncio.run(_async_main(args))


if __name__ == "__main__":
    run(setup_parser())
