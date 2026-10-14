"""Webcam capture + MediaPipe hand landmarks on a background thread.

The tracker only *measures* (pointer position, normalised pinch distance, open
palm); deciding what those mean is gestures.py's job. The render loop reads the
latest sample through a lock-protected slot, so slow inference never stalls
rendering and stale frames are simply overwritten (no queue build-up).

Camera previews use a small in-memory RGB frame and can be hidden with T.
Neither camera images nor landmarks are saved or sent over the network.
"""
from __future__ import annotations

import threading
import time
import sys
import importlib.abc
from dataclasses import dataclass
from pathlib import Path
from typing import Generic, TypeVar


from .config import CameraConfig, GestureConfig
from .gestures import HandSample

class VisionOnlyImports(importlib.abc.MetaPathFinder):
    """Keep MediaPipe's optional audio import from initializing PortAudio.

    MediaPipe eagerly imports AudioRecord along with vision. AudioRecord already
    supports sounddevice being absent. Only this importing thread is affected;
    pygame audio and other threads' imports keep their normal behavior.
    """
    def __init__(self):self.thread=threading.get_ident()
    def find_spec(self, fullname, path=None, target=None):
        if fullname=='sounddevice' and threading.get_ident()==self.thread:
            raise ModuleNotFoundError('Audio capture is unused by the hand tracker',name=fullname)
        return None

@dataclass(frozen=True)
class TrackedHand:
    sample: HandSample
    handedness: str = ""
    score: float = 0.0

@dataclass(frozen=True)
class HandFrame:
    t: float
    hands: tuple[TrackedHand, ...] = ()
    preview: bytes | None = None
    preview_size: tuple[int, int] = (0, 0)

# MediaPipe hand landmark indices
WRIST, THUMB_IP, THUMB_TIP = 0, 3, 4
INDEX_MCP, INDEX_PIP, INDEX_TIP = 5, 6, 8
MIDDLE_MCP, MIDDLE_PIP, MIDDLE_TIP = 9, 10, 12
RING_PIP, RING_TIP = 14, 16
PINKY_MCP, PINKY_PIP, PINKY_TIP = 17, 18, 20

HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8), (5, 9), (9, 10), (10, 11),
    (11, 12), (9, 13), (13, 14), (14, 15), (15, 16), (13, 17), (0, 17), (17, 18), (18, 19), (19, 20),
]

T = TypeVar("T")


class LatestSlot(Generic[T]):
    """Single-value, thread-safe mailbox: writers overwrite, readers get the newest."""

    def __init__(self):
        self._lock = threading.Lock()
        self._value: T | None = None
        self._seq = 0

    def put(self, value: T) -> None:
        with self._lock:
            self._value = value
            self._seq += 1

    def get(self) -> tuple[int, T | None]:
        with self._lock:
            return self._seq, self._value


@dataclass(frozen=True)
class HandMeasure:
    x: float
    y: float
    pinch: float
    open_palm: bool
    fingers_extended: int
    victory: bool = False   # ✌️ index + middle up, ring + pinky curled


def measure_hand(landmarks, aspect: float, pinch_off: float = 0.45) -> HandMeasure:
    """Turn 21 normalised landmarks (N x >=2) into pointer + gesture measurements.

    `aspect` = image width / height. MediaPipe's x and y are normalised separately,
    so x is scaled by the aspect ratio to make distances isotropic before comparing.
    Pinch distance is divided by the wrist->middle-knuckle length, a hand-size
    reference that stays fairly constant as the hand turns, so thresholds don't
    depend on how far the hand is from the camera.
    """
    import numpy as np
    pts = landmarks[:, :2].astype(np.float64) * np.array([aspect, 1.0])
    hand_size = max(float(np.linalg.norm(pts[WRIST] - pts[MIDDLE_MCP])), 1e-4)
    pinch = float(np.linalg.norm(pts[THUMB_TIP] - pts[INDEX_TIP])) / hand_size

    def dist(a: int, b: int) -> float:
        return float(np.linalg.norm(pts[a] - pts[b]))

    # A finger is extended when its tip is clearly farther from the wrist than its PIP joint.
    index, middle, ring, pinky = (dist(tip, WRIST) > 1.15 * dist(pip, WRIST)
                                  for tip, pip in ((INDEX_TIP, INDEX_PIP), (MIDDLE_TIP, MIDDLE_PIP),
                                                   (RING_TIP, RING_PIP), (PINKY_TIP, PINKY_PIP)))
    extended = index + middle + ring + pinky
    thumb_out = dist(THUMB_TIP, PINKY_MCP) > 1.1 * dist(THUMB_IP, PINKY_MCP)
    open_palm = extended == 4 and thumb_out and pinch > pinch_off
    # Ring/pinky must be clearly curled (tip nearer the wrist than the PIP), not just "not
    # extended", so a lazy open hand never reads as ✌️.
    curled = (dist(RING_TIP, WRIST) < dist(RING_PIP, WRIST)
              and dist(PINKY_TIP, WRIST) < dist(PINKY_PIP, WRIST))
    victory = index and middle and curled and pinch > pinch_off
    x, y = float(landmarks[INDEX_TIP, 0]), float(landmarks[INDEX_TIP, 1])
    return HandMeasure(x, y, pinch, open_palm, extended, victory)


class HandTracker:
    """Owns the camera and the MediaPipe HandLandmarker; runs on a daemon thread."""

    def __init__(self, cam: CameraConfig, gesture: GestureConfig | None = None):
        self.cam = cam
        self.pinch_off = (gesture or GestureConfig()).pinch_off
        self.samples: LatestSlot[HandFrame] = LatestSlot()
        self.paused = False
        self.preview_enabled = True
        self._status = ("starting", "info")
        self._status_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="hand-tracker", daemon=True)
        self.inference_fps = 0.0

    # -------------------------------------------------------------- public API
    def start(self) -> None:
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout)

    @property
    def status(self) -> tuple[str, str]:
        """(text, level) where level is info | ok | warn | error."""
        with self._status_lock:
            return self._status

    def _set_status(self, text: str, level: str) -> None:
        with self._status_lock:
            self._status = (text, level)

    # ------------------------------------------------------------ thread body
    def _run(self) -> None:
        try:
            landmarker = self._create_landmarker()
        except Exception as exc:   # missing model / mediapipe import problems: report, don't crash
            self._set_status(str(exc), "error")
            return
        try:
            self._loop(landmarker)
        except Exception as exc:
            self._set_status(f"Hand tracker crashed: {exc}", "error")
        finally:
            try:
                landmarker.close()
            except Exception:
                pass

    def _create_landmarker(self):
        model = Path(self.cam.model_path)
        if not model.is_file():
            raise RuntimeError(f"Hand model missing — run: python scripts/download_hand_model.py")
        self._set_status("loading hand model", "info")
        imports=VisionOnlyImports()
        sys.meta_path.insert(0,imports)
        try:
            import mediapipe as mp
            from mediapipe.tasks.python import BaseOptions, vision
        except ImportError as exc:
            raise RuntimeError(f"mediapipe not installed ({exc})") from exc
        finally:
            sys.meta_path.remove(imports)
        self._mp = mp
        options = vision.HandLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(model)),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=0.5,
            min_hand_presence_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        return vision.HandLandmarker.create_from_options(options)

    def _open_camera(self):
        import cv2
        if self.cam.source_url:
            # Bound network open/read waits so disconnects cannot hang tracking.
            cap=cv2.VideoCapture(self.cam.source_url,cv2.CAP_FFMPEG,
                                 [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,4000,
                                  cv2.CAP_PROP_READ_TIMEOUT_MSEC,1000])
            if not cap.isOpened():
                cap.release()
                return None
            return cap
        cap = cv2.VideoCapture(self.cam.index, cv2.CAP_V4L2)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(self.cam.index)     # let OpenCV pick a backend
        if not cap.isOpened():
            cap.release()
            return None
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.cam.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.cam.height)
        cap.set(cv2.CAP_PROP_FPS,self.cam.max_fps)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)            # newest frame, less latency
        return cap

    def _loop(self, landmarker) -> None:
        import cv2
        import numpy as np
        mp = self._mp
        cap = None
        failures = 0
        last_ts_ms = -1
        min_dt = 1.0 / max(1.0, self.cam.max_fps)
        last_t = 0.0
        fps_t0, fps_n = time.monotonic(), 0
        try:
            while not self._stop.is_set():
                if self.paused:
                    if cap is not None:
                        cap.release()
                        cap = None
                    self._set_status("tracking paused (H)", "warn")
                    self.samples.put(HandFrame(time.monotonic()))
                    self._stop.wait(0.2)
                    continue
                if cap is None:
                    source='network camera' if self.cam.source_url else f'camera {self.cam.index}'
                    self._set_status(f"opening {source}", "info")
                    cap = self._open_camera()
                    if cap is None:
                        self._set_status(f"cannot open {source} — retrying "
                                         "(H for keyboard)", "error")
                        self.samples.put(HandFrame(time.monotonic()))
                        self._stop.wait(2.0)
                        continue
                    failures = 0
                    self._set_status("camera ready — P1 left / P2 right", "ok")

                ok, frame = cap.read()
                t = time.monotonic()
                if not ok or frame is None:
                    failures += 1
                    if failures >= 10:
                        cap.release()
                        cap = None
                        self._set_status("camera disconnected — retrying", "error")
                        self.samples.put(HandFrame(t))
                        self._stop.wait(1.0)
                    else:
                        self._stop.wait(0.03)
                    continue
                failures = 0
                if t - last_t < min_dt:          # frame-rate cap to leave CPU for rendering
                    continue
                last_t = t

                if self.cam.mirror:
                    frame = cv2.flip(frame, 1)
                h, w = frame.shape[:2]
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                ts_ms = max(int(t * 1000), last_ts_ms + 1)     # VIDEO mode needs increasing timestamps
                last_ts_ms = ts_ms
                result = landmarker.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb),
                                                     ts_ms)
                hands = []
                for index, landmarks in enumerate(result.hand_landmarks):
                    lms = np.array([[p.x, p.y, p.z] for p in landmarks], dtype=np.float32)
                    m = measure_hand(lms, w / h, self.pinch_off)
                    points = tuple((float(x), float(y), float(z)) for x, y, z in lms)
                    sample = HandSample(t, True, m.x, m.y, m.pinch, m.open_palm, points, m.victory)
                    categories = result.handedness[index] if index < len(result.handedness) else []
                    label = categories[0].category_name if categories else ""
                    score = categories[0].score if categories else 0.0
                    hands.append(TrackedHand(sample, label, score))
                preview = cv2.resize(rgb,(240,180)).tobytes() if self.preview_enabled else None
                self.samples.put(HandFrame(t, tuple(hands),preview,(240,180)))
                self._set_status(f"tracking {len(hands)}/2 hands", "ok" if hands else "info")

                fps_n += 1
                if t - fps_t0 >= 1.0:
                    self.inference_fps = fps_n / (t - fps_t0)
                    fps_t0, fps_n = t, 0
        finally:
            if cap is not None:
                cap.release()
