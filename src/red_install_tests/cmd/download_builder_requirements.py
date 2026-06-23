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
from collections.abc import Callable, Collection, Iterable, Sequence
from io import BytesIO
from typing import Any, ClassVar, Final
from urllib.parse import urlsplit

import niquests
from typing_extensions import Self

from red_install_tests import http
from red_install_tests.cli import add_deps_dir_option, parser_spec, run
from red_install_tests.job_config import get_host_architecture
from red_install_tests.resources import RESOURCES

SW_7ZIP_VERSION: Final = "26.01"
SW_AAVMF_VERSION: Final = "2022.11-6+deb12u2"
SW_OVMF_VERSION: Final = "2022.11-6+deb12u2"
SW_PACKER_VERSION: Final = "1.15.3"
SW_RPI_UTILS_VERSION: Final = "2026.6.3"
SW_TART_VERSION: Final = "2.32.1"
SW_VIRTIO_WIN_DRIVERS_VERSION: Final = "0.1.285-1"
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
SW_7ZIP_BASE_URL: Final = f"https://github.com/ip7z/7zip/releases/download/{SW_7ZIP_VERSION}/%s"
SW_AAVMF_BASE_URL: Final = (
    f"http://ftp.nl.debian.org/debian/pool/main/e/edk2/qemu-efi-aarch64_{SW_AAVMF_VERSION}_all.deb"
)
SW_OVMF_BASE_URL: Final = (
    f"http://ftp.nl.debian.org/debian/pool/main/e/edk2/ovmf_{SW_OVMF_VERSION}_all.deb"
)
SW_PACKER_BASE_URL: Final = (
    f"https://releases.hashicorp.com/packer/{SW_PACKER_VERSION}/packer_{SW_PACKER_VERSION}_%s.zip"
)
SW_RPI_UTILS_BASE_URL: Final = (
    f"https://github.com/Jackenmen/raspberrypi-utils/releases/download/v{SW_RPI_UTILS_VERSION}"
    "/raspberrypi-utils-%s-%s-Release.zip"
)
SW_TART_BASE_URL: Final = (
    f"https://github.com/cirruslabs/tart/releases/download/{SW_TART_VERSION}/tart.tar.gz"
)
SW_VIRTIO_WIN_DRIVERS_URL: Final = (
    "https://fedorapeople.org/groups/virt/virtio-win/direct-downloads/virtio-win-pkg-scripts-input"
    f"/virtio-win-{SW_VIRTIO_WIN_DRIVERS_VERSION}/virtio-win-prewhql-0.1.zip"
)


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
    REQUIREMENTS: ClassVar[dict[str, Callable[[Self], None]]] = {}

    def __init_subclass__(cls) -> None:
        cls.REQUIREMENTS = {
            attr_name[len("download_") :]: attr_value
            for attr_name, attr_value in cls.__dict__.items()
            if attr_name.startswith("download_")
        }


class Downloader(_DownloaderBase):
    def __init__(self, deps_dir: str) -> None:
        self.deps_dir = deps_dir
        self.bin_dir = os.path.join(deps_dir, "bin")
        self.edk2_dir = os.path.join(deps_dir, "edk2")
        self.drivers_dir = os.path.join(deps_dir, "drivers")
        self.installed_reqs: set[str] = set()

    @property
    def bin_7z(self) -> str:
        return os.path.join(self.bin_dir, "7z.exe" if IS_WINDOWS else "7zz")

    def _download_7z_win(self, base_filename: str) -> None:
        with tempfile.TemporaryDirectory() as tmpdirname:
            extractor = os.path.join(tmpdirname, "7zr.exe")
            url = SW_7ZIP_BASE_URL % "7zr.exe"
            print(f"Fetching {url}...")
            r = _verify_hash(http.get(url))
            with open(extractor, "wb") as fp:
                fp.writelines(r.iter_content())

            plat = "arm64" if get_host_architecture() == "aarch64" else "x64"
            installer = os.path.join(tmpdirname, "7z-installer.exe")
            url = SW_7ZIP_BASE_URL % f"{base_filename}{plat}.exe"
            print(f"Fetching {url}...")
            r = _verify_hash(http.get(url))
            with open(installer, "wb") as fp:
                fp.writelines(r.iter_content())

            subprocess.check_call((extractor, "x", "-o", tmpdirname, installer))

            for filename in ("7z.dll", "7z.exe"):
                shutil.move(
                    os.path.join(tmpdirname, filename), os.path.join(self.bin_dir, filename)
                )

    def _download_7z_unix(self, base_filename: str) -> None:
        match platform_key := (sys.platform, get_host_architecture()):
            case ("linux", "x86_64"):
                filename = f"{base_filename}linux-x64.tar.xz"
            case ("linux", "aarch64"):
                filename = f"{base_filename}linux-arm64.tar.xz"
            case ("darwin", _):
                filename = f"{base_filename}mac.tar.xz"
            case _:
                raise RuntimeError(f"{platform_key} platform is not supported")
        url = SW_7ZIP_BASE_URL % filename
        print(f"Fetching {url}...")
        r = _verify_hash(http.get(url))
        with tarfile.open(fileobj=BytesIO(r.content or b"")) as archive:
            setattr(archive, "extraction_filter", getattr(tarfile, "data_filter", None))
            archive.extract("7zz", self.bin_dir)

    def download_7z(self) -> None:
        print("Downloading 7-zip...")
        base_filename = f"7z{SW_7ZIP_VERSION.replace('.', '')}-"
        if IS_WINDOWS:
            self._download_7z_win(base_filename)
        else:
            self._download_7z_unix(base_filename)
        print("Downloaded.")

    def _download_deb(
        self,
        req_name: str,
        *,
        url: str,
        destination: str,
        files: Iterable[str],
    ) -> None:
        if "7z" not in self.installed_reqs and not os.path.exists(self.bin_7z):
            self.download_7z()
            self.installed_reqs.add("7z")

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

    def download_aavmf(self) -> None:
        self._download_deb(
            "AAVMF",
            url=SW_AAVMF_BASE_URL,
            destination=self.edk2_dir,
            files=(
                f"./usr/share/AAVMF/AAVMF_{suffix}"
                for suffix in ("CODE.fd", "CODE.ms.fd", "VARS.fd", "VARS.ms.fd")
            ),
        )

    def download_ovmf(self) -> None:
        self._download_deb(
            "OVMF",
            url=SW_OVMF_BASE_URL,
            destination=self.edk2_dir,
            files=(
                f"./usr/share/OVMF/OVMF_{suffix}"
                for suffix in ("CODE_4M.fd", "CODE_4M.secboot.fd", "VARS_4M.fd", "VARS_4M.ms.fd")
            ),
        )
        print("Downloaded.")

    def download_packer(self) -> None:
        print("Downloading Packer...")
        plat = "windows" if IS_WINDOWS else sys.platform
        arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(get_host_architecture())
        platform_key = f"{plat}_{arch}"
        if platform_key not in VALID_PLATFORM_KEYS:
            raise RuntimeError(f"{platform_key} platform is not supported")

        url = SW_PACKER_BASE_URL % platform_key
        print(f"Fetching {url}...")
        r = _verify_hash(http.get(url))

        with zipfile.ZipFile(BytesIO(r.content or b"")) as archive:
            if IS_WINDOWS:
                archive.extract("packer.exe", self.bin_dir)
            else:
                archive.extract("packer", self.bin_dir)
                os.chmod(os.path.join(self.bin_dir, "packer"), 0o755)
        print("Downloaded.")

    def download_raspberry_pi_utils(self) -> None:
        print("Downloading raspberrypi-utils...")

        os_name = {"win32": "Windows", "linux": "Linux", "darwin": "macOS"}[sys.platform]
        arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(get_host_architecture())
        if arch not in ("amd64", "arm64"):
            raise RuntimeError(f"{arch} architecture is not supported")

        url = SW_RPI_UTILS_BASE_URL % (os_name, arch)
        print(f"Fetching {url}...")
        r = _verify_hash(http.get(url))

        with zipfile.ZipFile(BytesIO(r.content or b"")) as archive:
            for filename in ("dtapply", "dtmerge.exe" if IS_WINDOWS else "dtmerge"):
                archive.extract(filename, self.bin_dir)
                if not IS_WINDOWS:
                    os.chmod(os.path.join(self.bin_dir, filename), 0o755)
        print("Downloaded.")

    def download_tart(self) -> None:
        if sys.platform != "darwin":
            return
        print("Downloading tart...")

        url = SW_TART_BASE_URL
        print(f"Fetching {url}...")
        r = _verify_hash(http.get(url))

        with tarfile.open(fileobj=BytesIO(r.content or b"")) as archive:
            setattr(archive, "extraction_filter", getattr(tarfile, "data_filter", None))
            archive.extractall(
                self.bin_dir, (m for m in archive if m.name.startswith("tart.app/"))
            )
        os.symlink("tart.app/Contents/MacOS/tart", os.path.join(self.bin_dir, "tart"))
        print("Downloaded.")

    def download_virtio_win_drivers(self) -> None:
        print("Downloading virtio-win drivers...")

        url = SW_VIRTIO_WIN_DRIVERS_URL
        print(f"Fetching {url}...")
        r = _verify_hash(http.get(url))

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
                        archive.extract(os.path.join(os_name, arch, filename), self.drivers_dir)
        print("Downloaded.")

    def run(self, reqs: Collection[str]) -> None:
        os.makedirs(self.bin_dir, exist_ok=True)
        os.makedirs(self.edk2_dir, exist_ok=True)
        reqs = sorted(reqs, key=list(self.REQUIREMENTS).index) if reqs else self.REQUIREMENTS
        installed_reqs: set[str] = set()
        for req_name in reqs:
            if req_name not in installed_reqs:
                self.REQUIREMENTS[req_name](self)
                installed_reqs.add(req_name)


class _ValidateChoicesAction(argparse.Action):
    def __init__(
        self,
        option_strings: Sequence[str],
        dest: str,
        *,
        choices: Iterable[Any] | None,
        **kwargs: Any,
    ) -> None:
        super().__init__(option_strings, dest, **kwargs)
        self.__choices = choices

    def __call__(
        self,
        parser: argparse.ArgumentParser,
        namespace: argparse.Namespace,
        values: str | Sequence[Any] | None,
        option_string: str | None = None,
    ) -> None:
        del option_string
        if values is not None and not isinstance(values, str):
            for value in values:
                self.choices = self.__choices
                try:
                    parser._check_value(self, value)
                finally:
                    self.choices = None
        setattr(namespace, self.dest, values)


@parser_spec
def setup_parser(parser: argparse.ArgumentParser, /) -> None:
    add_deps_dir_option(parser)
    parser.add_argument(
        "requirements",
        metavar="requirement",
        nargs="*",
        # this doesn't work without `_ValidateChoicesAction` until Python 3.12
        choices=Downloader.REQUIREMENTS,
        action=_ValidateChoicesAction,
    )
    parser.set_defaults(func=main)


def main(args: argparse.Namespace, /) -> None:
    downloader = Downloader(args.deps_dir)
    downloader.run(args.requirements)


if __name__ == "__main__":
    run(setup_parser())
