import itertools
import os
import subprocess
import sys
import threading
import time
from fractions import Fraction
from typing import IO, NamedTuple

import av
from vncdotool import api


class Video(NamedTuple):
    container: av.container.OutputContainer
    stream: av.VideoStream


class VNCScreenshotThread(threading.Thread):
    def __init__(
        self,
        *,
        screenshot_path: str | None,
        screencast_path: str | None,
        vnc_address: str,
        vnc_password: str,
    ) -> None:
        super().__init__()
        self._stop = threading.Event()
        self.screenshot_path = screenshot_path
        self.screencast_path = screencast_path
        self.vnc_address = vnc_address
        self.vnc_password = vnc_password or None

    def run(self) -> None:
        screenshot_path = self.screenshot_path
        video: Video | None = None
        video_fp: IO[bytes] | None
        fps = 8
        try:
            if self.screencast_path is not None:
                video_fp = open(self.screencast_path, "wb", buffering=0)  # noqa: SIM115
                container = av.open(video_fp, "w", buffer_size=184)
                container.flags |= av.container.Flags.flush_packets.value
                stream = container.add_stream(
                    "vp9", rate=fps, width=800, height=600, time_base=Fraction(1, fps)
                )
                video = Video(container, stream)

            # ensure VNC server is up by waiting a bit
            time.sleep(1)

            max_wait = 1.0 / fps
            client = api.connect(self.vnc_address, self.vnc_password)
            client.timeout = max_wait

            wait = max_wait
            while not self._stop.wait(wait):
                wait = 0.0

                start = time.monotonic()
                try:
                    client.refreshScreen()
                    if screenshot_path is not None:
                        with open(f"{screenshot_path}.tmp", "wb") as fp:
                            client.screen.save(fp, format="png")
                    if video is not None:
                        frame = av.VideoFrame.from_image(client.screen)
                        for packet in video.stream.encode(frame):
                            video.container.mux_one(packet)
                except TimeoutError:
                    client.disconnect()
                    client = api.connect(self.vnc_address, self.vnc_password)
                    client.timeout = max_wait
                    wait = max_wait / 2
                    continue
                if screenshot_path is not None:
                    os.rename(f"{screenshot_path}.tmp", screenshot_path)
                stop = time.monotonic()

                elapsed = stop - start
                if elapsed < max_wait:
                    wait = max_wait - elapsed
        finally:
            if video is not None:
                for packet in video.stream.encode():
                    video.container.mux_one(packet)
                video.container.close()
            if video_fp is not None:
                video_fp.close()
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

    screenshot_path = os.environ.get("RED_INSTALL_TESTS_SCREENSHOT_PATH") or None
    screencast_path = os.environ.get("RED_INSTALL_TESTS_SCREENCAST_PATH") or None
    raw_vnc_args = ""
    for a, b in itertools.pairwise(args):
        if a == "-vnc":
            raw_vnc_args = b
    if not raw_vnc_args:
        raise RuntimeError("could not find VNC argument to QEMU")
    vnc_address, _, vnc_password = raw_vnc_args.partition(",")

    thread = VNCScreenshotThread(
        screenshot_path=screenshot_path,
        screencast_path=screencast_path,
        vnc_address=vnc_address,
        vnc_password=vnc_password,
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
