variable "output_directory" {
  type = string
  default = ""
}

variable "red_package_spec" {
  type = string
  default = "Red-DiscordBot[postgres]"
}

variable "red_install_instructions" {
  type = list(object({
    commands = list(string)
  }))
}

variable "red_expected_java_version" {
  type = number
  default = 25
}

variable "extra_env_vars" {
  type = map(string)
  default = {}
}

variable "build_name" {
  type = string
}

locals {
  env_vars = merge(
    {
      PIP_ONLY_BINARY = ":all:"
      RED_PACKAGE_SPEC = var.red_package_spec
      EXPECTED_JAVA_VERSION = var.red_expected_java_version
    },
    var.extra_env_vars,
  )
  source_name = "tests"
  sources = ["${local.source_type}.${local.source_name}"]

  tmp_dir = "/tmp"
  default_unix_shell = "bash"
}

build {
  name = var.build_name
  sources = local.sources

  // Ensure cloud-init finishes before doing anything.
  provisioner "shell" {
    inline = ["cloud-init status --long --wait"]
  }

  // Run provided install instructions.
  dynamic "provisioner" {
    for_each = var.red_install_instructions
    labels = ["shell"]
    content {
      inline = concat(["set -eo pipefail"], provisioner.value.commands)
      env = local.env_vars
      inline_shebang = "/usr/bin/env -S ${local.default_unix_shell} -il"
    }
  }

  // Copy over the extension-project and generate_imports.py - needed by ./run_tests.py.
  provisioner "file" {
    sources = [
      "${path.root}/tests/extension-project",
      "${path.root}/tests/generate_imports.py",
    ]
    destination = "${local.tmp_dir}/"
  }

  // Run tests.
  dynamic "provisioner" {
    for_each = [
      // Check that the default Java's version is what we expect it to be.
      "${path.root}/tests/check_java_version.py",
      "${path.root}/tests/run_tests.py",
    ]
    labels = ["shell"]
    content {
      script = provisioner.value
      execute_command = (
        "chmod +x {{ .Path }}; source ~/redenv/bin/activate; {{ .Vars }} python {{ .Path }}"
      )
      remote_path = "${local.tmp_dir}/script-${uuidv4()}.py"
      env = local.env_vars
    }
  }

  // Remove the output directory since we don't actually need the built image.
  post-processor "shell-local" {
    command = "unused-placeholder"
    execute_command = ["rm", "-rf", "${var.output_directory}"]
    except = ["source.null.tests", "source.tart-cli.tests"]
    only_on = ["darwin", "linux"]
  }
  post-processor "shell-local" {
    command = "unused-placeholder"
    execute_command = ["rmdir", "/S", "/Q", "${var.output_directory}"]
    except = ["source.null.tests", "source.tart-cli.tests"]
    only_on = ["windows"]
  }
}
