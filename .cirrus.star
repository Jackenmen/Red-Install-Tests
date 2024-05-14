load("cirrus", "env", "fs", "yaml")

load("github.com/cirrus-modules/graphql", "execute", "failed_instruction", "rerun_task")
load("github.com/cirrus-modules/helpers", "container", "script", "task")


_MANUAL_TASK_NAME = "on_build_finish"
_GET_TASK_STATUSES_QUERY = """\
query GetTaskStatusesQuery($build_id: ID!) {
    build(id: $build_id) {
        tasks {
            id
            name
            status
        }
    }
}"""
_TASK_TRIGGER_MUTATION = """\
mutation TaskTriggerMutation($input: TaskTriggerInput!) {
    trigger(input: $input) {
        clientMutationId
    }
}"""


def _on_build_finish_task():
    return (
        _MANUAL_TASK_NAME + "_task",
        task(
            _MANUAL_TASK_NAME,
            container("alpine", cpu=0.1, memory=256),
            env={"CIRRUS_SHELL": "sh"},
            instructions=[
                {"trigger_type": "manual"},
                script("clone", "echo 'Build finished'"),
            ]
        )
    )


def main(ctx):
    package_name = "https://github.com/Cog-Creators/Red-DiscordBot/tarball/"
    if env["CIRRUS_BRANCH"] == "dev":
        package_name += "V3/develop#egg=Red-DiscordBot"
    elif env["CIRRUS_BRANCH"].startswith("pull/"):
        package_name += "refs/{0}/merge#egg=Red-DiscordBot".format(env["CIRRUS_BRANCH"])
    else:
        package_name = "Red-DiscordBot"

    return [
        ("env", {"RED_PACKAGE_NAME": package_name}),
        _on_build_finish_task(),
    ]


def on_task_completed(ctx):
    _maybe_trigger_manual_task(ctx)


def on_task_aborted(ctx):
    _maybe_trigger_manual_task(ctx)


def on_task_failed(ctx):
    if _check_for_intermittent_errors(ctx):
        return
    _maybe_trigger_manual_task(ctx)


def _check_for_intermittent_errors(ctx):
    if ctx.payload.data.task.automaticReRun:
        print("Task is already an automatic re-run, let's not retry...")
        return False
    for notification in ctx.payload.data.task.notifications:
        msg = notification.message
        if (
            notification.level == "ERROR"
            or msg.startswith("Persistent worker failed to start the task")
        ):
            return True
    instruction = failed_instruction(ctx.payload.data.task.id)
    if not instruction or not instruction["logsTail"]:
        print("Couldn't find any logs for last failed command.")
        return False

    should_rerun = False
    logs = instruction["logsTail"]
    task_name = instruction["name"]

    # task-specific ignores
    if task_name == "install_instructions":
        for line in logs:
            if (
                # observed with dnf on RHEL derivatives
                line.startswith("Errors during downloading metadata for repository")
                # observed with dnf on RHEL derivatives
                or line.startswith("Cannot retrieve metalink for repository: ")
                # observed with zypper on openSUSE Tumbleweed
                or line.endswith("does not contain the desired medium")
                # observed with zypper on openSUSE Leap, it means:
                #  Some repository had to be disabled temporarily because it failed to refresh
                or line == "Exit status: 106"
                # observed with zypper on openSUSE Leap
                or "is temporarily unaccessible" in line
                # observed with apt on Raspbian
                or line.startswith("E: Failed to fetch")
                # observed with chocolatey on Windows
                or line.startswith(" The remote server returned an error:")
                # observed with pip
                or "Connection reset by peer" in line
                # observed with pacman on Arch Linux
                or line == "error: required key missing from keyring"
            ):
                should_rerun = True
                break

    # global ignores
    if not should_rerun:
        for line in logs:
            # Observed while trying to build Python with install_instructions on Arch Linux
            # as well as with install_python_with_pyenv on OSes that use pyenv.
            start = line.find("curl: (")
            if start != -1:
                errno = int(line[start + 7 : line.find(")", start)])
                if errno in (6, 7, 28, 55, 56):
                    should_rerun = True
                    break

    if should_rerun:
        print("Found failed log line indicating a transient issue!")
        new_task_id = rerun_task(ctx.payload.data.task.id)
        print("Successfully re-ran task! Here is the new one: {}".format(new_task_id))
    else:
        print("Didn't find any transient issues in logs!")
    return should_rerun


def _maybe_trigger_manual_task(ctx):
    if ctx.payload.data.task.name == _MANUAL_TASK_NAME:
        return

    data = execute(_GET_TASK_STATUSES_QUERY, {"build_id": ctx.payload.data.build.id})
    task_id = None
    for task in data["build"]["tasks"]:
        if task["name"] == _MANUAL_TASK_NAME:
            task_id = task["id"]
        elif task["status"] in ("TRIGGERED", "SCHEDULED", "EXECUTING"):
            return
    if task_id == None:
        fail("Couldn't find the {0!r} task!".format(_MANUAL_TASK_NAME))

    execute(
        _TASK_TRIGGER_MUTATION,
        {"input": {"taskId": task_id, "clientMutationId": "trigger-" + task_id}},
    )
    print(
        "Successfully triggered the {0!r} task! Here is the ID: {1}".format(
            _MANUAL_TASK_NAME, task_id
        )
    )
