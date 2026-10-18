import base64
import re
from typing import Any, Final, Literal, NotRequired, ReadOnly, assert_never
from urllib.parse import urljoin, urlsplit, urlunsplit

import jsonquerylang
import niquests
from lxml import etree
from typing_extensions import TypedDict

from . import http

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
ChecksumStyle = Literal["bsd", "gnu"]
ChecksumType = Literal["sha256", "sha512"]
ImageFormatType = Literal["qcow2", "raw", "raw+xz"]
MachineType = Literal["raspi3b", None]
BootModeType = Literal["bios", "uefi", "uefi-secure-boot"]


class _BaseImageLocation(TypedDict):
    download_type: ReadOnly[
        Literal["checksum-file", "direct-url", "html", "json-file", "tart-image"]
    ]
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
    checksum_style: NotRequired[ChecksumStyle]
    checksum_type: NotRequired[ChecksumType]
    filename_pattern: str


class DirectUrlImageLocation(_DiskImageLocation, closed=True):
    download_type: Literal["direct-url"]
    checksum: str


class _BaseHtmlImageLocation(_DiskImageLocation):
    download_type: Literal["html"]
    url_xpath: str
    checksum_type: NotRequired[ChecksumType]


class _HtmlImageLocationChecksumFile(_BaseHtmlImageLocation, closed=True):
    checksum_file_url_xpath: str
    checksum_style: NotRequired[ChecksumStyle]


class _HtmlImageLocationChecksumValue(_BaseHtmlImageLocation, closed=True):
    checksum_xpath: str


HtmlImageLocation = _HtmlImageLocationChecksumFile | _HtmlImageLocationChecksumValue


class JsonFileImageLocation(_DiskImageLocation, closed=True):
    download_type: Literal["json-file"]
    url_json_query: str
    checksum_type: NotRequired[ChecksumType]
    checksum_json_query: str


class TartImageLocation(_BaseImageLocation, closed=True):
    download_type: Literal["tart-image"]
    os: Literal["darwin"]
    arch: Literal["aarch64"]
    image: str


ImageLocation = (
    ChecksumFileImageLocation
    | DirectUrlImageLocation
    | HtmlImageLocation
    | JsonFileImageLocation
    | TartImageLocation
)


SpecType = Literal["disk", "tart"]


class _BaseImageSpec(TypedDict):
    spec_type: ReadOnly[SpecType]
    name: ReadOnly[str]
    os: ReadOnly[OsType]
    arch: ReadOnly[ArchType]
    expected_java_version: ReadOnly[int]


class _ClosedBaseImageSpec(_BaseImageSpec, closed=True):
    pass


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


def _create_base_image_spec(
    spec_type: SpecType, location: _BaseImageLocation
) -> _ClosedBaseImageSpec:
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


def _extract_checksum(
    url: str, *, checksum_style: ChecksumStyle, filename_pattern: str
) -> tuple[str, str, str]:
    r = http.get(url)
    checksum_pattern = _GNU_CHECKSUM_PATTERN if checksum_style == "gnu" else _BSD_CHECKSUM_PATTERN
    filename_re = re.compile(filename_pattern)
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
        if filename_re.search(filename):
            matched_files.append((filename, match.group("checksum")))

    if not checksum_count:
        raise RuntimeError(
            f"could not find any {checksum_style.upper()}-style checksums"
            f" in the file found at URL: {url}"
        )

    if not matched_files:
        raise RuntimeError(
            f"could not find any files matching the specified pattern ({filename_re!r})"
            f" in the file at URL: {url}"
        )
    if len(matched_files) > 1:
        raise RuntimeError(
            f"more than one file matched the specified pattern ({filename_re!r})"
            f" in the file at URL: {url}"
        )

    filename, checksum = matched_files.pop()
    parsed_url = urlsplit(r.url or url)
    base_path, _, _ = parsed_url.path.rpartition("/")
    url = urlunsplit(parsed_url._replace(path=f"{base_path}/{filename}"))

    return (url, filename, checksum)


def _normalize_checksum(checksum_type: ChecksumType, checksum: str) -> str:
    match checksum_type:
        case "sha256":
            expected_length = 64
        case "sha512":
            expected_length = 128
        case _ as unreachable:
            assert_never(unreachable)

    checksum_parts = checksum.split(":", 1)
    checksum = checksum_parts[-1]
    if len(checksum_parts) == 2 and checksum_parts[0] != checksum_type:
        raise ValueError(
            f"Found checksum declares itself as {checksum_parts[0]}"
            f" but {checksum_type} was expected"
        )

    if len(checksum) != expected_length:
        # assume a base64-encoded checksum
        missing_padding = len(checksum) % 4
        if missing_padding:
            checksum += "=" * (4 - missing_padding)
        return base64.b64decode(checksum).hex()
    return checksum


def _generate_image_spec_from_checksum_file(location: ChecksumFileImageLocation) -> DiskImageSpec:
    url = location["url"]
    checksum_type = location.get("checksum_type", "sha256")
    file_url, _, checksum = _extract_checksum(
        url,
        checksum_style=location.get("checksum_style", "gnu"),
        filename_pattern=location["filename_pattern"],
    )

    return _create_disk_image_spec(location, url=file_url, checksum=f"{checksum_type}:{checksum}")


def _generate_image_spec_from_direct_url(location: DirectUrlImageLocation) -> DiskImageSpec:
    return _create_disk_image_spec(location, url=location["url"], checksum=location["checksum"])


def _generate_image_spec_from_json_file(location: JsonFileImageLocation) -> DiskImageSpec:
    url_json_query = jsonquerylang.compile(jsonquerylang.parse(location["url_json_query"]))
    url = location["url"]
    checksum_type = location.get("checksum_type", "sha256")

    r = http.get(url)
    try:
        data = r.json()
    except niquests.JSONDecodeError as exc:
        raise RuntimeError(f"could not decode response from URL: {url}") from exc

    download_url = url_json_query(data)
    if download_url is None:
        raise RuntimeError(
            "did not find an item matching provided URL JSON Query"
            f" ({location['url_json_query']!r}) in the JSON file at URL: {url}"
        )
    if not isinstance(download_url, str):
        raise RuntimeError(
            f"provided URL JSON Query ({location['url_json_query']!r})"
            f" did not return a string when evaluated on the JSON file at URL: {url}"
        )
    download_url = urljoin(r.url or url, download_url)

    checksum = ""
    checksum_json_query = jsonquerylang.compile(
        jsonquerylang.parse(location["checksum_json_query"])
    )
    checksum = checksum_json_query(data)
    if checksum is None:
        raise RuntimeError(
            "did not find an item matching provided checksum JSON Query"
            f" ({location['checksum_json_query']!r}) in the JSON file at URL: {url}"
        )
    if not isinstance(checksum, str):
        raise RuntimeError(
            f"provided checksum JSON Query ({location['checksum_json_query']!r})"
            f" did not return a string when evaluated on the JSON file at URL: {url}"
        )
    checksum = _normalize_checksum(checksum_type, checksum)

    return _create_disk_image_spec(
        location, url=download_url, checksum=f"{checksum_type}:{checksum}"
    )


def _generate_image_spec_from_html(location: HtmlImageLocation) -> DiskImageSpec:
    url_xpath = etree.XPath(location["url_xpath"])
    url = location["url"]
    checksum_type = location.get("checksum_type", "sha256")

    r = http.get(url)
    if not r.text:
        raise RuntimeError(f"could not decode response from URL: {url}")
    root = etree.HTML(r.text)
    download_url = _xpath_string(url_xpath(root))
    if not download_url:
        raise RuntimeError(
            f"did not find any elements matching provided URL XPath ({url_xpath!r})"
            f" in the HTML file at URL: {url}"
        )
    download_url = urljoin(r.url or url, download_url)

    checksum = ""
    if xpath := location.get("checksum_xpath"):
        checksum_xpath = etree.XPath(xpath)
        checksums = checksum_xpath(root)
        if not checksums:
            raise RuntimeError(
                f"did not find any elements matching provided checksum XPath ({xpath!r})"
                f" in the HTML file at URL: {url}"
            )
        checksum = _normalize_checksum(checksum_type, checksums[0])
    if xpath := location.get("checksum_file_url_xpath"):
        checksum_file_url_xpath = etree.XPath(xpath)
        checksum_file_url = _xpath_string(checksum_file_url_xpath(root))
        if not checksum_file_url:
            raise RuntimeError(
                f"did not find any elements matching provided checksum file URL XPath ({xpath!r})"
                f" in the HTML file at URL: {url}"
            )
        checksum_file_url = urljoin(r.url or url, _xpath_string(checksum_file_url))

        parsed_download_url = urlsplit(download_url)
        _, _, download_filename = parsed_download_url.path.rpartition("/")

        _, _, checksum = _extract_checksum(
            checksum_file_url,
            checksum_style=location.get("checksum_style", "gnu"),
            filename_pattern=re.escape(download_filename),
        )

    if not checksum:
        raise RuntimeError("both checksum_xpath and checksum_file_url_xpath are missing")

    return _create_disk_image_spec(
        location, url=download_url, checksum=f"{checksum_type}:{checksum}"
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
    if location["download_type"] == "json-file":
        return _generate_image_spec_from_json_file(location)
    if location["download_type"] == "tart-image":
        return _generate_image_spec_from_tart_image(location)
    raise ValueError("Unknown download type")
