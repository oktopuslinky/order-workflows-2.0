"""Prove the calibration flash is actually on screen, before committing to a take.

Last take lost its calibration because `__demoCalibrate()` painted the four squares
into a page that was not the visible window -- Chrome was behind VS Code, and a second
Chrome window from the same profile muddied which surface CDP was even driving. Nothing
noticed until post, by which point the only anchor for the viewport->video transform and
the refined clock-zero was gone, along with 41 minutes of otherwise perfect footage.

So: paint a long flash, run this, and only start the real take if it prints ALL 4.
It grabs a single frame through the *same* gdigrab path the recorder uses, so a pass
here means the recorder will see the flash too.

    # driver: window.__demoCalibrate(15000)
    python demo/capture/check_flash.py

Exit 0 = all four markers visible. Exit 1 = do not record yet.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import numpy as np
from PIL import Image

HERE = pathlib.Path(__file__).parent
FRAME = HERE / "_flash_check.png"

# Must match instrument.js __demoCalibrate
COLORS = {
    "tl (magenta)": (255, 0, 255),
    "tr (cyan)": (0, 255, 255),
    "bl (yellow)": (255, 255, 0),
    "br (green)": (0, 255, 0),
}
# yuv420 subsampling shifts the pure colours a little; 60 is loose enough to survive
# that and still far from any real UI colour.
TOLERANCE = 60
MIN_PIXELS = 200  # a 60 CSS px square at dpr 1.25 is ~75x75 = 5600 px; 200 is generous


def grab() -> np.ndarray:
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "gdigrab", "-framerate", "15",
         "-draw_mouse", "0", "-i", "desktop", "-frames:v", "1", "-y", str(FRAME)],
        check=True, capture_output=True,
    )
    return np.array(Image.open(FRAME).convert("RGB")).astype(np.int16)


def main() -> int:
    img = grab()
    print(f"desktop frame: {img.shape[1]}x{img.shape[0]}")

    found = 0
    for name, rgb in COLORS.items():
        dist = np.abs(img - np.array(rgb, dtype=np.int16)).sum(axis=2)
        mask = dist < TOLERANCE
        n = int(mask.sum())
        if n >= MIN_PIXELS:
            ys, xs = np.nonzero(mask)
            print(f"  OK      {name:14} {n:6d} px  centroid=({xs.mean():7.1f}, {ys.mean():7.1f})")
            found += 1
        else:
            print(f"  MISSING {name:14} {n:6d} px")

    if found == 4:
        print("\nALL 4 MARKERS VISIBLE -- the flash is being captured. Safe to record.")
        return 0

    print(
        f"\nONLY {found}/4 VISIBLE -- DO NOT START THE TAKE.\n"
        "The flash is painted in the DOM but is not reaching the screen. Check, in order:\n"
        "  1. Is the flash still up? It expires -- re-fire __demoCalibrate(15000).\n"
        "  2. Is the CDP-driven window the one actually on screen? Kill every other Chrome\n"
        "     window from the demo profile; two windows means CDP may drive the hidden one.\n"
        "  3. Is Chrome foreground? SetForegroundWindow silently no-ops unless you\n"
        "     AttachThreadInput to the current foreground thread first (see preflight.ps1).",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
