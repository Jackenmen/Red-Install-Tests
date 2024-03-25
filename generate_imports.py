#!/usr/bin/env python3

import inspect
import sys
from packaging.requirements import Requirement
from typing import Iterable, Union
from typing_extensions import TypeGuard


if sys.version_info >= (3, 10):
    import importlib.metadata as importlib_metadata
else:
    import importlib_metadata


def _top_level_declared(dist: importlib_metadata.Distribution) -> Iterable[str]:
    return (dist.read_text('top_level.txt') or '').split()


def _top_level_inferred(dist: importlib_metadata.Distribution) -> Iterable[str]:
    opt_names = {
        f.parts[0] if len(f.parts) > 1 else inspect.getmodulename(f)
        for f in dist.files or []
    }

    def importable_name(name: Union[str, None]) -> TypeGuard[str]:
        if name is None:
            return False
        return "." not in name and name != "__pycache__"

    return filter(importable_name, opt_names)


def main() -> None:
    packages = set()
    for req_str in importlib_metadata.distribution("Red-DiscordBot").requires or []:
        req = Requirement(req_str)
        if req.marker is not None and not req.marker.evaluate({"extra": "postgres"}):
            continue
        dist = importlib_metadata.distribution(req.name)
        for pkg in _top_level_declared(dist) or _top_level_inferred(dist):
            packages.add(pkg)

    print('print("Trying to import all of Red\'s dependencies...")')

    for pkg in sorted(packages):
        print(f"print('Importing %s' % {repr(pkg)})")
        print(f"import {pkg}")

    print('print("All dependencies have been imported.")')


if __name__ == "__main__":
    main()
