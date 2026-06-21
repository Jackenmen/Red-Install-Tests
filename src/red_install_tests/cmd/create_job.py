import argparse
import json
import os

from red_install_tests.cli import (
    add_job_dir_option,
    add_name_patterns_argument,
    add_run_dir_option,
    parser_spec,
    run,
)
from red_install_tests.job_config import JOBS_DIR, JobConfig, create_job, create_jobs
from red_install_tests.run_config import OS_MATRIX_FILENAME, get_run_config


@parser_spec
def setup_parser(parser: argparse.ArgumentParser, /) -> None:
    add_name_patterns_argument(parser)
    parser.add_argument("--skip-emulation", action="store_true")
    add_run_dir_option(parser)
    add_job_dir_option(parser)
    parser.set_defaults(func=main)


def main(args: argparse.Namespace, /) -> None:
    run_config = get_run_config(args.run_dir)
    patterns = args.patterns or run_config.patterns
    if len(patterns) == 1 and not any(c in patterns[0] for c in ("*", "?", "[")):
        job_name = patterns[0]
        with open(os.path.join(args.run_dir, OS_MATRIX_FILENAME), encoding="utf-8") as fp:
            os_matrix = json.load(fp)
        for job_config in map(JobConfig.from_json_dict, os_matrix):
            if job_config.image_spec["name"] == job_name:
                break
        else:
            raise ValueError("Could not find an image with the provided name in the OS matrix")

        create_job(
            job_config,
            run_dir=args.run_dir,
            job_dir=args.job_dir or os.path.join(args.run_dir, JOBS_DIR, job_name),
        )
        return

    create_jobs(
        *patterns,
        run_dir=args.run_dir,
        jobs_dir=args.job_dir,
        allow_emulation=not args.skip_emulation,
    )


if __name__ == "__main__":
    run(setup_parser())
