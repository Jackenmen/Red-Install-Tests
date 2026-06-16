import re
from typing import Any, Final, Literal
from urllib.parse import urljoin, urlsplit, urlunsplit

import niquests
from lxml import etree
from typing_extensions import NotRequired, ReadOnly, TypedDict

DEFAULT_JAVA_VERSION: Final = 25
DEFAULT_IMAGE_FORMAT: Final = "qcow2"

_etree_ns: Final = etree.FunctionNamespace(None)


def _xpath_string(obj: Any) -> str:
    if isinstance(obj, str):
        return obj
    if isinstance(obj, list):
        if not obj:
            return ""
        return str(obj[0])
    return str(obj)


@_etree_ns("ends-with")
def _xpath_endswith(context, hay: Any, needle: Any) -> bool:
    del context
    hay = _xpath_string(hay)
    needle = _xpath_string(needle)
    return hay.endswith(needle)


_GNU_CHECKSUM_PATTERN: Final = re.compile(
    r"^(?P<checksum>[0-9a-f]+)(?: +|\t+)\*?(?P<filename>.+)$"
)
_BSD_CHECKSUM_PATTERN: Final = re.compile(
    r"^(?P<algorithm>[A-Za-z0-9\-]+) *\((?P<filename>.+)\) *= *(?P<checksum>[0-9a-f]+)$"
)

OsType = Literal["darwin", "linux", "windows"]
ArchType = Literal["x86_64", "aarch64"]
ChecksumType = Literal["sha256", "sha512"]
ImageFormatType = Literal["qcow2", "raw", "raw+xz"]
MachineType = Literal["raspi3b", None]
BootModeType = Literal["bios", "uefi", "uefi-secure-boot"]


class _BaseImageLocation(TypedDict):
    download_type: ReadOnly[Literal["checksum-file", "direct-url", "html", "tart-image"]]
    name: str
    os: ReadOnly[NotRequired[OsType]]
    arch: ReadOnly[NotRequired[ArchType]]
    expected_java_version: NotRequired[int]


class _DiskImageLocation(_BaseImageLocation):
    url: str
    image_format: NotRequired[ImageFormatType]
    machine_type: ReadOnly[NotRequired[MachineType]]
    boot_mode: ReadOnly[NotRequired[BootModeType]]


class ChecksumFileImageLocation(_DiskImageLocation, closed=True):
    download_type: Literal["checksum-file"]
    checksum_style: NotRequired[Literal["bsd", "gnu"]]
    checksum_type: NotRequired[ChecksumType]
    filename_pattern: str


class DirectUrlImageLocation(_DiskImageLocation, closed=True):
    download_type: Literal["direct-url"]
    checksum: str


class HtmlImageLocation(_DiskImageLocation, closed=True):
    download_type: Literal["html"]
    url_xpath: str
    checksum_xpath: str
    checksum_type: NotRequired[ChecksumType]


class TartImageLocation(_BaseImageLocation, closed=True):
    download_type: Literal["tart-image"]
    os: Literal["darwin"]
    arch: Literal["aarch64"]
    image: str


ImageLocation = (
    ChecksumFileImageLocation | DirectUrlImageLocation | HtmlImageLocation | TartImageLocation
)


SpecType = Literal["disk", "tart"]


class _BaseImageSpec(TypedDict):
    spec_type: ReadOnly[SpecType]
    name: ReadOnly[str]
    os: ReadOnly[OsType]
    arch: ReadOnly[ArchType]
    expected_java_version: ReadOnly[int]


class DiskImageSpec(_BaseImageSpec, closed=True):
    spec_type: Literal["disk"]
    url: ReadOnly[str]
    checksum: ReadOnly[str]
    image_format: ReadOnly[ImageFormatType]
    machine_type: ReadOnly[MachineType]
    boot_mode: ReadOnly[BootModeType]


class TartImageSpec(_BaseImageSpec, closed=True):
    spec_type: Literal["tart"]
    os: Literal["darwin"]
    arch: Literal["aarch64"]
    image: ReadOnly[str]


ImageSpec = DiskImageSpec | TartImageSpec


def _get_default_boot_mode(machine_type: MachineType) -> BootModeType:
    if machine_type == "raspi3b":
        return "bios"
    # Using EFI versions without Secure Boot by default
    # since Secure Boot works pretty poorly across the large number of OSes we test.
    return "uefi"


def _create_base_image_spec(spec_type: SpecType, location: _BaseImageLocation) -> _BaseImageSpec:
    os_type = location.get("os", "linux")
    arch = location.get("arch", "x86_64" if os_type != "darwin" else "aarch64")
    return {
        "spec_type": spec_type,
        "name": location["name"],
        "os": os_type,
        "arch": arch,
        "expected_java_version": location.get("expected_java_version", DEFAULT_JAVA_VERSION),
    }


def _create_disk_image_spec(
    location: _DiskImageLocation, *, url: str, checksum: str
) -> DiskImageSpec:
    machine_type = location.get("machine_type")
    return {
        **_create_base_image_spec("disk", location),
        "spec_type": "disk",
        "image_format": location.get("image_format", DEFAULT_IMAGE_FORMAT),
        "machine_type": machine_type,
        "boot_mode": location.get("boot_mode") or _get_default_boot_mode(machine_type),
        "url": url,
        "checksum": checksum,
    }


def _generate_image_spec_from_checksum_file(location: ChecksumFileImageLocation) -> DiskImageSpec:
    url = location["url"]
    r = niquests.get(url, retries=5).raise_for_status()
    checksum_type = location.get("checksum_type", "sha256")
    checksum_style = location.get("checksum_style", "gnu")
    checksum_pattern = _GNU_CHECKSUM_PATTERN if checksum_style == "gnu" else _BSD_CHECKSUM_PATTERN
    filename_pattern = re.compile(location["filename_pattern"])
    matched_files = []
    checksum_count = 0
    if not r.text:
        raise RuntimeError(f"could not decode response from URL: {url}")
    for line in r.text.splitlines():
        line = line.strip()
        if not line:
            continue
        match = checksum_pattern.match(line)
        if not match:
            continue
        checksum_count += 1
        filename = match.group("filename")
        if filename_pattern.search(filename):
            matched_files.append((filename, match.group("checksum")))

    if not checksum_count:
        raise RuntimeError(
            f"could not find any {checksum_style.upper()}-style checksums"
            f" in the file found at URL: {url}"
        )

    if not matched_files:
        raise RuntimeError(
            f"could not find any files matching the specified pattern ({filename_pattern!r})"
            f" in the file at URL: {url}"
        )
    if len(matched_files) > 1:
        raise RuntimeError(
            f"more than one file matched the specified pattern ({filename_pattern!r})"
            f" in the file at URL: {url}"
        )
    filename, checksum = matched_files.pop()
    parsed_url = urlsplit(url)
    base_path, _, _ = parsed_url.path.rpartition("/")

    return _create_disk_image_spec(
        location,
        url=urlunsplit(parsed_url._replace(path=f"{base_path}/{filename}")),
        checksum=f"{checksum_type}:{checksum}",
    )


def _generate_image_spec_from_direct_url(location: DirectUrlImageLocation) -> DiskImageSpec:
    return _create_disk_image_spec(location, url=location["url"], checksum=location["checksum"])


def _generate_image_spec_from_html(location: HtmlImageLocation) -> DiskImageSpec:
    url_xpath = etree.XPath(location["url_xpath"])
    checksum_xpath = etree.XPath(location["checksum_xpath"])
    url = location["url"]
    checksum_type = location.get("checksum_type", "sha256")

    r = niquests.get(url, retries=5).raise_for_status()
    if not r.text:
        raise RuntimeError(f"could not decode response from URL: {url}")
    root = etree.HTML(r.text)
    download_urls = url_xpath(root)
    if not download_urls:
        raise RuntimeError(
            f"did not find any elements matching provided URL XPath ({url_xpath!r})"
            f" in the HTML file at URL: {url}"
        )
    checksums = checksum_xpath(root)
    if not checksums:
        raise RuntimeError(
            f"did not find any elements matching provided checksum XPath ({checksum_xpath!r})"
            f" in the HTML file at URL: {url}"
        )
    download_url = urljoin(url, _xpath_string(download_urls[0]))

    return _create_disk_image_spec(
        location, url=download_url, checksum=f"{checksum_type}:{checksums[0]}"
    )


def _generate_image_spec_from_tart_image(location: TartImageLocation) -> TartImageSpec:
    return {
        **_create_base_image_spec("tart", location),
        "spec_type": "tart",
        "os": location["os"],
        "arch": location.get("arch", "aarch64"),
        "image": location["image"],
    }


def generate_image_spec(location: ImageLocation) -> ImageSpec:
    if location["download_type"] == "checksum-file":
        return _generate_image_spec_from_checksum_file(location)
    if location["download_type"] == "direct-url":
        return _generate_image_spec_from_direct_url(location)
    if location["download_type"] == "html":
        return _generate_image_spec_from_html(location)
    if location["download_type"] == "tart-image":
        return _generate_image_spec_from_tart_image(location)
    raise ValueError("Unknown download type")
