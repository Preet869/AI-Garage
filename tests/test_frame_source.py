"""Unit tests for Stage 1 frame source logic (no camera / no file needed)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.config import validate_config
from src.frame_source import FrameRecord, FrameSource


def _make_config(
    initial: float = 1.0,
    maximum: float = 8.0,
    watchdog: float = 10.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        capture=SimpleNamespace(
            reconnect_initial_delay=initial,
            reconnect_max_delay=maximum,
            watchdog_timeout=watchdog,
            target_fps=30,
        ),
        output=SimpleNamespace(clip_seconds=30),
        source=SimpleNamespace(type="file"),
    )


class FakeSource(FrameSource):
    """FrameSource driven by a fake capture object."""

    def __init__(self, config, fake_capture=None, clip_deque_size=None):
        super().__init__(config, clip_deque_size)
        self._fake_capture = fake_capture
        self.open_calls = 0

    def _open_capture(self):
        self.open_calls += 1
        return self._fake_capture

    def _post_grab(self, frame_record: FrameRecord) -> None:
        pass


def _inject_latest(source: FrameSource, seq: int, frame=None) -> FrameRecord:
    record = FrameRecord(
        frame=frame if frame is not None else object(),
        seq=seq,
        wall_time=0.0,
        mono_time=0.0,
    )
    with source._lock:
        source._latest = record
        source._seq = seq
    return record


class TestExponentialBackoff:
    def test_doubles_then_caps_then_resets(self):
        source = FakeSource(_make_config(initial=1.0, maximum=8.0))

        assert source._reconnect_backoff == 1.0

        assert source._advance_backoff() == 2.0
        assert source._reconnect_backoff == 2.0

        assert source._advance_backoff() == 4.0
        assert source._advance_backoff() == 8.0
        # Cap at max — further advances stay at max
        assert source._advance_backoff() == 8.0
        assert source._advance_backoff() == 8.0

        source._reset_backoff()
        assert source._reconnect_backoff == 1.0

        # After reset, doubling starts over
        assert source._advance_backoff() == 2.0


class TestReadSemantics:
    def test_read_returns_none_when_seq_equals_last_consumed(self):
        source = FakeSource(_make_config())
        _inject_latest(source, seq=5)
        source._last_consumed = 5

        assert source.read() is None

    def test_read_returns_frame_when_newer(self):
        source = FakeSource(_make_config())
        record = _inject_latest(source, seq=3)
        source._last_consumed = 2

        got = source.read()
        assert got is record
        assert source._last_consumed == 3


class TestSequenceGapAccounting:
    def test_frames_dropped_counts_skipped_sequences(self):
        source = FakeSource(_make_config())
        source._last_consumed = 5
        _inject_latest(source, seq=10)

        source.read()

        # gap = 10 - 5 - 1 = 4 frames skipped (6,7,8,9)
        assert source.health()["frames_dropped"] == 4
        assert source.health()["frames_delivered"] == 1

    def test_no_drop_on_consecutive_sequences(self):
        source = FakeSource(_make_config())
        source._last_consumed = 5
        _inject_latest(source, seq=6)

        source.read()
        assert source.health()["frames_dropped"] == 0


class TestConfigValidation:
    def _valid_raw(self) -> dict:
        return {
            "source": {
                "type": "file",
                "file": {"path": "x.mp4", "realtime": False, "loop": True},
            },
            "capture": {
                "target_fps": 30,
                "reconnect_initial_delay": 1,
                "reconnect_max_delay": 30,
                "watchdog_timeout": 10,
            },
            "display": {
                "enabled": True,
                "window_name": "w",
                "show_overlay": True,
            },
            "output": {
                "snapshots_dir": "data/snapshots",
                "clips_dir": "data/clips",
                "clip_seconds": 30,
            },
            "logging": {
                "level": "INFO",
                "file": "logs/x.log",
                "format": "%(message)s",
            },
        }

    def test_bad_source_type_raises_clear_error(self):
        data = self._valid_raw()
        data["source"]["type"] = "webcam"

        with pytest.raises(ValueError) as exc:
            validate_config(data)

        msg = str(exc.value)
        assert "source.type" in msg
        assert "webcam" in msg

    def test_missing_required_key_raises_clear_error(self):
        data = self._valid_raw()
        del data["capture"]

        with pytest.raises(ValueError) as exc:
            validate_config(data)

        msg = str(exc.value)
        assert "Missing required" in msg
        assert "capture" in msg
