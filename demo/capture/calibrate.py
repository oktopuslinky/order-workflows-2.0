"""Solve the viewport -> video-pixel transform by measuring it.

The driver calls `__demoCalibrate()` at the top of the take, which paints four
coloured squares at known viewport coordinates for ~700ms. This script grabs a
frame from that window, finds each square's centroid in the recording, and fits

    video_px = scale * viewport_px + offset

That sidesteps every guess about Windows display scaling, device pixel ratio and
browser chrome height -- the numbers come from the actual footage.

Run: python demo/capture/calibrate.py --name app
"""

from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import sys

import numpy as np
from PIL import Image

HERE = pathlib.Path(__file__).parent

# Must match instrument.js
COLORS = {
    "tl": (255, 0, 255),
    "tr": (0, 255, 255),
    "bl": (255, 255, 0),
    "br": (0, 255, 0),
}
TOLERANCE = 40


def extract_frame(video: pathlib.Path, at_s: float, out: pathlib.Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{at_s:.3f}", "-i", str(video), "-frames:v", "1", str(out)],
        check=True,
        capture_output=True,
    )


def centroid(img: np.ndarray, rgb: tuple[int, int, int]) -> tuple[float, float] | None:
    target = np.array(rgb, dtype=np.int16)
    diff = np.abs(img[:, :, :3].astype(np.int16) - target).sum(axis=2)
    mask = diff < TOLERANCE
    if mask.sum() < 50:  # too few pixels -- marker not visible in this frame
        return None
    ys, xs = np.nonzero(mask)
    return float(xs.mean()), float(ys.mean())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="app")
    args = ap.parse_args()

    video = HERE / f"raw-{args.name}.mp4"
    start = json.loads((HERE / f"raw-{args.name}.start.json").read_text(encoding="utf-8-sig"))
    events = json.loads((HERE / "events.json").read_text(encoding="utf-8"))

    calib = next((e for e in events if e["type"] == "calibrate"), None)
    if calib is None:
        print("No calibrate event in events.json", file=sys.stderr)
        return 1

    t0 = start["startEpochMs"]
    # Aim at the middle of the flash window; ffmpeg's own startup latency means
    # the nominal t0 is a little early, so we scan a few offsets if the first miss.
    nominal = (calib["t"] - t0) / 1000.0
    flash_ms = calib["tEnd"] - calib["t"]

    frame_png = HERE / "_calib-frame.png"
    found: dict[str, tuple[float, float]] = {}
    used_at = None

    # ffmpeg spawn latency shifts real t0 later => the flash appears EARLIER in the
    # file than nominal. Scan a window around it.
    for probe in [nominal + (flash_ms / 2000.0) - d for d in (0.0, 0.3, 0.6, 0.9, 1.2, -0.3)]:
        if probe < 0:
            continue
        extract_frame(video, probe, frame_png)
        img = np.array(Image.open(frame_png).convert("RGB"))
        hits = {k: c for k in COLORS if (c := centroid(img, COLORS[k])) is not None}
        if len(hits) == 4:
            found, used_at = hits, probe
            break

    if len(found) != 4:
        print(f"Calibration failed: found {len(found)}/4 markers. Flash may be off-frame.", file=sys.stderr)
        return 1

    # Least-squares fit of  video = scale * viewport + offset  (uniform scale).
    src = np.array([[m["cx"], m["cy"]] for m in calib["markers"] if m["id"] in found])
    dst = np.array([found[m["id"]] for m in calib["markers"] if m["id"] in found])

    # Solve x and y independently; they share a scale in practice, but fitting
    # separately surfaces any anisotropy instead of hiding it.
    sx, ox = np.polyfit(src[:, 0], dst[:, 0], 1)
    sy, oy = np.polyfit(src[:, 1], dst[:, 1], 1)

    probe_img = Image.open(frame_png)
    out = {
        "video": video.name,
        "videoSize": {"w": probe_img.width, "h": probe_img.height},
        "viewport": calib.get("viewport"),
        "dpr": calib.get("dpr"),
        "frameProbedAtS": used_at,
        # video_px = scale * viewport_px + offset
        "scaleX": float(sx),
        "scaleY": float(sy),
        "offsetX": float(ox),
        "offsetY": float(oy),
        # Clock zero for events: epoch ms of video frame 0.
        "startEpochMs": t0,
        # Refined: the flash's true position in the file tells us the real t0.
        "refinedStartEpochMs": float(calib["t"] + flash_ms / 2 - (used_at * 1000.0)),
        "fps": start.get("fps", 30),
    }
    (HERE / "calibration.json").write_text(json.dumps(out, indent=2), encoding="utf-8")

    print(json.dumps(out, indent=2))
    drift = out["refinedStartEpochMs"] - t0
    print(f"\nscale = ({sx:.4f}, {sy:.4f})   offset = ({ox:.1f}, {oy:.1f})")
    print(f"ffmpeg startup drift: {drift:.0f} ms  (events shifted by this)")
    if abs(sx - sy) > 0.01:
        print("WARNING: anisotropic scale -- the crop may be distorted.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
