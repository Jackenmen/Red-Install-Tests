variable "ssh_host" {
  type = string
}

variable "ssh_username" {
  type = string
}

variable "ssh_private_key_file" {
  type = string
}

locals {
  source_type = "null"
}

source "null" "tests" {
  ssh_host = var.ssh_host
  ssh_username = var.ssh_username
  ssh_private_key_file = var.ssh_private_key_file
}
