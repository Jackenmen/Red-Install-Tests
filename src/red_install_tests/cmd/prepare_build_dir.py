import argparse
import base64
import importlib.abc
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from typing import Any
from urllib.request import pathname2url

import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from red_install_tests.cli import add_deps_dir_option, parser_spec, run
from red_install_tests.image_location import DiskImageSpec, ImageSpec, TartImageSpec
from red_install_tests.job_config import JOBS_DIR, JobConfig, get_job_config
from red_install_tests.resources import RESOURCES
from red_install_tests.run_config import DEFAULT_RUN_DIR, RunConfig, get_run_config


def chmod_opener(mode: int) -> Callable[[str, int], int]:
    def opener(path: str, flags: int) -> int:
        return os.open(path, flags, mode)

    return opener


def _generate_ssh_key(build_dir: str) -> tuple[str, str]:
    private_key = Ed25519PrivateKey.generate()
    key_path = os.path.join(build_dir, "ssh.key")
    with open(key_path, "wb", opener=chmod_opener(0o600)) as fp:
        fp.write(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.OpenSSH,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
    public_key = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.OpenSSH,
            format=serialization.PublicFormat.OpenSSH,
        )
        .decode()
    )
    with open(f"{key_path}.pub", "w", encoding="utf-8") as fp:
        fp.write(f"{public_key}\n")
    return key_path, public_key


def _generate_cloud_init(public_key: str) -> dict[str, str]:
    user_data = {
        "users": [
            "default",
            {
                "name": "packer",
                "sudo": "ALL=(ALL) NOPASSWD:ALL",
                "shell": "/bin/bash",
                "ssh_authorized_keys": [public_key],
            },
        ],
    }
    return {"user-data": f"#cloud-config\n{yaml.dump(user_data)}", "meta-data": ""}


def _write_resource_contents(src: importlib.abc.Traversable, target_dir: str) -> str:
    child = f"{target_dir}/{src.name}"
    if src.is_dir():
        os.mkdir(child)
        for item in src.iterdir():
            _write_resource_contents(item, child)
    else:
        with src.open("rb") as fsrc, open(child, "wb") as fdst:
            shutil.copyfileobj(fsrc, fdst)
    return child


def _copy_resource(src: str, target_dir: str) -> str:
    path = RESOURCES
    for path_segment in src.split("/"):
        path /= path_segment

    return _write_resource_contents(path, target_dir)


class BuildDirGenerator:
    def __init__(
        self, run_config: RunConfig, job_config: JobConfig, job_dir: str, *, deps_dir: str
    ) -> None:
        self.run_config = run_config
        self.job_config = job_config
        self.job_dir = job_dir
        self.deps_dir = deps_dir
        self.build_dir = os.path.join(self.job_dir, "packer-build")
        self.packer_vars: dict[str, Any] = {
            "build_name": self.image_spec["name"],
            "red_install_instructions": job_config.install_instructions,
            "red_package_spec": run_config.package_spec,
            "red_expected_java_version": self.image_spec["expected_java_version"],
            "os": self.image_spec["os"],
        }

    @property
    def image_spec(self) -> ImageSpec:
        return self.job_config.image_spec

    def prepare(self) -> None:
        _copy_resource("packer/common.pkr.hcl", self.build_dir)
        _copy_resource("tests", self.build_dir)

    def save_packer_vars(self) -> None:
        packer_vars_file = os.path.join(self.build_dir, "config.auto.pkrvars.json")
        with open(packer_vars_file, "w", encoding="utf-8") as fp:
            json.dump(self.packer_vars, fp, indent=4)


class QemuBuildDirGenerator(BuildDirGenerator):
    def __init__(
        self, run_config: RunConfig, job_config: JobConfig, job_dir: str, *, deps_dir: str
    ) -> None:
        super().__init__(run_config, job_config, job_dir, deps_dir=deps_dir)
        self.image_path = os.path.join(self.build_dir, "system.img")
        self.key_path = ""
        self.public_key = ""

    @property
    def image_spec(self) -> DiskImageSpec:
        image_spec = self.job_config.image_spec
        assert image_spec["spec_type"] == "disk"
        return image_spec

    def prepare(self) -> None:
        super().prepare()
        self.key_path, self.public_key = _generate_ssh_key(self.build_dir)

        _copy_resource("packer/qemu.pkr.hcl", self.build_dir)
        subprocess.check_call(
            (
                sys.executable,
                "-m",
                "red_install_tests.cmd.download_image",
                self.image_path,
                "--job-dir",
                self.job_dir,
            )
        )
        image_format, _, _ = self.image_spec["image_format"].partition("+")
        self.packer_vars["use_backing_file"] = image_format == "qcow2"
        self.packer_vars["iso_url"] = f"file://{pathname2url(self.image_path)}"
        self.packer_vars["output_directory"] = os.path.join(self.build_dir, "output")
        self.packer_vars["ssh_private_key_file"] = self.key_path
        self.packer_vars["architecture"] = self.image_spec["arch"]
        self.packer_vars["machine_type"] = self.image_spec["machine_type"]

        is_x86 = self.image_spec["arch"] == "x86_64"
        edk2_dir = os.path.join(self.deps_dir, "edk2")
        match self.image_spec["boot_mode"]:
            case "bios":
                self.packer_vars["efi_firmware_code"] = ""
                self.packer_vars["efi_firmware_vars"] = ""
            case "uefi":
                self.packer_vars["efi_firmware_code"] = os.path.join(
                    edk2_dir, "OVMF_CODE_4M.fd" if is_x86 else "AAVMF_CODE.fd"
                )
                self.packer_vars["efi_firmware_vars"] = os.path.join(
                    edk2_dir, "OVMF_VARS_4M.fd" if is_x86 else "AAVMF_VARS.fd"
                )
            case "uefi-secure-boot":
                self.packer_vars["efi_firmware_code"] = os.path.join(
                    edk2_dir, "OVMF_CODE_4M.secboot.fd" if is_x86 else "AAVMF_CODE.ms.fd"
                )
                self.packer_vars["efi_firmware_vars"] = os.path.join(
                    edk2_dir, "OVMF_VARS_4M.ms.fd" if is_x86 else "AAVMF_VARS.ms.fd"
                )

        self._prepare_system_specific_config()

    def _prepare_system_specific_config(self) -> None:
        match self.image_spec["os"]:
            case "linux":
                self._prepare_linux_specific_config()
            case "windows":
                self._prepare_windows_specific_config()

    def _prepare_linux_specific_config(self) -> None:
        cloud_init_files = _generate_cloud_init(self.public_key)
        self.packer_vars["http_content"] = {
            f"/{filename}": content for filename, content in cloud_init_files.items()
        }
        self.packer_vars["cd_content"] = cloud_init_files
        if self.image_spec["machine_type"] == "raspi3b":
            self._prepare_linux_raspi3b_specific_config()

    def _prepare_linux_raspi3b_specific_config(self) -> None:
        subprocess.check_call(
            (
                sys.executable,
                "-m",
                "red_install_tests.cmd.prepare_raspi_img",
                self.image_path,
                self.build_dir,
            )
        )
        network_config = {
            "version": 2,
            "ethernets": {
                "default": {
                    "match": {
                        "name": "en*",
                    },
                    "dhcp4": True,
                },
            },
        }
        with open(os.path.join(self.build_dir, "cmdline.txt"), encoding="utf-8") as fp:
            kernel_cmdline = fp.read().strip()
        kernel_cmdline += (
            " ds=nocloud;s=http://{{ .HTTPIP }}:{{ .HTTPPort }}/"
            f" network-config={base64.b64encode(yaml.dump(network_config).encode()).decode()}"
        )
        extra_qemu_args = [
            ("-dtb", os.path.join(self.build_dir, "output.dtb")),
            ("-kernel", os.path.join(self.build_dir, "kernel.img")),
            ("-append", kernel_cmdline),
        ]
        initrd_path = os.path.join(self.build_dir, "initrd.img")
        if os.path.exists(initrd_path):
            extra_qemu_args.append(("-initrd", initrd_path))
        self.packer_vars["extra_qemu_args"] = extra_qemu_args

    def _prepare_windows_specific_config(self) -> None:
        autounattend_file = _copy_resource("windows/autounattend.xml", self.build_dir)
        firstlogin_file = _copy_resource("windows/firstlogin.ps1", self.build_dir)
        drivers_dir = os.path.join(self.build_dir, "drivers")
        shutil.copytree(
            os.path.join(
                self.deps_dir,
                "drivers",
                "Win10" if "-10" in self.image_spec["name"] else "Win11",
                "amd64" if self.image_spec["arch"] == "x86_64" else "ARM64",
            ),
            drivers_dir,
        )
        self.packer_vars["disk_image"] = False
        self.packer_vars["floppy_files"] = [
            autounattend_file,
            firstlogin_file,
            drivers_dir,
            f"{self.key_path}.pub",
        ]


class TartBuildDirGenerator(BuildDirGenerator):
    @property
    def image_spec(self) -> TartImageSpec:
        image_spec = self.job_config.image_spec
        assert image_spec["spec_type"] == "tart"
        return image_spec

    def prepare(self) -> None:
        super().prepare()
        _copy_resource("packer/tart.pkr.hcl", self.build_dir)
        self.packer_vars["vm_base_name"] = self.image_spec["image"]


@parser_spec
def setup_parser(parser: argparse.ArgumentParser, /) -> None:
    existing_dirs_group = parser.add_mutually_exclusive_group()
    existing_dirs_group.add_argument("--override", action="store_true")
    existing_dirs_group.add_argument("--ignore-existing", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--job-dir", "--jobdir", "--run-dir", "--rundir", default=DEFAULT_RUN_DIR)
    add_deps_dir_option(parser)
    parser.set_defaults(func=main)


def main(args: argparse.Namespace, /) -> None:
    if not args.all:
        prepare_build_dir(
            job_dir=args.job_dir,
            deps_dir=args.deps_dir,
            override=args.override,
            ignore_existing=args.ignore_existing,
        )
        return

    for entry in os.scandir(os.path.join(args.job_dir, JOBS_DIR)):
        if entry.is_dir():
            prepare_build_dir(
                entry.path,
                deps_dir=args.deps_dir,
                override=args.override,
                ignore_existing=args.ignore_existing,
            )


def prepare_build_dir(
    job_dir: str, *, deps_dir: str, override: bool, ignore_existing: bool
) -> None:
    job_dir = os.path.abspath(job_dir)
    run_config = get_run_config(job_dir)
    job_config = get_job_config(job_dir)
    image_spec = job_config.image_spec

    if image_spec["os"] == "darwin" and sys.platform != "darwin":
        raise RuntimeError("cannot run macOS VMs on non-macOS systems")

    print("Processing", image_spec["name"], "job...")
    generator_cls: type[BuildDirGenerator]
    if image_spec["spec_type"] == "disk":
        generator_cls = QemuBuildDirGenerator
    elif image_spec["spec_type"] == "tart":
        generator_cls = TartBuildDirGenerator
    else:
        raise RuntimeError("unknown image spec type")
    generator = generator_cls(run_config, job_config, job_dir, deps_dir=deps_dir)

    if os.path.exists(generator.build_dir):
        if isinstance(generator, QemuBuildDirGenerator) and not os.path.exists(
            generator.image_path
        ):
            print(
                "Build dir already exists but does not contain the system image,"
                " removing before proceeding..."
            )
        elif ignore_existing:
            print("Build dir already exists, skipped.")
            return
        elif not override:
            raise RuntimeError(
                "cannot override an existing build directory when --override flag is not specified"
            )
        shutil.rmtree(generator.build_dir)
    os.makedirs(generator.build_dir)

    generator.prepare()
    generator.save_packer_vars()

    print("Build directory prepared.")


if __name__ == "__main__":
    run(setup_parser())
