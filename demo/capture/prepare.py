"""Post-capture: compress the raw recording and stage the take into the Remotion
project's public/ dir.

Two reasons this exists rather than pointing Remotion at the raw file:

1. Remotion copies public/ on *every* render. A raw ultrafast desktop capture is
   >1GB, which makes each iteration crawl. Screen content is mostly static, so a
   slower preset at a sane CRF cuts it by ~10x with no visible loss.
2. `-g 30` forces a keyframe every second. Remotion seeks constantly while
   scrubbing scenes; a sparse-keyframe file makes that seek-bound.

Run: python demo/capture/prepare.py --name app
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys

HERE = pathlib.Path(__file__).parent
PUBLIC = HERE.parent / "video" / "public"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="app")
    ap.add_argument("--crf", type=int, default=23)
    args = ap.parse_args()

    raw = HERE / f"raw-{args.name}.mp4"
    if not raw.exists():
        print(f"missing {raw}", file=sys.stderr)
        return 1

    PUBLIC.mkdir(parents=True, exist_ok=True)
    out = PUBLIC / f"{args.name}.mp4"

    raw_mb = raw.stat().st_size / 1e6
    print(f"compressing {raw.name} ({raw_mb:.0f} MB) -> public/{out.name} ...")

    subprocess.run(
        [
            "ffmpeg", "-y", "-i", str(raw),
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", str(args.crf),
            "-g", "30",            # keyframe every second: Remotion seeks a lot
            "-pix_fmt", "yuv420p",
            "-an",
            str(out),
        ],
        check=True,
        capture_output=True,
    )

    out_mb = out.stat().st_size / 1e6
    print(f"  {raw_mb:.0f} MB -> {out_mb:.0f} MB  ({raw_mb / max(out_mb, 0.1):.1f}x smaller)")

    # calibration.json names the video file the composition loads; repoint it at
    # the compressed copy (identical geometry, so the transform still holds).
    cal_src = HERE / "calibration.json"
    if cal_src.exists():
        cal = json.loads(cal_src.read_text(encoding="utf-8"))
        cal["video"] = out.name
        (PUBLIC / "calibration.json").write_text(json.dumps(cal, indent=2), encoding="utf-8")
        print("staged calibration.json")

    events_src = HERE / "events.json"
    if events_src.exists():
        shutil.copy(events_src, PUBLIC / "events.json")
        print("staged events.json")

    # The synthetic fixture is huge and no longer needed once real footage lands.
    fixture = PUBLIC / "fixture.mp4"
    if fixture.exists():
        fixture.unlink()
        print("removed fixture.mp4")

    return 0


if __name__ == "__main__":
    sys.exit(main())
