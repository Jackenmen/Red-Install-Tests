import itertools
import os
import subprocess
import sys
import threading
import time
from fractions import Fraction
from typing import IO, Final, NamedTuple

import av
from PIL import Image
from vncdotool import api


class Video(NamedTuple):
    container: av.container.OutputContainer
    stream: av.VideoStream


class Recorder:
    WIDTH: Final = 800
    HEIGHT: Final = 600

    def __init__(
        self, screenshot_path: str | None, *, video: Video | None = None, fps: int = 8
    ) -> None:
        self.video = video
        self.screenshot_path = screenshot_path
        self.fps = fps
        self.time_base = Fraction(1, fps)
        self._start_time = time.monotonic()
        self._last_frame_time = time.monotonic()
        self.frame_number = 0

    def start(self) -> None:
        self._start_time = time.monotonic()
        self._last_frame_time = self._start_time

    def stop(self) -> None:
        video = self.video
        if video is not None:
            for packet in video.stream.encode():
                video.container.mux_one(packet)
            video.container.close()

    def write_screen(self, screen: Image.Image) -> None:
        if (
            self.frame_number % self.fps == 0
            and (screenshot_path := self.screenshot_path) is not None
        ):
            with open(f"{screenshot_path}.tmp", "wb") as fp:
                screen.save(fp, format="png")
            os.rename(f"{screenshot_path}.tmp", screenshot_path)

        video = self.video
        if video is None:
            return

        stop = time.monotonic()
        total_frames = int((stop - self._start_time) / self.time_base)
        new_frames = total_frames - self.frame_number

        if new_frames == 0:
            return

        frame = av.VideoFrame.from_image(screen)
        for packet in video.stream.encode(frame):
            video.container.mux_one(packet)
        self.frame_number += 1

        if new_frames == 1:
            return

        screen.paste(0x0000FF, (screen.width - 100, 50, screen.width - 50, 100))
        frame = av.VideoFrame.from_image(screen)
        for _ in range(new_frames - 1):
            for packet in video.stream.encode(frame):
                video.container.mux_one(packet)
            self.frame_number += 1


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
        recorder = Recorder(self.screenshot_path)
        video_fp: IO[bytes] | None
        try:
            if self.screencast_path is not None:
                video_fp = open(self.screencast_path, "wb", buffering=0)  # noqa: SIM115
                container = av.open(video_fp, "w", buffer_size=184)
                container.flags |= av.container.Flags.flush_packets.value
                stream = container.add_stream(
                    "vp9",
                    rate=recorder.fps,
                    width=recorder.WIDTH,
                    height=recorder.HEIGHT,
                    time_base=recorder.time_base,
                )
                recorder.video = Video(container, stream)

            # ensure VNC server is up by waiting a bit
            time.sleep(1)

            client = api.connect(self.vnc_address, self.vnc_password)
            client.timeout = 1.0

            max_wait = 1.0 / recorder.fps
            wait = max_wait
            recorder.start()
            while not self._stop.wait(wait):
                wait = 0.0

                start = time.monotonic()
                try:
                    client.refreshScreen()
                except TimeoutError:
                    client.disconnect()
                    client = api.connect(self.vnc_address, self.vnc_password)
                    client.timeout = 1.0
                    wait = max_wait / 2
                    continue
                else:
                    recorder.write_screen(client.screen.copy())
                stop = time.monotonic()

                elapsed = stop - start
                if elapsed < max_wait:
                    wait = max_wait - elapsed
        finally:
            recorder.stop()
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
            exit_code = proc.wait()
            print("QEMU process exited with code:", exit_code)
        except KeyboardInterrupt:
            pass
        finally:
            thread.stop()
            proc.kill()
            thread.join()
            raise SystemExit(proc.wait())


if __name__ == "__main__":
    main()
