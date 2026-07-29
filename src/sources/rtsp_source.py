"""RTSP stream source."""

import logging
import os

import cv2

from src.frame_source import FrameRecord, FrameSource

logger = logging.getLogger(__name__)

# FFmpeg RTSP timeouts in microseconds (5 seconds).
_FFMPEG_TIMEOUT_US = 5_000_000


class RTSPSource(FrameSource):
    """
    RTSP stream source with optional sub-stream support.

    Handles network reconnection with exponential backoff.
    """

    def __init__(self, config, clip_deque_size=None):
        super().__init__(config, clip_deque_size)
        self.main_url = config.source.rtsp.main_url
        self.sub_url = config.source.rtsp.sub_url
        self.use_substream = config.source.rtsp.use_substream

    def _open_capture(self):
        """Open RTSP stream, falling back to main URL if sub-stream fails."""
        # Must set BEFORE constructing VideoCapture so FFmpeg picks it up.
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = (
            f"rtsp_transport;tcp|"
            f"stimeout;{_FFMPEG_TIMEOUT_US}|"
            f"timeout;{_FFMPEG_TIMEOUT_US}"
        )

        if self.use_substream and self.sub_url:
            logger.info(
                "Attempting to open sub-stream: %s",
                self._mask_credentials(self.sub_url),
            )
            cap = cv2.VideoCapture(self.sub_url, cv2.CAP_FFMPEG)
            if cap.isOpened():
                logger.info("Sub-stream opened successfully")
                return cap
            cap.release()
            logger.warning("Sub-stream failed, falling back to main stream")

        logger.info(
            "Opening main stream: %s",
            self._mask_credentials(self.main_url),
        )
        cap = cv2.VideoCapture(self.main_url, cv2.CAP_FFMPEG)
        if cap.isOpened():
            logger.info("Main stream opened successfully")
            return cap

        logger.error("Failed to open RTSP stream")
        return None

    def _post_grab(self, frame_record: FrameRecord):
        """RTSP source doesn't need post-processing."""
        pass

    @staticmethod
    def _mask_credentials(url: str) -> str:
        """Mask credentials in URLs for logging."""
        if "://" in url:
            scheme, rest = url.split("://", 1)
            if "@" in rest:
                _, host = rest.rsplit("@", 1)
                return f"{scheme}://***:***@{host}"
        return url
