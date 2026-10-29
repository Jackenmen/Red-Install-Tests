import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from collections.abc import Callable, Collection, Iterable
from io import BytesIO
from typing import ClassVar, Final, Self
from urllib.parse import urlsplit

import niquests

from red_install_tests import http
from red_install_tests.cli import add_deps_dir_option, add_job_dir_option, parser_spec, run
from red_install_tests.job_config import get_host_architecture, get_job_config
from red_install_tests.resources import RESOURCES

SW_VERSIONS: Final = json.loads(
    RESOURCES.joinpath("builder_requirement_versions.json").read_text()
)
FILE_CHECKSUMS: Final = json.loads(
    RESOURCES.joinpath("builder_requirement_file_checksums.json").read_text()
)
VALID_PLATFORM_KEYS: Final = {
    "darwin_amd64",
    "darwin_arm64",
    "windows_amd64",
    "linux_amd64",
    "linux_arm64",
}
IS_WINDOWS: Final = sys.platform == "win32"
SW_7ZIP_BASE_URL: Final = "https://github.com/ip7z/7zip/releases/download/{version}/{filename}"
SW_AAVMF_BASE_URL: Final = (
    "http://ftp.nl.debian.org/debian/pool/main/e/edk2/qemu-efi-aarch64_{version}_all.deb"
)
SW_GSUDO_URL: Final = (
    "https://github.com/gerardog/gsudo/releases/download/v{version}/gsudo.portable.zip"
)
SW_OVMF_BASE_URL: Final = "http://ftp.nl.debian.org/debian/pool/main/e/edk2/ovmf_{version}_all.deb"
SW_PACKER_BASE_URL: Final = (
    "https://releases.hashicorp.com/packer/{version}/packer_{version}_{platform}.zip"
)
SW_REFRESHENV_CMD_URL: Final = (
    "https://raw.githubusercontent.com/chocolatey/choco/{commit}"
    "/src/chocolatey.resources/redirects/RefreshEnv.cmd"
)
SW_RPI_UTILS_BASE_URL: Final = (
    "https://github.com/Jackenmen/raspberrypi-utils/releases/download/v{version}"
    "/raspberrypi-utils-{os}-{arch}-Release.zip"
)
SW_TART_BASE_URL: Final = (
    "https://github.com/cirruslabs/tart/releases/download/{version}/tart.tar.gz"
)
SW_VIRTIO_WIN_DRIVERS_URL: Final = (
    "https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/virtio-win-pkg-scripts-input"
    "/virtio-win-{version}/virtio-win-prewhql-0.1.zip"
)
SW_WIN32_OPENSSH_URL: Final = (
    "https://github.com/PowerShell/Win32-OpenSSH/releases/download/{release_tag}"
    "/OpenSSH-{platform}-v{version}.msi"
)
REFRESHENV_CMD_LINE_MAPPINGS = {
    (
        """    'wmic Process"""
        ''' WHERE "Name='!CmdExeName!' AND CommandLine LIKE '%%!uid!%%'"'''
        """ GET ParentProcessID /value'\r\n"""
    ): (
        """    'powershell -command "Get-CimInstance -ClassName Win32_Process"""
        ''' -Filter \\"Name='!CmdExeName!' AND CommandLine LIKE '%%!uid!%%'\\"'''
        """ | Select-Object -ExpandProperty ParentProcessId"'\r\n"""
    ),
    """        'wmic Process WHERE "Handle='%%i'" GET CommandLine /value'\r\n""": (
        """        'powershell -command "Get-CimInstance -Class Win32_Process"""
        ''' -Filter \\"Handle='%%i'\\"'''
        """ | Select-Object -ExpandProperty CommandLine"'\r\n"""
    ),
}


def _verify_hash(r: niquests.Response) -> niquests.Response:
    first_resp = r
    if r.history:
        first_resp = r.history[0]
    filename = urlsplit(first_resp.url or "").path.rsplit("/", 1)[-1]
    hash_name, _, expected_hash = FILE_CHECKSUMS[filename].partition(":")
    h = hashlib.new(hash_name)
    for chunk in r.iter_content():
        h.update(chunk)
    actual_hash = h.hexdigest()
    if actual_hash != expected_hash:
        raise RuntimeError(
            f"Mismatching checksum for file {filename!r}"
            f" - expected {expected_hash}, got {actual_hash}"
        )
    return r


class _DownloaderBase:
    REQUIREMENTS: ClassVar[dict[str, Callable[[Self, str], None]]] = {}

    def __init_subclass__(cls) -> None:
        cls.REQUIREMENTS = {
            attr_name[len("download_") :].replace("_", "-"): attr_value
            for attr_name, attr_value in cls.__dict__.items()
            if attr_name.startswith("download_")
        }


class Downloader(_DownloaderBase):
    def __init__(self, deps_dir: str) -> None:
        self.deps_dir = deps_dir
        self.bin_dir = os.path.join(deps_dir, "bin")
        self.edk2_dir = os.path.join(deps_dir, "edk2")
        self.windows_dir = os.path.join(deps_dir, "windows")
        self.installed_reqs: dict[str, str] = {}

    @property
    def bin_7z(self) -> str:
        return os.path.join(self.bin_dir, "7z.exe" if IS_WINDOWS else "7zz")

    def _download_7z_win(self, version: str, base_filename: str) -> None:
        with tempfile.TemporaryDirectory() as tmpdirname:
            extractor = os.path.join(tmpdirname, "7zr.exe")
            url = SW_7ZIP_BASE_URL.format(version=version, filename="7zr.exe")
            print(f"Fetching {url}...")
            r = _verify_hash(http.get(url))
            with open(extractor, "wb") as fp:
                fp.writelines(r.iter_content())

            plat = "arm64" if get_host_architecture() == "aarch64" else "x64"
            installer = os.path.join(tmpdirname, "7z-installer.exe")
            url = SW_7ZIP_BASE_URL.format(version=version, filename=f"{base_filename}{plat}.exe")
            print(f"Fetching {url}...")
            r = _verify_hash(http.get(url))
            with open(installer, "wb") as fp:
                fp.writelines(r.iter_content())

            subprocess.check_call((extractor, "x", "-o", tmpdirname, installer))

            for filename in ("7z.dll", "7z.exe"):
                shutil.move(
                    os.path.join(tmpdirname, filename), os.path.join(self.bin_dir, filename)
                )

    def _download_7z_unix(self, version: str, base_filename: str) -> None:
        match platform_key := (sys.platform, get_host_architecture()):
            case ("linux", "x86_64"):
                filename = f"{base_filename}linux-x64.tar.xz"
            case ("linux", "aarch64"):
                filename = f"{base_filename}linux-arm64.tar.xz"
            case ("darwin", _):
                filename = f"{base_filename}mac.tar.xz"
            case _:
                raise RuntimeError(f"{platform_key} platform is not supported")
        url = SW_7ZIP_BASE_URL.format(version=version, filename=filename)
        print(f"Fetching {url}...")
        r = _verify_hash(http.get(url))
        with tarfile.open(fileobj=BytesIO(r.content or b"")) as archive:
            setattr(archive, "extraction_filter", getattr(tarfile, "data_filter", None))
            archive.extract("7zz", self.bin_dir)

    def download_7z(self, version: str) -> None:
        print("Downloading 7-zip...")
        base_filename = f"7z{version.replace('.', '')}-"
        if IS_WINDOWS:
            self._download_7z_win(version, base_filename)
        else:
            self._download_7z_unix(version, base_filename)
        print("Downloaded.")

    def _ensure_installed(self, req_name: str) -> None:
        version = SW_VERSIONS[req_name]
        if self.installed_reqs.get(req_name) == version:
            return
        self.REQUIREMENTS[req_name](self, version)
        self.installed_reqs[req_name] = version

    def _download_deb(
        self,
        req_name: str,
        *,
        url: str,
        destination: str,
        files: Iterable[str],
    ) -> None:
        self._ensure_installed("7z")

        print(f"Downloading {req_name}...")
        with tempfile.TemporaryDirectory() as tmpdirname:
            print(f"Fetching {url}...")
            deb_file = os.path.join(tmpdirname, "package.deb")
            r = _verify_hash(http.get(url))
            with open(deb_file, "wb") as fp:
                fp.writelines(r.iter_content())

            data_file = "data.tar"
            subprocess.check_call((self.bin_7z, "x", f"-o{tmpdirname}", deb_file, data_file))
            for filepath in files:
                while True:
                    filedir, filename = filepath.rsplit("/", 1)
                    subprocess.check_call(
                        (
                            self.bin_7z,
                            "x",
                            f"-o{tmpdirname}",
                            os.path.join(tmpdirname, data_file),
                            filepath,
                        )
                    )
                    target_path = os.path.join(destination, filename)
                    try:
                        os.remove(target_path)
                    except FileNotFoundError:
                        pass
                    shutil.move(os.path.join(tmpdirname, filepath), target_path)
                    try:
                        link_target = os.readlink(target_path)
                    except OSError:
                        break
                    if os.sep in link_target:
                        raise RuntimeError("symlinks to different dir not supported")
                    filepath = f"{filedir}/{link_target}"

        print("Downloaded.")

    def download_aavmf(self, version: str) -> None:
        self._download_deb(
            "AAVMF",
            url=SW_AAVMF_BASE_URL.format(version=version),
            destination=self.edk2_dir,
            files=(
                f"./usr/share/AAVMF/AAVMF_{suffix}"
                for suffix in ("CODE.fd", "CODE.ms.fd", "VARS.fd", "VARS.ms.fd")
            ),
        )

    def download_ovmf(self, version: str) -> None:
        self._download_deb(
            "OVMF",
            url=SW_OVMF_BASE_URL.format(version=version),
            destination=self.edk2_dir,
            files=(
                f"./usr/share/OVMF/OVMF_{suffix}"
                for suffix in ("CODE_4M.fd", "CODE_4M.secboot.fd", "VARS_4M.fd", "VARS_4M.ms.fd")
            ),
        )
        print("Downloaded.")

    def download_packer(self, version: str) -> None:
        print("Downloading Packer...")
        plat = "windows" if IS_WINDOWS else sys.platform
        arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(get_host_architecture())
        platform_key = f"{plat}_{arch}"
        if platform_key not in VALID_PLATFORM_KEYS:
            raise RuntimeError(f"{platform_key} platform is not supported")

        url = SW_PACKER_BASE_URL.format(version=version, platform=platform_key)
        print(f"Fetching {url}...")
        r = _verify_hash(http.get(url))

        with zipfile.ZipFile(BytesIO(r.content or b"")) as archive:
            if IS_WINDOWS:
                archive.extract("packer.exe", self.bin_dir)
            else:
                archive.extract("packer", self.bin_dir)
                os.chmod(os.path.join(self.bin_dir, "packer"), 0o755)
        print("Downloaded.")

    def download_rpi_utils(self, version: str) -> None:
        print("Downloading raspberrypi-utils...")

        os_name = {"win32": "Windows", "linux": "Linux", "darwin": "macOS"}[sys.platform]
        arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(get_host_architecture())
        if arch not in ("amd64", "arm64"):
            raise RuntimeError(f"{arch} architecture is not supported")

        url = SW_RPI_UTILS_BASE_URL.format(version=version, os=os_name, arch=arch)
        print(f"Fetching {url}...")
        r = _verify_hash(http.get(url))

        with zipfile.ZipFile(BytesIO(r.content or b"")) as archive:
            for filename in ("dtapply", "dtmerge.exe" if IS_WINDOWS else "dtmerge"):
                archive.extract(filename, self.bin_dir)
                if not IS_WINDOWS:
                    os.chmod(os.path.join(self.bin_dir, filename), 0o755)
        print("Downloaded.")

    def download_tart(self, version: str) -> None:
        if sys.platform != "darwin":
            return
        print("Downloading tart...")

        url = SW_TART_BASE_URL.format(version=version)
        print(f"Fetching {url}...")
        r = _verify_hash(http.get(url))

        with tarfile.open(fileobj=BytesIO(r.content or b"")) as archive:
            setattr(archive, "extraction_filter", getattr(tarfile, "data_filter", None))
            archive.extractall(
                self.bin_dir, (m for m in archive if m.name.startswith("tart.app/"))
            )
        os.symlink("tart.app/Contents/MacOS/tart", os.path.join(self.bin_dir, "tart"))
        print("Downloaded.")

    def download_virtio_win(self, version: str) -> None:
        print("Downloading virtio-win drivers...")

        url = SW_VIRTIO_WIN_DRIVERS_URL.format(version=version)
        print(f"Fetching {url}...")
        r = _verify_hash(http.get(url))

        drivers_dir = os.path.join(self.windows_dir, "drivers")
        try:
            shutil.rmtree(drivers_dir)
        except FileNotFoundError:
            pass

        with zipfile.ZipFile(BytesIO(r.content or b"")) as archive:
            for os_name in ("Win10", "Win11"):
                for arch in ("amd64", "ARM64"):
                    for filename in (
                        "netkvm.cat",
                        "netkvm.inf",
                        "netkvm.sys",
                        "netkvmp.exe",
                        "viogpudo.cat",
                        "viogpudo.inf",
                        "viogpudo.sys",
                        "viostor.cat",
                        "viostor.inf",
                        "viostor.sys",
                    ):
                        archive.extract(os.path.join(os_name, arch, filename), drivers_dir)
        print("Downloaded.")

    def download_gsudo(self, version: str) -> None:
        print("Downloading gsudo...")

        url = SW_GSUDO_URL.format(version=version)
        print(f"Fetching {url}...")
        r = _verify_hash(http.get(url))

        gsudo_dir = os.path.join(self.windows_dir, "gsudo")
        try:
            shutil.rmtree(gsudo_dir)
        except FileNotFoundError:
            pass

        with zipfile.ZipFile(BytesIO(r.content or b"")) as archive:
            for file in archive.namelist():
                if file.startswith(("x64/", "arm64/")):
                    archive.extract(file, gsudo_dir)

        print("Downloaded.")

    def download_refreshenv_cmd(self, version: str) -> None:
        print("Downloading RefreshEnv.cmd...")

        url = SW_REFRESHENV_CMD_URL.format(commit=version)
        print(f"Fetching {url}...")
        r = _verify_hash(http.get(url))
        with open(
            os.path.join(self.windows_dir, "RefreshEnv.cmd"), "w", encoding="utf-8-sig", newline=""
        ) as fp:
            fp.writelines(
                REFRESHENV_CMD_LINE_MAPPINGS.get(line, line)
                for line in (r.text or "").splitlines(keepends=True)
            )

        print("Downloaded.")

    def download_win32_openssh_x64(self, version: str) -> None:
        print("Downloading Win32-OpenSSH for x86-64...")

        base_version, _, _ = version.partition("p")
        url = SW_WIN32_OPENSSH_URL.format(
            release_tag=version, version=base_version, platform="Win64"
        )
        print(f"Fetching {url}...")
        r = _verify_hash(http.get(url))
        with open(os.path.join(self.windows_dir, "openssh-x86_64.msi"), "wb") as fp:
            fp.writelines(r.iter_content())
        print("Downloaded.")

    def download_win32_openssh_arm64(self, version: str) -> None:
        print("Downloading Win32-OpenSSH for ARM64...")

        base_version, _, _ = version.partition("p")
        url = SW_WIN32_OPENSSH_URL.format(
            release_tag=version, version=base_version, platform="ARM64"
        )
        print(f"Fetching {url}...")
        r = _verify_hash(http.get(url))
        with open(os.path.join(self.windows_dir, "openssh-aarch64.msi"), "wb") as fp:
            fp.writelines(r.iter_content())
        print("Downloaded.")

    def run(self, reqs: Collection[str]) -> None:
        os.makedirs(self.bin_dir, exist_ok=True)
        os.makedirs(self.edk2_dir, exist_ok=True)
        reqs = sorted(reqs, key=list(self.REQUIREMENTS).index) if reqs else self.REQUIREMENTS

        installed_versions_file = os.path.join(self.deps_dir, "installed_versions.json")
        try:
            with open(installed_versions_file, encoding="utf-8") as fp:
                self.installed_reqs = json.load(fp)
        except FileNotFoundError:
            self.installed_reqs = {}

        for req_name in reqs:
            self._ensure_installed(req_name)

        with open(installed_versions_file, "w", encoding="utf-8") as fp:
            json.dump(self.installed_reqs, fp, indent=4)


@parser_spec
def setup_parser(parser: argparse.ArgumentParser, /) -> None:
    add_deps_dir_option(parser)
    add_job_dir_option(parser)
    parser.add_argument(
        "requirements",
        metavar="requirement",
        nargs="*",
        choices=Downloader.REQUIREMENTS,
    )
    parser.set_defaults(func=main)


def main(args: argparse.Namespace, /) -> None:
    downloader = Downloader(args.deps_dir)
    if args.requirements or args.job_dir is None:
        downloader.run(args.requirements)
    else:
        job_config = get_job_config(args.job_dir)
        image_spec = job_config.image_spec
        requirements = ["packer"]
        if image_spec["spec_type"] == "disk":
            if image_spec["arch"] == "x86_64":
                requirements.append("ovmf")
            else:
                requirements.append("aavmf")
            if image_spec["machine_type"] == "raspi3b":
                requirements.append("7z")
                requirements.append("rpi-utils")
            if image_spec["os"] == "windows":
                requirements.append("gsudo")
                requirements.append("refreshenv-cmd")
                requirements.append("virtio-win")
                if image_spec["arch"] == "x86_64":
                    requirements.append("win32-openssh-x64")
                if image_spec["arch"] == "aarch64":
                    requirements.append("win32-openssh-arm64")
        elif image_spec["spec_type"] == "tart":
            requirements.append("tart")

        downloader.run(requirements)


if __name__ == "__main__":
    run(setup_parser())
