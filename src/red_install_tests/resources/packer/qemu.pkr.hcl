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
      ["-d", "out_asm,in_asm,op,op_opt,op_ind,int,exec,cpu,fpu,mmu,pcall,cpu_reset,unimp,guest_errors,page,nochain,plugin,trace:ac*,trace:adb*,trace:ahci_dma_prepare_buf_*,trace:ahci_mem_write_host_u*,trace:ahci_mem_write_u*,trace:ahci_populate_sglist_*,trace:ahci_port_write_u*,trace:ahci_r*,trace:ahci_se*,trace:ahci_u*,trace:ai*,trace:al*,trace:am*,trace:ar*,trace:as*,trace:at*,trace:au*,trace:aw*,trace:ba*,trace:blo*,trace:bm*,trace:br*,trace:ca*,trace:cl*,trace:cm*,trace:co*,trace:cpuh*,trace:cu*,trace:d*,trace:e*,trace:f*,trace:g3*,trace:gd_g*,trace:gd_k*,trace:gd_s*,trace:gd_un*,trace:handle_cmd_b*,trace:handle_cmd_n*,trace:handle_cmd_u*,trace:handle_h*,trace:handle_q*,trace:hb*,trace:hd*,trace:he*,trace:hi*,trace:ide_atapi_cmd_error,trace:im*,trace:in*,trace:io*,trace:is*,trace:j*,trace:ke*,trace:kvm_c*,trace:kvm_d*,trace:kvm_f*,trace:kvm_i*,trace:kvm_m*,trace:kvm_res*,trace:kvm_s*,trace:kvm_x*,trace:la*,trace:le*,trace:loa*,trace:ls*,trace:lu*,trace:ma*,trace:md*,trace:meg*,trace:mh*,trace:mi*,trace:mo*,trace:mp*,trace:ms*,trace:mu*,trace:n*,trace:op*,trace:os*,trace:pci_n*,trace:pci_u*,trace:pflash_c*,trace:pflash_de*,trace:pflash_e*,trace:pflash_m*,trace:pflash_p*,trace:pflash_r*,trace:pflash_s*,trace:pflash_t*,trace:pflash_u*,trace:pflash_write_*,trace:pi*,trace:pl*,trace:pn*,trace:po*,trace:pp*,trace:pr*,trace:ps*,trace:pu*,trace:pv*,trace:px*,trace:qa*,trace:qb*,trace:qcr*,trace:qd*,trace:qed*,trace:qemu_an*,trace:qemu_f*,trace:qemu_l*,trace:qemu_r*,trace:qemu_s*,trace:qemu_vfi*,trace:qi*,trace:qm*,trace:qu*,trace:qx*,trace:r*,trace:s*,trace:tc*,trace:tp*,trace:tr*,trace:tu*,trace:u*,trace:v9*,trace:vd*,trace:vf*,trace:vg*,trace:vh*,trace:via*,trace:virtio_ba*,trace:virtio_blk_d*,trace:virtio_c*,trace:virtio_g*,trace:virtio_i*,trace:virtio_m*,trace:virtio_ne*,trace:virtio_p*,trace:virtio_r*,trace:virtio_s*,trace:vm*,trace:vn*,trace:vt*,trace:w*,trace:xe*,trace:xi*,trace:xk*"],
      ["-device", "${local.net_device},netdev=user.0"],
      ["-device", "usb-kbd"],
      ["-device", "usb-tablet"],
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
  cd_files = var.cd_files
  cd_label = "cidata"
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
  # - for Windows, it needs to be larger because we have to install the system from scratch
  # - for Linux ARM, it needs to be larger because we (usually) have to emulate it and boot is slower
  # - for Linux x86_64, boot takes only around a minute
  ssh_timeout = (var.os == "windows" ? "35m" : (!local.is_x86_64 ? "20m" : "5m"))
  qemuargs = local.qemu_args
}
