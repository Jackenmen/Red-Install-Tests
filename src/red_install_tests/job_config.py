import dataclasses
import json
import os
from typing import Final, Literal, TypedDict

from typing_extensions import Self

from .image_location import ImageSpec

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


def get_job_config(job_dir: str) -> JobConfig:
    with open(os.path.join(job_dir, JOB_CONFIG_FILENAME), encoding="utf-8") as fp:
        return JobConfig.from_json_dict(json.load(fp))
