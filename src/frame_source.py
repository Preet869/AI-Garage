"""Core frame source abstraction for file and RTSP sources."""

import logging
import random
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from typing import List, Optional

import cv2

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FrameRecord:
    """A single captured frame with timing information."""
    frame: object  # numpy array (can't type hint cv2 frames properly)
    seq: int  # Monotonic counter incremented per grabbed frame
    wall_time: float  # time.time() for filenames and log timestamps
    mono_time: float  # time.monotonic() for measuring age and latency


class FrameSource(ABC):
    """Abstract base class for frame sources (file or RTSP)."""

    def __init__(self, config, clip_deque_size: Optional[int] = None):
        """
        Initialize frame source.

        Args:
            config: Configuration object (must have capture, output, source sections)
            clip_deque_size: Size of rolling clip deque, or None to disable

        RAM cost at 1080p: ~6 MB/frame (1920*1080*3). A 30s buffer at 30 fps
        is 900 frames ≈ 5.4 GB. Size the deque from clip_seconds * target_fps.
        """
        self.config = config
        self.clip_deque_size = clip_deque_size

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

        self._latest: Optional[FrameRecord] = None
        self._last_consumed = -1
        self._seq = 0

        self._capture: Optional[cv2.VideoCapture] = None
        self._reconnect_backoff = float(config.capture.reconnect_initial_delay)

        self._stats = {
            "frames_grabbed": 0,
            "frames_delivered": 0,
            "frames_dropped": 0,
            "reconnects": 0,
            "last_grab_mono": None,
            "uptime_sec": None,
            "start_mono": time.monotonic(),
        }

        # Rolling clip buffer appended by the grabber thread.
        # RAM cost at 1080p: ~6 MB/frame × maxlen (30s @ 30fps = 900 ≈ 5.4 GB).
        self._clip_deque = (
            deque(maxlen=clip_deque_size)
            if clip_deque_size
            else None
        )

    @abstractmethod
    def _open_capture(self) -> Optional[cv2.VideoCapture]:
        """Open the video capture source. Returns VideoCapture or None."""
        pass

    @abstractmethod
    def _post_grab(self, frame_record: FrameRecord) -> None:
        """Hook after each successful grab (e.g. file realtime pacing)."""
        pass

    def _on_grab_failed(self) -> bool:
        """
        Called when capture.read() fails.

        Returns:
            True to release and reconnect, False to stop the grabber.
        """
        return True

    def _advance_backoff(self) -> float:
        """Double backoff, capped at reconnect_max_delay. Returns new delay."""
        self._reconnect_backoff = min(
            self._reconnect_backoff * 2,
            float(self.config.capture.reconnect_max_delay),
        )
        return self._reconnect_backoff

    def _reset_backoff(self) -> None:
        """Reset backoff to the configured initial delay (call on success)."""
        self._reconnect_backoff = float(self.config.capture.reconnect_initial_delay)

    def start(self) -> None:
        """Spawn the grabber thread and return immediately."""
        if self._thread is not None:
            raise RuntimeError("Frame source already started")

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._grabber_loop,
            daemon=True,
            name="FrameSourceGrabber",
        )
        self._thread.start()
        logger.info("Frame source started")

    def read(self) -> Optional[FrameRecord]:
        """
        Return the newest unconsumed frame, or None if none available.

        Frame dropping is intentional: if the main thread is slower than the
        grabber, skipped sequence numbers are counted in frames_dropped.
        """
        with self._lock:
            if self._latest is None or self._latest.seq == self._last_consumed:
                return None

            gap = self._latest.seq - self._last_consumed - 1
            if gap > 0:
                self._stats["frames_dropped"] += gap

            self._last_consumed = self._latest.seq
            self._stats["frames_delivered"] += 1
            return self._latest

    def copy_clip_frames(self) -> List[FrameRecord]:
        """Return a snapshot of the rolling clip buffer (oldest → newest)."""
        with self._lock:
            if self._clip_deque is None:
                return []
            return list(self._clip_deque)

    def stop(self) -> None:
        """Signal the grabber thread to stop and wait for it."""
        if self._thread is None:
            return

        logger.info("Stopping frame source")
        self._stop_event.set()

        self._thread.join(timeout=5.0)
        if self._thread.is_alive():
            logger.warning("Frame source thread did not terminate within timeout")
        else:
            logger.info("Grabber thread joined")

        if self._capture is not None:
            self._capture.release()
            self._capture = None
            logger.info("Capture released")

        self._thread = None

    def health(self) -> dict:
        """Return current health statistics."""
        with self._lock:
            stats = self._stats.copy()
            stats["uptime_sec"] = time.monotonic() - stats["start_mono"]
            stats["backoff_sec"] = self._reconnect_backoff
            if self._latest is not None:
                stats["latest_seq"] = self._latest.seq
                stats["frame_age_ms"] = (
                    time.monotonic() - self._latest.mono_time
                ) * 1000.0
            else:
                stats["latest_seq"] = None
                stats["frame_age_ms"] = None
        return stats

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False

    def _grabber_loop(self) -> None:
        """Grab frames, reconnect with exponential backoff, watch for stalls."""
        last_grab_mono = None

        while not self._stop_event.is_set():
            if self._capture is None:
                logger.info(
                    "Opening capture (reconnect attempt #%d)",
                    self._stats["reconnects"] + 1,
                )
                self._capture = self._open_capture()

                if self._capture is None:
                    delay = self._reconnect_backoff
                    sleep_for = delay + random.uniform(0, delay * 0.2)
                    logger.warning(
                        "Disconnect: failed to open capture, backing off %.1fs",
                        sleep_for,
                    )
                    self._stats["reconnects"] += 1
                    self._stop_event.wait(timeout=sleep_for)
                    self._advance_backoff()
                    continue

                self._reset_backoff()
                logger.info("Reconnect recovery: capture opened successfully")
                last_grab_mono = time.monotonic()

            # Watchdog: force reconnect if no successful grab for too long
            if last_grab_mono is not None:
                age = time.monotonic() - last_grab_mono
                if age > self.config.capture.watchdog_timeout:
                    logger.error(
                        "Watchdog timeout: no frame in %.1fs (limit: %ss), "
                        "forcing reconnect",
                        age,
                        self.config.capture.watchdog_timeout,
                    )
                    self._capture.release()
                    self._capture = None
                    last_grab_mono = None
                    continue

            ret, frame = self._capture.read()

            if not ret:
                logger.warning("Disconnect: failed to read frame, will reconnect")
                self._capture.release()
                self._capture = None
                if not self._on_grab_failed():
                    logger.info("Grab failure requested stop")
                    break
                continue

            now_wall = time.time()
            now_mono = time.monotonic()
            last_grab_mono = now_mono

            self._seq += 1
            frame_record = FrameRecord(
                frame=frame,
                seq=self._seq,
                wall_time=now_wall,
                mono_time=now_mono,
            )

            with self._lock:
                self._latest = frame_record
                if self._clip_deque is not None:
                    self._clip_deque.append(frame_record)

            self._stats["frames_grabbed"] += 1
            self._stats["last_grab_mono"] = now_mono

            self._post_grab(frame_record)

        logger.info("Grabber loop exited")
