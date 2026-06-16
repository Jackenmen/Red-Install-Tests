#!/usr/bin/env python3
import asyncio
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from io import BytesIO

import aiohttp
import redbot

TEST_CODE_0 = "import spam; exit(spam.system('python -c \"exit(0)\"') != 0)"
TEST_CODE_1 = "import spam; exit(spam.system('python -c \"exit(1)\"') == 0)"
PACKAGE_NAME = "Red-DiscordBot"
PACKAGE_NAME_WITH_EXTRAS = f"{PACKAGE_NAME}[postgres]"


async def main() -> None:
    skip_tests = os.getenv("RED_SKIP_TESTS", "")
    if skip_tests:
        print("Running tests skipped. Reason:", skip_tests)
        raise SystemExit(0)

    package_spec = os.environ["RED_PACKAGE_SPEC"]
    red_install_tests_repo = os.getcwd()

    with subprocess.Popen(
        (sys.executable, os.path.join(tempfile.gettempdir(), "generate_imports.py")),
        stdout=subprocess.PIPE,
    ) as import_generator:
        subprocess.check_call((sys.executable, "-"), stdin=import_generator.stdout)
        stdout, stderr = import_generator.communicate()
        if import_generator.returncode:
            raise subprocess.CalledProcessError(
                import_generator.returncode, import_generator.args, output=stdout, stderr=stderr
            )

    os.mkdir(PACKAGE_NAME)
    os.chdir(PACKAGE_NAME)
    if package_spec == PACKAGE_NAME_WITH_EXTRAS:
        url = (
            f"https://files.pythonhosted.org/packages/source/R/Red-DiscordBot/"
            f"red_discordbot-{redbot.__version__}.tar.gz"
        )
    else:
        url = package_spec[len(f"{PACKAGE_NAME_WITH_EXTRAS} @ ") :]

    if sys.platform == "win32":
        subprocess.run(("curl", "--head", url), check=True)

    async with aiohttp.ClientSession() as session, session.get(url) as resp:
        fp = BytesIO(await resp.read())

        with tarfile.open(fileobj=fp, mode="r|gz") as tar:
            tar.extractall()
            os.chdir(os.listdir()[0])
            shutil.rmtree("redbot")

    package_test_spec = package_spec.replace(PACKAGE_NAME_WITH_EXTRAS, f"{PACKAGE_NAME}[test]")
    for args in (
        (sys.executable, "-m", "pip", "install", "-U", package_test_spec),
        (sys.executable, "-m", "pytest", "-v"),
    ):
        subprocess.run(args, check=True)

    extension_project_dir = os.path.join(tempfile.gettempdir(), "extension-project")
    os.chdir(red_install_tests_repo)
    for args in (
        (sys.executable, "-m", "pip", "install", extension_project_dir),
        (sys.executable, "-c", TEST_CODE_0),
        (sys.executable, "-c", TEST_CODE_1),
    ):
        subprocess.run(args, check=True)


if __name__ == "__main__":
    asyncio.run(main())
