#!/usr/bin/env python3
"""Download MediaPipe's hand landmark model (one-time, ~7.8 MB) into ./models/.

The app itself runs fully offline; this is the only network access, at install time.
"""
from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

URL = ("https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
       "hand_landmarker/float16/1/hand_landmarker.task")
DEST = Path(__file__).resolve().parent.parent / "assets" / "models" / "hand_landmarker.task"


def main() -> int:
    if DEST.is_file() and DEST.stat().st_size > 1_000_000:
        print(f"model already present: {DEST}")
        return 0
    DEST.parent.mkdir(parents=True, exist_ok=True)
    tmp = DEST.with_suffix(".part")
    print(f"downloading {URL}")
    try:
        with urllib.request.urlopen(URL, timeout=60) as resp, open(tmp, "wb") as out:
            while chunk := resp.read(1 << 16):
                out.write(chunk)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        print(f"download failed: {exc}", file=sys.stderr)
        return 1
    tmp.replace(DEST)
    print(f"saved {DEST} ({DEST.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
