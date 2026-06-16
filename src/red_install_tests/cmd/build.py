import argparse
import os
import subprocess

from red_install_tests.cli import add_job_dir_option, parser_spec, run


@parser_spec
def setup_parser(parser: argparse.ArgumentParser, /) -> None:
    add_job_dir_option(parser)
    parser.add_argument("extra_packer_args", nargs="*")
    parser.set_defaults(func=main)


def main(args: argparse.Namespace, /) -> None:
    job_dir = os.path.abspath(args.job_dir)
    build_dir = os.path.join(job_dir, "packer-build")

    subprocess.check_call(("packer", "init", build_dir))

    env = os.environ.copy()
    env["PACKER_LOG"] = "1"
    env["PACKER_LOG_PATH"] = os.path.join(build_dir, "packer.log")
    try:
        cp = subprocess.run(("packer", "build", *args.extra_packer_args, build_dir), env=env)
    except KeyboardInterrupt:
        raise SystemExit(2) from None

    raise SystemExit(cp.returncode)


if __name__ == "__main__":
    run(setup_parser())
