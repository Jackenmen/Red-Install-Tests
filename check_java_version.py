#!/usr/bin/env python3
import os
import re
import subprocess
import sys

_RE_JAVA_VERSION_LINE_PRE223 = re.compile(
    r'version "1\.(?P<major>[0-8])\.(?P<minor>0)(?:_(?:\d+))?(?:-.*)?"'
)
_RE_JAVA_VERSION_LINE_223 = re.compile(
    r'version "(?P<major>\d+)(?:\.(?P<minor>\d+))?(?:\.\d+)*(\-[a-zA-Z0-9]+)?"'
)


def main() -> int:
    expected_major_version = int(os.getenv("EXPECTED_JAVA_VERSION", "17"))
    process = subprocess.run(("java", "-version"), stderr=subprocess.PIPE, check=True)
    version_info = process.stderr.decode("utf-8")
    lines = version_info.splitlines()

    for line in lines:
        match = _RE_JAVA_VERSION_LINE_PRE223.search(line)
        if match is None:
            match = _RE_JAVA_VERSION_LINE_223.search(line)
        if match is None:
            continue

        major = int(match["major"])
        if major == expected_major_version:
            return 0

        print(
            f"The detected Java version ({major}) is different"
            f" from expected ({expected_major_version})."
        )
        return 1

    print("Couldn't determine Java version!")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
