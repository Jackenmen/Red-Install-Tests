variable "ssh_host" {
  type = string
}

variable "ssh_port" {
  type = number
}

variable "ssh_username" {
  type = string
}

variable "ssh_private_key_file" {
  type = string
}

locals {
  username = var.ssh_username
  source_type = "null"
}

source "null" "tests" {
  ssh_host = var.ssh_host
  ssh_port = var.ssh_port
  ssh_username = var.ssh_username
  ssh_private_key_file = var.ssh_private_key_file
}
