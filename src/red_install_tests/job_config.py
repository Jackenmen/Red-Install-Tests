import dataclasses
import fnmatch
import json
import os
import platform
import shutil
import sys
from typing import Final, Literal, TypedDict

from typing_extensions import Self

from .image_location import ImageSpec
from .run_config import OS_MATRIX_FILENAME, RUN_CONFIG_FILENAME

JOB_CONFIG_FILENAME: Final = "job_config.json"
JOBS_DIR: Final = "jobs"
ShellType = Literal["shell", "windows-shell", "powershell"]


class CmdBlockDict(TypedDict):
    shell: ShellType
    commands: list[str]
    elevated: bool


class JobConfigDict(TypedDict):
    image_spec: ImageSpec
    install_instructions: list[CmdBlockDict]


@dataclasses.dataclass(kw_only=True)
class JobConfig:
    image_spec: ImageSpec
    install_instructions: list[CmdBlockDict]

    @classmethod
    def from_json_dict(cls, data: JobConfigDict) -> Self:
        return cls(
            image_spec=data["image_spec"], install_instructions=data["install_instructions"]
        )

    def to_json_dict(self) -> JobConfigDict:
        return {"image_spec": self.image_spec, "install_instructions": self.install_instructions}

    def can_run(self, *, allow_emulation: bool = True) -> bool:
        if not allow_emulation and self.image_spec["arch"] != get_host_architecture():
            return False
        return self.image_spec["os"] != "darwin" or sys.platform == "darwin"


def get_job_config(job_dir: str) -> JobConfig:
    with open(os.path.join(job_dir, JOB_CONFIG_FILENAME), encoding="utf-8") as fp:
        return JobConfig.from_json_dict(json.load(fp))


def create_jobs(
    *patterns: str, run_dir: str, jobs_dir: str | None = None, allow_emulation: bool = True
) -> None:
    with open(os.path.join(run_dir, OS_MATRIX_FILENAME), encoding="utf-8") as fp:
        os_matrix = json.load(fp)

    found_patterns = set()
    jobs = {}
    for job_config in map(JobConfig.from_json_dict, os_matrix):
        image_spec = job_config.image_spec
        name = image_spec["name"]
        if not job_config.can_run(allow_emulation=allow_emulation):
            continue
        if not patterns:
            jobs[name] = job_config
            continue
        for pat in patterns:
            if fnmatch.fnmatch(name, pat):
                jobs[name] = job_config
                found_patterns.add(pat)
    missing_patterns = set(patterns) - found_patterns
    if missing_patterns:
        raise ValueError(
            "Could not find images matching the following patterns in the OS matrix:"
            f" {', '.join(missing_patterns)}"
        )

    if jobs_dir is None:
        jobs_dir = os.path.join(run_dir, JOBS_DIR)
    for job_name, job_config in jobs.items():
        create_job(job_config, run_dir=run_dir, job_dir=os.path.join(jobs_dir, job_name))


def create_job(job_config: JobConfig, *, run_dir: str, job_dir: str) -> None:
    os.makedirs(job_dir, exist_ok=True)
    with open(os.path.join(job_dir, JOB_CONFIG_FILENAME), "w", encoding="utf-8") as fp:
        json.dump(job_config.to_json_dict(), fp, separators=(",", ":"))

    if not os.path.samefile(run_dir, job_dir):
        for filename in (OS_MATRIX_FILENAME, RUN_CONFIG_FILENAME):
            shutil.copyfile(os.path.join(run_dir, filename), os.path.join(job_dir, filename))


def get_host_architecture() -> str:
    machine = platform.machine().lower()
    if machine == "amd64":
        return "x86_64"
    if machine == "arm64":
        return "aarch64"
    return machine
