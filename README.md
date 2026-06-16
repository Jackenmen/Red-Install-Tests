# Red-Install-Tests

The CI setup for running Red's [current stable installation instructions](https://docs.discord.red/en/stable/install_guides/index.html)
and [installation instructions from `V3/develop` branch](https://docs.discord.red/en/latest/install_guides/index.html) daily.

This repo also allows for requesting builds for pending PRs on demand.

## Pre-requirements

- Python 3.10
- [Hatch](https://hatch.pypa.io/latest/install/)
- [QEMU](https://www.qemu.org/download/)
- On Linux, you might need to manually install [xorriso](https://www.gnu.org/software/xorriso/)

## Running locally

> [!NOTE]
> By default, the **run directory** will be the `os-build-run` subdirectory of the current directory.
> All commands that work on a run directory allow you to provide a different directory
> with the `--run-dir` option:
> ```console
> hatch run red-install-tests configure-run --run-dir path/to/run-directory
> ```
> When using project's Hatch scripts (e.g. `hatch run configure-run` instead of
> `hatch run red-install-tests configure-run`), the **run directory** will be
> the `os-build-run` subdirectory of the project root rather than of the current directory.

### Advanced usage

1.  Configure the **run** with the `red-install-tests configure-run` command:
    ```console
    hatch run configure-run
    ```
    By default, the **run** is configured to test the stable version of Red. \
    You can change that with the `--pr`, `--branch`, or `--version` options.
    You can also choose to test Red from a fork using the `--repo` option.
    ```console
    hatch run configure-run --pr 6785
    hatch run configure-run --version 3.5.25
    hatch run configure-run --repo Jackenmen/Red-DiscordBot --branch add_os_image_locations
    ```
1.  Download the Red repository for the **run directory** with the `red-install-tests download-red-repo` command:
    ```console
    hatch run download-red-repo
    ```
1.  Create a **job** for an image in the OS matrix with the `red-install-tests create-job` command:
    ```console
    hatch run create-job ubuntu-2204
    ```
    By default, the **job directory** will be `<run_dir>/jobs/<image_name>`.
    This can be changed with the `--job-dir` option.

    The command can also be used to create multiple jobs (patterns support wildcards):
    ```console
    hatch run create-job opensuse-tumbleweed "windows-*"
    ```
    or jobs for all compatible images in the OS matrix:
    ```console
    hatch run create-job "*"
    ```
    When specifying a pattern, only jobs that can be executed on current system will match. \
    Additionally, you can exclude images that require emulation to run using the `--skip-emulation` flag:
    ```console
    hatch run create-job --skip-emulation "*"
    ```
    Please note that, when specifying a pattern *and* the `--job-dir` option,
    the **job directories** will be subdirectories under the specified directory,
    not the specified directory itself
