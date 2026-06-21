import argparse
import ctypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import ClassVar, Final, Literal

from red_install_tests.cli import parser_spec, run

StrPath = os.PathLike | str
MODEL_RASPI3B: Final = "raspi3b"
MODEL_RASPI4B: Final = "raspi4b"
RaspberryPiModel = Literal["raspi3b", "raspi4b"]

DTB_FILENAMES: Final[dict[RaspberryPiModel, str]] = {
    MODEL_RASPI3B: "bcm2710-rpi-3-b.dtb",
    MODEL_RASPI4B: "bcm2711-rpi-4-b.dtb",
}
CONFIG_FILENAME: Final = "config.txt"


class CHSAddress(ctypes.LittleEndianStructure):
    _layout_ = "ms"
    _pack_ = 1
    _fields_: ClassVar = [
        ("head", ctypes.c_uint8),
        ("sector", ctypes.c_uint8, 6),
        ("cylinder", ctypes.c_uint16, 10),
    ]

    def __bool__(self) -> bool:
        return any((self.head, self.sector, self.cylinder))


class PartitionEntry(ctypes.LittleEndianStructure):
    _layout_ = "ms"
    _pack_ = 1
    _fields_: ClassVar = [
        ("boot_indicator", ctypes.c_uint8),
        ("start_chs", CHSAddress),
        ("partition_type", ctypes.c_uint8),
        ("end_chs", CHSAddress),
        ("start_lba", ctypes.c_uint32),
        ("end_lba", ctypes.c_uint32),
    ]

    def __bool__(self) -> bool:
        return self.partition_type != 0


PartitionTable: Final = PartitionEntry * 4
PARTITION_TABLE_OFFSET: Final = 446
MBR_SIZE: Final = 512


def section_applies(section: str, model: str) -> bool:
    match section:
        case "none":
            return False
        case "all":
            return True
        case "pi3":
            return model == MODEL_RASPI3B
        case "pi4":
            return model == MODEL_RASPI4B
    return False


def convert_image(src: StrPath, dst: StrPath) -> None:
    subprocess.check_call(("qemu-img", "convert", "-O", "raw", src, dst))


def fix_partition_table(img_file: StrPath) -> None:
    with open(img_file, "r+b") as fp:
        partition_table = PartitionTable.from_buffer_copy(
            fp.read(MBR_SIZE), PARTITION_TABLE_OFFSET
        )
        modified = False
        for partition in partition_table:
            if not partition or partition.start_chs or partition.end_chs:
                # empty partition entry or CHS already exists
                continue
            partition.start_chs = CHSAddress(254, 63, 1023)
            partition.end_chs = CHSAddress(254, 63, 1023)
            modified = True
        if modified:
            fp.seek(PARTITION_TABLE_OFFSET)
            fp.write(partition_table)


def extract_boot_partition(img_file: StrPath, boot_partition_dir: StrPath) -> None:
    bin_name = "7z" if sys.platform == "win32" else "7zz"
    with tempfile.TemporaryDirectory() as tmpdirname:
        partition_file = "0.fat"
        subprocess.check_call(
            (bin_name, "x", f"-o{tmpdirname}", os.fspath(img_file), partition_file)
        )
        subprocess.check_call(
            (bin_name, "x", f"-o{boot_partition_dir}", os.path.join(tmpdirname, partition_file))
        )


def apply_dtb_config(
    *,
    boot_partition_dir: StrPath,
    output_dir: StrPath,
    model: RaspberryPiModel,
) -> None:
    config_file = os.path.join(boot_partition_dir, CONFIG_FILENAME)
    base_dtb_file = os.path.join(boot_partition_dir, DTB_FILENAMES[model])
    output_dtb_file = os.path.join(output_dir, "output.dtb")

    mode = os.F_OK
    if sys.platform != "win32":
        mode |= os.X_OK
    dtapply_bin = shutil.which("dtapply", mode)
    if dtapply_bin is None:
        print("WARNING: could not find dtapply binary - the device tree might be inaccurate.")
        shutil.move(base_dtb_file, output_dtb_file)
        return

    # display does not work in QEMU when VC4 driver is enabled so just skip it
    with open(config_file, "r+", encoding="utf-8") as fp:
        content = fp.read()
        fp.seek(0)
        fp.write(re.sub(r"^dtoverlay=vc4-kms-v3d($|,.+$)", "", content, flags=re.MULTILINE))
        fp.truncate()

    subprocess.check_call(
        (
            sys.executable,
            dtapply_bin,
            "--output",
            output_dtb_file,
            "--overlays-dir",
            os.path.join(boot_partition_dir, "overlays"),
            base_dtb_file,
            config_file,
        )
    )


@parser_spec
def setup_parser(parser: argparse.ArgumentParser, /) -> None:
    parser.add_argument("--model", choices=tuple(DTB_FILENAMES.keys()), default=MODEL_RASPI3B)
    parser.add_argument("img_file")
    parser.add_argument("output_dir")
    parser.set_defaults(func=main)


def main(args: argparse.Namespace, /) -> None:
    os.makedirs(args.output_dir, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmpdirname:
        boot_partition_dir = os.path.join(tmpdirname, "boot")
        img_file = os.path.join(tmpdirname, "system.img")

        convert_image(args.img_file, img_file)
        fix_partition_table(img_file)
        extract_boot_partition(img_file, boot_partition_dir)
        apply_dtb_config(
            boot_partition_dir=boot_partition_dir, output_dir=args.output_dir, model=args.model
        )

        arm_64bit = args.model == MODEL_RASPI4B
        kernel_filename = None
        initrd_filename = None
        auto_initramfs = False
        cmdline_filename = "cmdline.txt"
        with open(os.path.join(boot_partition_dir, CONFIG_FILENAME), encoding="utf-8") as fp:
            active = True
            for raw in fp:
                line = raw.strip()

                # Strip comments at the end of line
                line = re.sub(r"\s*#.*$", "", line)
                if not line:
                    continue

                # Section header
                m = re.fullmatch(r"\[([^\]]+)\]", line)
                if m:
                    active = section_applies(m.group(1).lower(), args.model)
                    continue

                if not active:
                    continue

                # dtparam / dtoverlay
                m = re.match(
                    r"^(?:"
                    r"(arm_64bit|auto_initramfs|kernel|cmdline)\s*=\s*(.*)"
                    r"|(initramfs)\s+(\S+)\s+followkernel"
                    r")",
                    line,
                    re.IGNORECASE,
                )
                if not m:
                    continue

                option_name = (m[1] or m[3]).lower()
                value = (m[2] or m[4]).strip()

                if option_name == "auto_initramfs":
                    auto_initramfs = value == "1"
                elif option_name == "arm_64bit":
                    arm_64bit = value == "1"
                elif option_name == "kernel":
                    kernel_filename = value
                elif option_name == "cmdline":
                    cmdline_filename = value
                else:
                    initrd_filename = value

        if kernel_filename is None:
            if arm_64bit:
                kernel_filename = "kernel8.img"
            elif args.model == MODEL_RASPI3B:
                kernel_filename = "kernel7.img"
            else:
                kernel_filename = "kernel7l.img"

        if initrd_filename is None and auto_initramfs:
            initrd_filename = re.sub("^kernel", "initramfs", kernel_filename, count=1)
            initrd_filename, _, _ = initrd_filename.rpartition(".")

        with open(os.path.join(boot_partition_dir, cmdline_filename), encoding="utf-8") as fp:
            cmdline = fp.read().strip()

        with open(os.path.join(args.output_dir, "cmdline.txt"), "w", encoding="utf-8") as fp:
            fp.write(cmdline)

        print("Kernel filename:", kernel_filename)
        print("initrd filename:", initrd_filename)
        print("Kernel cmdline:", cmdline)

        shutil.move(
            os.path.join(boot_partition_dir, kernel_filename),
            os.path.join(args.output_dir, "kernel.img"),
        )
        if initrd_filename is not None:
            shutil.move(
                os.path.join(boot_partition_dir, initrd_filename),
                os.path.join(args.output_dir, "initrd.img"),
            )


if __name__ == "__main__":
    run(setup_parser())
