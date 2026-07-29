"""Factory for creating appropriate frame source based on config."""

import logging

from src.config import Config
from src.frame_source import FrameSource
from src.sources import FileSource, RTSPSource

logger = logging.getLogger(__name__)


def create_frame_source(config: Config, clip_deque_size: int = None) -> FrameSource:
    """
    Create a frame source based on configuration.

    If clip_deque_size is None, uses target_fps * clip_seconds from config.
    """
    if clip_deque_size is None:
        clip_deque_size = int(
            config.capture.target_fps * config.output.clip_seconds
        )

    source_type = config.source.type

    if source_type == "file":
        logger.info("Creating file source: %s", config.source.file.path)
        return FileSource(config, clip_deque_size)

    if source_type == "rtsp":
        logger.info("Creating RTSP source")
        return RTSPSource(config, clip_deque_size)

    raise ValueError(
        f"Unknown source type: {source_type}\nMust be 'file' or 'rtsp'"
    )
