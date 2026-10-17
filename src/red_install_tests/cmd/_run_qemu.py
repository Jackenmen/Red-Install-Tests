import itertools
import os
import subprocess
import sys
import threading
import time

from vncdotool import api


class VNCScreenshotThread(threading.Thread):
    def __init__(self, *, screenshot_path: str, vnc_address: str, vnc_password: str) -> None:
        super().__init__()
        self._stop = threading.Event()
        self.screenshot_path = screenshot_path
        self.vnc_address = vnc_address
        self.vnc_password = vnc_password or None

    def run(self) -> None:
        tmp_screenshot_path = f"{self.screenshot_path}.tmp"
        # ensure VNC server is up by waiting a bit
        time.sleep(1)
        client = api.connect(self.vnc_address, self.vnc_password)
        client.timeout = 1
        try:
            while not self._stop.wait(1):
                try:
                    client.captureScreen(tmp_screenshot_path, format="png")
                except TimeoutError:
                    continue
                os.rename(tmp_screenshot_path, self.screenshot_path)
        finally:
            client.disconnect()
            api.shutdown()

    def stop(self) -> None:
        self._stop.set()


def main() -> None:
    if sys.__stdout__ is not None:
        sys.__stdout__.reconfigure(line_buffering=True)
    if sys.__stderr__ is not None:
        sys.__stderr__.reconfigure(line_buffering=True)
    architecture = os.environ["RED_INSTALL_TESTS_ARCHITECTURE"]
    qemu_binary = f"qemu-system-{architecture}"
    args = sys.argv[1:]

    if args == ["-version"]:
        subprocess.check_call((qemu_binary, "-version"))
        return

    screenshot_path = os.environ["RED_INSTALL_TESTS_SCREENSHOT_PATH"]
    raw_vnc_args = ""
    for a, b in itertools.pairwise(args):
        if a == "-vnc":
            raw_vnc_args = b
    if not raw_vnc_args:
        raise RuntimeError("could not find VNC argument to QEMU")
    vnc_address, _, vnc_password = raw_vnc_args.partition(",")

    thread = VNCScreenshotThread(
        screenshot_path=screenshot_path, vnc_address=vnc_address, vnc_password=vnc_password
    )
    with subprocess.Popen((qemu_binary, *args)) as proc:
        thread.start()
        try:
            raise SystemExit(proc.wait())
        except KeyboardInterrupt:
            pass
        finally:
            thread.stop()
            proc.kill()
            thread.join()
            raise SystemExit(proc.wait())


if __name__ == "__main__":
    main()
