"""File-based video source (MP4, MKV, etc.)."""

import logging
import time
from pathlib import Path

import cv2

from src.frame_source import FrameRecord, FrameSource

logger = logging.getLogger(__name__)


class FileSource(FrameSource):
    """
    File-based video source with optional real-time pacing.

    Looping is done by releasing and reopening the file (via the base
    reconnect path) so a deleted/renamed file triggers disconnect → backoff
    → reconnect → recovery instead of seeking a stale handle.
    """

    def __init__(self, config, clip_deque_size=None):
        super().__init__(config, clip_deque_size)
        self.file_path = config.source.file.path
        self.realtime = config.source.file.realtime
        self.loop = config.source.file.loop
        self._last_frame_time = None
        self._frame_interval = (
            1.0 / config.capture.target_fps if self.realtime else 0
        )

    def _open_capture(self):
        """Open video file. Returns None if the path is missing or unreadable."""
        if not Path(self.file_path).is_file():
            logger.error("File not found: %s", self.file_path)
            return None

        cap = cv2.VideoCapture(self.file_path)
        if not cap.isOpened():
            logger.error("Failed to open file: %s", self.file_path)
            return None

        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        logger.info(
            "Opened file: %s (%d frames @ %.1f FPS)",
            self.file_path,
            frame_count,
            fps,
        )
        return cap

    def _on_grab_failed(self) -> bool:
        """Reconnect (loop) or stop when the file ends / becomes unreadable."""
        if self.loop:
            logger.info("End of file or read failure — will reopen to loop")
            return True
        logger.info("End of file, stopping (loop=false)")
        self._stop_event.set()
        return False

    def _post_grab(self, frame_record: FrameRecord):
        """Pace playback; force disconnect if the path vanished mid-read."""
        # OpenCV keeps an open fd after rename/delete, so EOF alone is too late.
        # If the configured path is gone, release now so the base loop does
        # disconnect → backoff → reconnect → recovery without a process restart.
        if not Path(self.file_path).is_file():
            logger.warning(
                "Disconnect: source file disappeared (%s), forcing reconnect",
                self.file_path,
            )
            if self._capture is not None:
                self._capture.release()
                self._capture = None
            return

        if not self.realtime or self._frame_interval == 0:
            return

        if self._last_frame_time is None:
            self._last_frame_time = time.monotonic()
            return

        elapsed = time.monotonic() - self._last_frame_time
        remaining = self._frame_interval - elapsed

        if remaining > 0:
            # Wait interruptibly so stop() is responsive
            self._stop_event.wait(timeout=remaining)

        self._last_frame_time = time.monotonic()
