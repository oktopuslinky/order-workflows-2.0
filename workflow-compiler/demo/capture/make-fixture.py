"""Build a synthetic take so the Remotion edit can be proven BEFORE the real
20-minute recording exists.

Generates a fake desktop recording, a calibration, and an events log carrying
every mark scenes.ts expects. If the video renders against this, the loader,
scene resolution, cursor projection and zoom math are all sound -- and any
failure during the real take is a capture problem, not a code problem.

Run: python demo/capture/make-fixture.py
"""

from __future__ import annotations

import json
import pathlib
import subprocess

HERE = pathlib.Path(__file__).parent
PUBLIC = HERE.parent / "video" / "public"

# Pretend the desktop is 1920x1080 and Chrome's viewport sits at (0, 120)
# at 1600x880 -- roughly what the real launch geometry produces.
VIDEO_W, VIDEO_H = 1920, 1080
VP_W, VP_H = 1600, 880
VP_X, VP_Y = 0, 120
FPS = 15  # must match record.ps1 $Fps
T0 = 1_700_000_000_000  # arbitrary epoch ms

# The beats scenes.ts cuts on, in order, with a duration each (seconds).
#
# The LLM waits are the MEASURED numbers from the verified headless run (see
# HANDOFF "Verified ground truth") -- not guesses. They dominate the take, so
# getting them right is what makes this fixture predict the real runtime.
# The interactive beats are estimates; the real ones will differ, and the speeds
# in scenes.ts get re-tuned against the actual take.
# Durations are how long the beat ITSELF lasts, i.e. the gap until the next mark.
# LLM waits are the numbers measured against live Nemotron on 2026-07-13; interactive
# beats are estimates. After a real take, re-tune scenes.ts against the real gaps.
BEATS = [
    ("upload", 15),
    ("compile-start", 402),     # measured: fresh compile
    ("compile-done", 4),
    ("workspace", 20),
    ("views", 40),
    ("cvpa-start", 170),        # measured: phase classification
    ("cvpa-done", 30),
    ("gate", 3),
    ("validate0-start", 75),    # measured: first validate (Approve needs one)
    ("validate0-done", 25),
    ("refuse", 14),             # 1x: the gate refuses -- unconfirmed dependencies
    ("confirm", 60),            # tick every dep + trigger, answer R4
    ("break", 40),              # rename order-fulfilment's `order_id` input
    ("validate-start", 160),    # measured
    ("validate-done", 14),      # 1x: the blocking finding names the mapping
    ("fix", 30),
    ("revalidate-start", 110),  # measured
    ("revalidate-done", 20),
    ("approve-start", 360),     # measured: full generation, all three workflows
    ("approve-done", 15),
    ("results", 30),
    ("code", 30),
    ("download", 12),
    ("end", 0),
]


def main() -> None:
    PUBLIC.mkdir(parents=True, exist_ok=True)
    total_s = sum(d for _, d in BEATS)

    video = PUBLIC / "fixture.mp4"
    print(f"rendering {total_s}s synthetic desktop -> {video.name}")
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", f"testsrc2=size={VIDEO_W}x{VIDEO_H}:rate={FPS}:duration={total_s}",
            # A throwaway test pattern -- quality is irrelevant, and the take is
            # ~26 minutes, so a visually-lossless encode would cost gigabytes for
            # nothing. crf 32 keeps it small and quick to seek during probes.
            "-c:v", "libx264", "-preset", "ultrafast", "-crf", "32", "-pix_fmt", "yuv420p",
            str(video),
        ],
        check=True,
        capture_output=True,
    )

    events: list[dict] = []
    t = T0

    # Calibration flash at the very top of the take.
    events.append(
        {
            "type": "calibrate",
            "t": t,
            "tEnd": t + 700,
            "viewport": {"w": VP_W, "h": VP_H},
            "dpr": 1,
            "markers": [
                {"id": "tl", "cx": 70, "cy": 70},
                {"id": "tr", "cx": VP_W - 70, "cy": 70},
                {"id": "bl", "cx": 70, "cy": VP_H - 70},
                {"id": "br", "cx": VP_W - 70, "cy": VP_H - 70},
            ],
        }
    )

    for name, dur in BEATS:
        events.append({"type": "mark", "t": t, "name": name, "url": "/"})
        # A click partway through each beat, so the cursor has somewhere to go.
        if dur > 3:
            events.append(
                {
                    "type": "click",
                    "t": t + int(dur * 1000 * 0.4),
                    "label": f"{name} button",
                    "tag": "button",
                    "url": "/",
                    "rect": {
                        "x": 200 + (hash(name) % 900),
                        "y": 150 + (hash(name) % 500),
                        "w": 160,
                        "h": 44,
                    },
                }
            )
        t += dur * 1000

    (PUBLIC / "events.json").write_text(json.dumps(events, indent=2), encoding="utf-8")

    calibration = {
        "video": "fixture.mp4",
        "videoSize": {"w": VIDEO_W, "h": VIDEO_H},
        "viewport": {"w": VP_W, "h": VP_H},
        "dpr": 1,
        "scaleX": 1.0,
        "scaleY": 1.0,
        "offsetX": float(VP_X),
        "offsetY": float(VP_Y),
        "refinedStartEpochMs": float(T0),
        "fps": FPS,
    }
    (PUBLIC / "calibration.json").write_text(json.dumps(calibration, indent=2), encoding="utf-8")

    print(f"wrote {PUBLIC/'events.json'} ({len(events)} events)")
    print(f"wrote {PUBLIC/'calibration.json'}")
    print("\nNow: cd demo/video && npx remotion still Rough out/probe.png --frame=300 --scale=0.4")


if __name__ == "__main__":
    main()
