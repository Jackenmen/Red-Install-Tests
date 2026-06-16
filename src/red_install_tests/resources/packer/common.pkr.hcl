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
    shell = string
    commands = list(string)
    elevated = bool
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

variable "os" {
  type = string
  default = "linux"
  validation {
    condition = contains(["darwin", "linux", "windows"], var.os)
    error_message = "The os value must be one of: darwin, linux, windows."
  }
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

  gsudo_drop_elevation_command = "C:\\gsudo\\gsudo.exe -i Medium "
  windows_python_execute_command = replace(
    <<-EOT
    call C:\\ProgramData\\chocolatey\\bin\\RefreshEnv.cmd
    && call %USERPROFILE%\\redenv\\Scripts\\activate.bat
    && {{ .Vars }}${local.gsudo_drop_elevation_command}python {{ .Path }}
    EOT
    ,
    "\n",
    "",
  )
  powershell_execute_command = replace(
    <<-EOT
    powershell -executionpolicy bypass "& {
      if (Test-Path variable:global:ProgressPreference) {
        set-variable -name variable:global:ProgressPreference -value 'SilentlyContinue'
      };
      . {{.Vars}};
      &${local.gsudo_drop_elevation_command}'{{.Path}}';
      exit $LastExitCode
    }"
    EOT
    ,
    "\n",
    "",
  )
  powershell_elevated_execute_command = replace(
    local.powershell_execute_command, local.gsudo_drop_elevation_command, ""
  )
  cmd_execute_command = "cmd /c {{ .Vars }} ${local.gsudo_drop_elevation_command}\"{{ .Path }}\""
  cmd_elevated_execute_command = replace(
    local.cmd_execute_command, local.gsudo_drop_elevation_command, ""
  )
  tmp_dir = var.os == "windows" ? "C:/Users/packer/AppData/Local/Temp" : "/tmp"
  tmp_dir_winsep = var.os == "windows" ? replace(local.tmp_dir, "/", "\\") : local.tmp_dir
  default_unix_shell = var.os == "darwin" ? "zsh" : "bash"
}

build {
  name = var.build_name
  sources = local.sources

  // Ensure cloud-init finishes before doing anything.
  provisioner "shell" {
    inline = ["cloud-init status --long --wait"]
    only = var.os == "linux" ? local.sources : [""]
  }

  // Run provided install instructions.
  dynamic "provisioner" {
    for_each = var.red_install_instructions
    labels = [provisioner.value.shell]
    content {
      execute_command = (
        provisioner.value.shell == "shell"
          // Unix shell
          ? "chmod +x {{ .Path }}; {{ .Vars }} {{ .Path }}"
          // Windows
          : (
            provisioner.value.shell == "powershell"
              // PowerShell
              ? (
                  provisioner.value.elevated
                    ? local.powershell_elevated_execute_command
                    : local.powershell_execute_command
              )
              // Command Prompt
              : (
                  provisioner.value.elevated
                    ? local.cmd_elevated_execute_command
                    : local.cmd_execute_command
              )
          )
      )
      inline = (
        provisioner.value.shell == "windows-shell"
          ? [for cmd in provisioner.value.commands : "call ${cmd} || exit /b"]
          : (
            provisioner.value.shell == "shell"
              ? concat(["set -eo pipefail"], provisioner.value.commands)
              : provisioner.value.commands
          )
      )
      env = local.env_vars
      // the below conditions have to be mutually exclusive to avoid one overriding another
      override = {
        (provisioner.value.shell == "shell" ? local.source_name : "") = {
          inline_shebang = "/usr/bin/env -S ${local.default_unix_shell} -il"
        }
        (
          provisioner.value.shell == "powershell" && provisioner.value.elevated
            ? local.source_name
            : ""
        ) = {
          elevated_user = "packer"
          elevated_password = "packer"
          remote_path = "${local.tmp_dir}/script-${uuidv4()}.ps1"
          remote_env_var_path = "${local.tmp_dir}/packer-ps-env-vars-${uuidv4()}.ps1"
        }
        (
          provisioner.value.shell == "powershell" && !provisioner.value.elevated
            ? local.source_name
            : ""
        ) = {
          remote_path = "${local.tmp_dir}/script-${uuidv4()}.ps1"
          remote_env_var_path = "${local.tmp_dir}/packer-ps-env-vars-${uuidv4()}.ps1"
        }
        (provisioner.value.shell == "windows-shell" ? local.source_name : "") = {
          remote_path = "${local.tmp_dir}/script-${uuidv4()}.bat"
        }
      }
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
    labels = [var.os == "windows" ? "windows-shell" : "shell"]
    content {
      script = provisioner.value
      execute_command = (
        var.os == "windows"
          ? local.windows_python_execute_command
          : "chmod +x {{ .Path }}; source ~/redenv/bin/activate; {{ .Vars }} python {{ .Path }}"
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
