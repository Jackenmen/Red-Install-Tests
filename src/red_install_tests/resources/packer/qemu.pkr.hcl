packer {
  required_plugins {
    qemu = {
      version = ">= 1.4.4"
      source = "github.com/cog-creators/qemu"
    }
  }
}

variable "red_install_tests_qemu" {
  type = string
  default = env("RED_INSTALL_TESTS_QEMU")
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

variable "cd_files" {
  type = list(string)
  default = null
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
  net_device = local.machine_type == "raspi3b" ? "usb-net" : "virtio-net"
  qemu_args = concat(
    local.machine_type == "raspi3b" ? [] : [
      ["-device", "qemu-xhci"],
      # To avoid issues with multiple displays being detected by the OS and us being able to
      # see only one of them through VNC, we only configure a single display device.
      # On Windows, if we want to see the display the whole time,
      # the best we can do is resorting to ramfb which will be presented to the OS
      # as a UEFI GOP framebuffer. Otherwise, Windows's lack of virtio drivers
      # will present an issue at one point or another.
      # On Linux x86-64, we can use a modern virtio-based display device - virtio-vga.
      # This is identical to virtio-gpu-pci (also known as virtio-gpu) device
      # except for being VGA compatible which matters on systems that don't have
      # virtio-gpu drivers (that probably just means Windows but it doesn't cost us
      # anything to just use the VGA variant anyway).
      # On Linux aarch64, VGA isn't really supported so we just use virtio-gpu.
      # Ref: https://www.kraxel.org/blog/2019/09/display-devices-in-qemu/
      #
      # For consistency with defaults for ramfb, virtio resolution is set to 800x600:
      # Ref: https://github.com/tianocore/edk2/blob/a34a0ef95496fe4d192b490bc40c734194ebf4c6/MdeModulePkg/MdeModulePkg.dec#L1820-L1828
      ["-device", var.os == "windows" ? "ramfb" : join("", ["virtio-", local.is_x86_64 ? "vga" : "gpu", ",xres=800,yres=600"])],
      ["-vga", "none"],
    ],
    [
      ["-machine", "type=${local.machine_type},accel=hvf:kvm:whpx:tcg"],
      ["-serial", "stdio"],
      ["-device", "${local.net_device},netdev=user.0"],
      ["-device", "usb-kbd"],
      ["-device", "usb-tablet"],
    ],
    local.is_x86_64 || local.machine_type == "raspi3b" ? [] : [
      for i in range(
        (var.disk_image ? 0 : 1) + (var.cd_content != null || var.cd_files != null ? 1 : 0)
      ) : ["-device", "usb-storage,drive=cdrom${i}"]
    ],
    var.extra_qemu_args,
  )
  username = "packer"
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
  cd_files = local.machine_type == "raspi3b" ? null : var.cd_files
  cd_label = "cidata"
  cdrom_interface = local.is_x86_64 || local.machine_type == "raspi3b" ? "" : "none"
  ssh_username = local.username

  # Keystrokes to send over VNC, only needed on Windows in UEFI mode
  # to get through the "Press any key to boot from CD or DVD" prompt.
  # With default boot key interval of 100ms, 600 keystrokes should happen over the time of ~60s.
  boot_command = var.os == "windows" ? [for i in range(600): "<bs>"] : []
  boot_wait = "-1s"

  # Use the correct binary for the tested system
  qemu_binary = coalesce(var.red_install_tests_qemu, "qemu-system-${var.architecture}")

  # RAM values:
  # - for Raspberry Pi 3B, it needs to match the actual board (1 GB)
  # - for Windows, the minimum is 4 GB
  # - for Linux, the minimum of some distros (RHEL derivatives) is 1.5 GB
  memory = local.machine_type == "raspi3b" ? 1024 : (var.os == "windows" ? 4096 : 1536)

  # Use correct specs for Raspberry Pi 3B board emulation
  # https://www.qemu.org/docs/master/system/arm/raspi.html
  cpus = local.machine_type == "raspi3b" ? 4 : var.cpus
  net_device = local.net_device
  disk_interface = local.machine_type == "raspi3b" ? "sd" : "virtio"
  # Some OSes may require x86-64-v3 extensions or ARMv8.2-A (rather than ARMv8.0)
  # so just go with host / max to get the fullest feature set we can.
  cpu_model = local.is_x86_64 ? "host" : (local.machine_type == "raspi3b" ? "" : "max")
  efi_firmware_code = var.efi_firmware_code
  efi_firmware_vars = var.efi_firmware_vars

  # SSH timeout values:
  # - for Windows x86_64, it needs to be larger because we have to install the system from scratch
  # - for any ARM build, it needs to be larger because we (usually) have to emulate it and everything is slower
  # - for Linux x86_64, boot takes only around a minute
  ssh_timeout = (var.os == "windows" ? (!local.is_x86_64 ? "245m" : "35m") : (!local.is_x86_64 ? "20m" : "5m"))
  qemuargs = local.qemu_args
}
