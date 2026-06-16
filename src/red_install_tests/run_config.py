import dataclasses
import json
import os
from typing import Final, TypedDict

from typing_extensions import Self

RUN_CONFIG_FILENAME: Final = "run_config.json"
OS_MATRIX_FILENAME: Final = "os_matrix.json"
DEFAULT_RUN_DIR: Final = "os-build-run"
STABLE_PACKAGE_SPEC: Final = "Red-DiscordBot[postgres]"


class RunConfigDict(TypedDict):
    repo_url: str
    ref: str | None


@dataclasses.dataclass(kw_only=True)
class RunConfig:
    repo_url: str
    ref: str | None

    @classmethod
    def from_json_dict(cls, data: RunConfigDict) -> Self:
        return cls(repo_url=data["repo_url"], ref=data["ref"])

    def to_json_dict(self) -> RunConfigDict:
        return {"repo_url": self.repo_url, "ref": self.ref}

    @property
    def pinned_tag(self) -> str | None:
        if self.ref and self.ref.startswith("refs/tags/"):
            return self.ref[len("refs/tags/") :]
        return None

    @property
    def package_spec(self) -> str:
        if self.ref is None:
            return STABLE_PACKAGE_SPEC
        if self.pinned_tag:
            return f"{STABLE_PACKAGE_SPEC}=={self.pinned_tag}"
        return f"{STABLE_PACKAGE_SPEC} @ {self.repo_url}/tarball/{self.ref}"


def get_run_config(job_or_run_dir: str = DEFAULT_RUN_DIR) -> RunConfig:
    with open(os.path.join(job_or_run_dir, RUN_CONFIG_FILENAME), encoding="utf-8") as fp:
        return RunConfig.from_json_dict(json.load(fp))
