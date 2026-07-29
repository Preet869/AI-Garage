# AI-Garage Architecture

Stage 1 is only about getting frames reliably. Detection comes later.

## Why a grabber thread exists

`cv2.VideoCapture.read()` blocks. If the main thread does the reading and then spends time on inference or I/O, the capture buffer fills with stale frames (or the RTSP socket backs up). A dedicated grabber thread runs `read()` as fast as the source allows and always keeps only the **latest** frame.

```
Main thread                         Grabber thread (daemon)
-----------                         ----------------------
source.read()  ←── _latest ────────  cap.read()
process frame                        store FrameRecord
imshow / keys                        reconnect on failure
Ctrl-C → stop() → join + release
```

The main thread never waits on the camera. It either gets a fresh frame or `None`.

## Why frames are dropped on purpose

If the main thread is slower than the grabber, intermediate frames are skipped. That is correct for monitoring: you want the **current** picture, not a growing backlog of the past.

`read()` tracks sequence numbers. When it returns a frame whose `seq` jumped ahead of `last_consumed`, the gap is added to `frames_dropped`. A climbing drop count with a low frame age means the design is working. A climbing frame age means the display is falling behind real time — the grabber design would be broken.

## Reconnection

On open/read failure the grabber logs a disconnect, sleeps with exponential backoff (doubles each failure, capped at `reconnect_max_delay`), then retries. On success the backoff **resets** to `reconnect_initial_delay`. Without that reset, one blip leaves you stuck at the maximum delay forever.

File sources loop by releasing and reopening the file (not seeking a stale handle), so a deleted/renamed file goes through the same disconnect → backoff → reconnect → recovery path.

## Watchdog

If no frame arrives for `watchdog_timeout` seconds (default **10**), the grabber force-releases and reconnects. This catches silent stalls where `read()` stops producing frames without a clean error. RTSP opens set `OPENCV_FFMPEG_CAPTURE_OPTIONS` (`stimeout` and `timeout`, microseconds) **before** `VideoCapture(..., cv2.CAP_FFMPEG)` so blocked reads eventually return.

## Shutdown

`KeyboardInterrupt` (Ctrl-C) and key `q` both leave the main `with` block so `__exit__` → `stop()` joins the grabber thread and releases the capture. Do not assume "no try/except is needed" — without handling Ctrl-C, cleanup may be skipped.

## Layout

```
main.py                 # sole entry point
config/config.yaml
src/
  config.py             # load + validate
  frame_source.py       # FrameRecord + FrameSource ABC
  frame_factory.py
  sources/
    file_source.py
    rtsp_source.py
tests/
docs/ARCHITECTURE.md    # this file
```
