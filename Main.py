"""AI-Garage Stage 1 — frame acquisition entry point.

Run: python main.py
Keys: q quit | s snapshot | c save clip
"""

from __future__ import annotations

import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2

from src.config import load_config
from src.frame_factory import create_frame_source
from src.frame_source import FrameRecord, FrameSource


def setup_logging(config) -> None:
    log_path = Path(config.logging.file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    level = getattr(logging, config.logging.level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format=config.logging.format,
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_path),
        ],
        force=True,
    )


def draw_overlay(
    frame,
    source: FrameSource,
    delivered_fps: float,
    consumed_fps: float,
    frame_age_ms: float,
) -> None:
    stats = source.health()
    lines = [
        f"delivered FPS: {delivered_fps:.1f}",
        f"consumed FPS:  {consumed_fps:.1f}",
        f"dropped:       {stats['frames_dropped']}",
        f"reconnects:    {stats['reconnects']}",
        f"frame age ms:  {frame_age_ms:.0f}",
    ]
    y = 24
    for line in lines:
        cv2.putText(
            frame, line, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3, cv2.LINE_AA
        )
        cv2.putText(
            frame, line, (10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 1, cv2.LINE_AA
        )
        y += 22


def save_snapshot(frame_record: FrameRecord, snapshots_dir: str) -> Path:
    ts = datetime.fromtimestamp(frame_record.wall_time).strftime("%Y%m%d_%H%M%S_%f")
    path = Path(snapshots_dir) / f"snapshot_{ts}.jpg"
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), frame_record.frame)
    return path


def save_clip(source: FrameSource, clips_dir: str, fps: float) -> Path | None:
    records = source.copy_clip_frames()
    if not records:
        return None

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = Path(clips_dir) / f"clip_{ts}.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)

    h, w = records[0].frame.shape[:2]
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"mp4v"),
        max(fps, 1.0),
        (w, h),
    )
    for rec in records:
        writer.write(rec.frame)
    writer.release()
    return path


def main() -> int:
    config = load_config()
    setup_logging(config)
    logger = logging.getLogger("main")
    logger.info("Config loaded: source type = %s", config.source.type)

    window = config.display.window_name
    show_display = config.display.enabled
    show_overlay = config.display.show_overlay

    meter_t0 = time.monotonic()
    prev_grabbed = 0
    prev_delivered = 0
    delivered_fps = 0.0
    consumed_fps = 0.0
    last_frame: FrameRecord | None = None

    try:
        with create_frame_source(config) as source:
            logger.info(
                "Frame source started — press q to quit, s snapshot, c clip"
            )

            while True:
                frame_record = source.read()

                if frame_record is not None:
                    last_frame = frame_record
                    frame_age_ms = (
                        time.monotonic() - frame_record.mono_time
                    ) * 1000.0

                    now = time.monotonic()
                    if now - meter_t0 >= 1.0:
                        stats = source.health()
                        elapsed = now - meter_t0
                        delivered_fps = (
                            stats["frames_grabbed"] - prev_grabbed
                        ) / elapsed
                        consumed_fps = (
                            stats["frames_delivered"] - prev_delivered
                        ) / elapsed
                        prev_grabbed = stats["frames_grabbed"]
                        prev_delivered = stats["frames_delivered"]
                        meter_t0 = now

                    if show_display:
                        display = frame_record.frame.copy()
                        if show_overlay:
                            draw_overlay(
                                display,
                                source,
                                delivered_fps,
                                consumed_fps,
                                frame_age_ms,
                            )
                        cv2.imshow(window, display)

                if show_display:
                    key = cv2.waitKey(1) & 0xFF
                    if key == ord("q"):
                        logger.info("Quit requested (q)")
                        break
                    if key == ord("s") and last_frame is not None:
                        path = save_snapshot(
                            last_frame, config.output.snapshots_dir
                        )
                        logger.info("Snapshot saved: %s", path)
                    if key == ord("c"):
                        path = save_clip(
                            source,
                            config.output.clips_dir,
                            float(config.capture.target_fps),
                        )
                        if path:
                            logger.info("Clip saved: %s", path)
                        else:
                            logger.warning("Clip buffer empty — nothing saved")
                else:
                    time.sleep(0.001)

    except KeyboardInterrupt:
        # Ctrl-C must be handled here so the with-block __exit__ can join the
        # grabber thread and release the capture. A bare daemon exit would skip that.
        logger.info("KeyboardInterrupt — shutting down")
        return 0
    finally:
        if show_display:
            cv2.destroyAllWindows()
        logger.info("Shutdown complete")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
