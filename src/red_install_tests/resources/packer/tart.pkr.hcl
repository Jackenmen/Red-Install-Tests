packer {
  required_plugins {
    qemu = {
      version = ">= 1.20.0"
      source = "github.com/cirruslabs/tart"
    }
  }
}

variable "vm_base_name" {
  type = string
}

variable "headless" {
  type = bool
  default = true
}

locals {
  source_type = "tart-cli"
}

source "tart-cli" "tests" {
  # image location
  vm_base_name = var.vm_base_name

  # use UUID for VM name because it's apparently global
  vm_name = "red-install-tests-macos-${uuidv4()}"

  # configure specs
  cpu_count = 2
  memory_gb = 4
  disk_size_gb = 50

  # avoid launching a GUI for the VNC connection
  headless = var.headless

  # cloud-init configuration
  ssh_username = "admin"
  ssh_password = "admin"
}
