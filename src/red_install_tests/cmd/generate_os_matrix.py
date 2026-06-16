import argparse
import itertools
import json
import os
import subprocess
import sys
import sysconfig
import tempfile
from typing import Any, Final

from red_install_tests.cli import add_run_dir_option, parser_spec, run
from red_install_tests.image_location import generate_image_spec
from red_install_tests.job_config import CmdBlockDict, JobConfig, ShellType
from red_install_tests.run_config import OS_MATRIX_FILENAME

_LANGUAGE_TO_SHELL: Final[dict[str, ShellType]] = {
    "bash": "shell",
    "batch": "windows-shell",
    "powershell": "powershell",
}


def _get_scripts_dir(venv_dir: str) -> str:
    if sys.version_info >= (3, 11):
        return sysconfig.get_path(
            "scripts", scheme="venv", vars={"base": venv_dir, "platbase": venv_dir}
        )
    if sys.platform == "win32":
        return os.path.join(venv_dir, "Scripts")
    return os.path.join(venv_dir, "bin")


def prompt_has_modifier(prompt: dict[str, Any], modifier: str):
    if modifier.endswith("-"):
        return any(m.startswith(modifier) for m in prompt["modifiers"])
    return any(m == modifier for m in prompt["modifiers"])


@parser_spec
def setup_parser(parser: argparse.ArgumentParser, /) -> None:
    add_run_dir_option(parser)
    parser.set_defaults(func=main)


def _process_prompts(prompts: list[dict[str, Any]]) -> list[CmdBlockDict]:
    install_instructions = []
    for (language, elevated), cmd_block_prompts in itertools.groupby(
        prompts,
        key=lambda p: (
            p["language"],
            prompt_has_modifier(p, "red-install-guide-elevated"),
        ),
    ):
        commands: list[str] = []
        cmd_block: CmdBlockDict = {
            "shell": _LANGUAGE_TO_SHELL[language],
            "commands": commands,
            "elevated": elevated,
        }
        package_spec_ref = {
            "bash": '"$RED_PACKAGE_SPEC"',
            "batch": '"%RED_PACKAGE_SPEC%"',
            "powershell": '"$env:RED_PACKAGE_SPEC"',
        }[language]
        for prompt in cmd_block_prompts:
            if prompt_has_modifier(prompt, "red-install-guide-install-normal"):
                commands.extend(
                    line.replace("Red-DiscordBot", package_spec_ref)
                    for line in prompt["content"].splitlines()
                )
                continue
            if prompt_has_modifier(prompt, "red-install-guide-setup"):
                continue
            if prompt_has_modifier(prompt, "red-install-guide-run"):
                continue
            commands.extend(prompt["content"].splitlines())
        _process_commands(commands)
        install_instructions.append(cmd_block)

    return install_instructions


def _process_commands(commands: list[str]) -> None:
    per_program_extra_args = {
        "makepkg": "--noconfirm",
        "pacman": "--noconfirm",
    }
    for idx, command in enumerate(commands):
        split_command = command.split(" ", 2)
        prefix = program = split_command[0]
        if program == "sudo" and len(split_command) > 1:
            program = split_command[1]
            prefix = " ".join(split_command[:2])
        extra_args = per_program_extra_args.get(program)
        if extra_args:
            commands[idx] = f"{prefix} {extra_args}{command[len(prefix) :]}"


def main(args: argparse.Namespace, /) -> None:
    red_repo_dir = os.path.join(args.run_dir, "repos", "Red-DiscordBot")
    matrix = []
    with tempfile.TemporaryDirectory() as tmpdirname:
        venv_dir = os.path.join(tmpdirname, "venv")
        subprocess.check_call((sys.executable, "-m", "venv", venv_dir))
        scripts_dir = _get_scripts_dir(venv_dir)
        venv_python = os.path.join(scripts_dir, "python" + sysconfig.get_config_var("EXE"))
        subprocess.check_call((venv_python, "-m", "pip", "install", "-U", "pip"))
        subprocess.check_call((venv_python, "-m", "pip", "install", f"{red_repo_dir}/.[doc]"))
        build_dir = os.path.join(tmpdirname, "build")
        subprocess.check_call(
            (
                venv_python,
                "-m",
                "sphinx",
                "-M",
                "jsonprompt",
                os.path.join(red_repo_dir, "docs"),
                build_dir,
            )
        )
        for entry in os.scandir(os.path.join(build_dir, "jsonprompt", "install_guides")):
            if not entry.is_file():
                continue
            with open(entry.path, encoding="utf-8") as fp:
                data = json.load(fp)

            if not data.get("os_image_locations"):
                continue

            install_instructions = _process_prompts(data["prompts"])
            for image_name, location in data["os_image_locations"].items():
                print(f"Processing {image_name} image...")
                location["name"] = image_name
                spec = generate_image_spec(location)
                job_config = JobConfig(image_spec=spec, install_instructions=install_instructions)
                matrix.append(job_config.to_json_dict())

        with open(os.path.join(args.run_dir, OS_MATRIX_FILENAME), "w", encoding="utf-8") as fp:
            json.dump(matrix, fp, separators=(",", ":"))


if __name__ == "__main__":
    run(setup_parser())
