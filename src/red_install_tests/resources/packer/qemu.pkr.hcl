packer {
  required_plugins {
    qemu = {
      version = ">= 1.2.0"
      source = "github.com/cog-creators/qemu"
    }
  }
}

variable "iso_url" {
  type = string
}

variable "iso_checksum" {
  type = string
  default = "none"
}

variable "disk_image" {
  type = bool
  default = true
}

variable "machine_type" {
  type = string
  default = null
}

variable "cpus" {
  type = number
  default = 2
}

variable "use_backing_file" {
  type = bool
  default = true
}

variable "headless" {
  type = bool
  default = true
}

variable "ssh_private_key_file" {
  type = string
}

variable "http_content" {
  type = map(string)
  default = null
}

variable "floppy_files" {
  type = list(string)
  default = null
}

variable "cd_content" {
  type = map(string)
  default = null
}

variable "architecture" {
  type = string
  default = "x86_64"
  validation {
    condition = contains(["x86_64", "aarch64"], var.architecture)
    error_message = "The architecture value must be one of: x86_64, aarch64."
  }
}

variable "efi_firmware_code" {
  type = string
  default = ""
}

variable "efi_firmware_vars" {
  type = string
  default = ""
}

variable "extra_qemu_args" {
  type = list(tuple([string, string]))
  default = []
}

locals {
  is_x86_64 = var.architecture == "x86_64"
  machine_type = coalesce(var.machine_type, local.is_x86_64 ? "q35" : "virt")
  qemu_args = concat(
    [
      ["-machine", "type=${local.machine_type},accel=hvf:kvm:whpx:tcg"],
      ["-serial", "stdio"],
    ],
    var.extra_qemu_args,
  )
  source_type = "qemu"
}

source "qemu" "tests" {
  # image location
  iso_url = var.iso_url
  iso_checksum = var.iso_checksum
  # indicate whether `iso_url` is actually a bootable QEMU image
  disk_image = var.disk_image

  # The output directory is needed for the disk image but it will be discarded
  # immediately after the OS is shut down. For that reason, we should also skip compaction.
  output_directory = var.output_directory
  skip_compaction = true

  # minimize used disk space/avoid disk compression
  use_backing_file = var.use_backing_file

  # Set to a high enough size to avoid shrinking the base disk image.
  # When on Windows, this must be enough storage for Windows install and Red.
  # In particular:
  # - Oracle Linux base images are 37 GB
  # - Windows 11 refuses to install on a partition smaller than 52 GB so we need 53 GB
  # When disk_interface is an SD card, this must be a power of 2,
  # so we'll just special-case Raspberry Pi 3B.
  disk_size = local.machine_type == "raspi3b" ? "16G" : "53G"

  # avoid launching a GUI for the VNC connection
  headless = var.headless

  # cloud-init configuration
  ssh_private_key_file = var.ssh_private_key_file
  http_content = var.http_content
  floppy_files = var.floppy_files
  cd_content = local.machine_type == "raspi3b" ? null : var.cd_content
  cd_label = "cidata"
  ssh_username = "packer"

  # Keystrokes to send over VNC, only needed on Windows in UEFI mode
  # to get through the "Press any key to boot from CD or DVD" prompt.
  boot_command = var.os == "windows" ? [
    "<spacebar><spacebar><spacebar><spacebar><spacebar><spacebar>",
  ] : []
  boot_wait = "-1s"
  boot_key_interval = "500ms"

  # Use the correct binary for the tested system
  qemu_binary = "qemu-system-${var.architecture}"

  # RAM values:
  # - for Raspberry Pi 3B, it needs to match the actual board (1 GB)
  # - for Windows, the minimum is 4 GB
  # - for Linux, the minimum of some distros (RHEL derivatives) is 1.5 GB
  memory = local.machine_type == "raspi3b" ? 1024 : (var.os == "windows" ? 4096 : 1536)

  # Use correct specs for Raspberry Pi 3B board emulation
  # https://www.qemu.org/docs/master/system/arm/raspi.html
  cpus = local.machine_type == "raspi3b" ? 4 : var.cpus
  net_device = local.machine_type == "raspi3b" ? "usb-net" : "virtio-net"
  disk_interface = local.machine_type == "raspi3b" ? "sd" : "virtio"
  # Some OSes may require x86-64-v3 extensions or ARMv8.2-A (rather than ARMv8.0)
  # so just go with host / max to get the fullest feature set we can.
  cpu_model = local.is_x86_64 ? "host" : (local.machine_type == "raspi3b" ? "" : "max")
  efi_firmware_code = var.efi_firmware_code
  efi_firmware_vars = var.efi_firmware_vars

  # SSH timeout values:
  # - for Windows, it needs to be larger because we have to install the system from scratch
  # - for Linux ARM, it needs to be larger because we (usually) have to emulate it and boot is slower
  # - for Linux x86_64, boot takes only around a minute
  ssh_timeout = (var.os == "windows" ? "25m" : (!local.is_x86_64 ? "20m" : "5m"))
  qemuargs = local.qemu_args
}
