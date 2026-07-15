"""
Rebuild an mp4 whose moov atom was never written.

ffmpeg's mp4 muxer keeps the index (moov) in memory and only writes it on a clean
exit. `record.ps1 -Stop` used `taskkill`, ffmpeg died without writing it, and the
result is ftyp + mdat with no index -- 159 MB of perfectly good H.264 that no
player will touch.

The frames themselves are fine. Inside mdat they are stored in AVCC form: each
NAL unit prefixed by a 4-byte big-endian length. Annex-B (a raw .h264 elementary
stream) instead separates NALs with 00 00 00 01 start codes, and carries SPS/PPS
inline rather than in the (missing) avcC box.

So: lift SPS/PPS from a reference clip encoded with identical settings, rewrite
the length prefixes as start codes, and hand the elementary stream back to ffmpeg
to remux. Frame *content* is untouched -- this is a container repair, not a
re-encode.
"""

import struct
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
BROKEN = HERE / "raw-app.mp4"
REF = HERE / "ref.mp4"
ANNEXB = HERE / "recovered.h264"
FIXED = HERE / "raw-app-fixed.mp4"
FPS = 30


def find_box(buf: bytes, target: bytes) -> bytes | None:
    """Depth-first hunt for a box's payload. The reference file is small, and the
    nesting (moov/trak/mdia/minf/stbl/stsd/avc1/avcC) is deep enough that walking
    it properly would be more code than simply scanning for the fourcc."""
    i = buf.find(target)
    if i == -1:
        return None
    size = struct.unpack(">I", buf[i - 4 : i])[0]
    return buf[i + 4 : i - 4 + size]


def sps_pps_from_avcc(avcc: bytes) -> tuple[list[bytes], int]:
    """avcC: [0]=version [1..3]=profile/comp/level [4]=0xFC|lengthSizeMinusOne
    [5]=0xE0|numSPS, then len-prefixed SPS, then numPPS, then len-prefixed PPS."""
    nal_len = (avcc[4] & 0x03) + 1
    out: list[bytes] = []
    p = 5
    num_sps = avcc[p] & 0x1F
    p += 1
    for _ in range(num_sps):
        n = struct.unpack(">H", avcc[p : p + 2])[0]
        p += 2
        out.append(avcc[p : p + n])
        p += n
    num_pps = avcc[p]
    p += 1
    for _ in range(num_pps):
        n = struct.unpack(">H", avcc[p : p + 2])[0]
        p += 2
        out.append(avcc[p : p + n])
        p += n
    return out, nal_len


def mdat_payload(buf: bytes) -> bytes:
    """Return the bytes inside mdat. A still-recording ffmpeg leaves the size
    field as 0 ('to EOF') or 1 (64-bit extended), so trust the type, not the size."""
    off = 0
    while off + 8 <= len(buf):
        size = struct.unpack(">I", buf[off : off + 4])[0]
        typ = buf[off + 4 : off + 8]
        header = 8
        if size == 1:
            size = struct.unpack(">Q", buf[off + 8 : off + 16])[0]
            header = 16
        elif size == 0:
            size = len(buf) - off
        if typ == b"mdat":
            return buf[off + header : off + size]
        off += size
    raise SystemExit("no mdat box found -- nothing to recover")


def main() -> None:
    if not BROKEN.exists() or not REF.exists():
        raise SystemExit("need both raw-app.mp4 (broken) and ref.mp4 (reference)")

    avcc = find_box(REF.read_bytes(), b"avcC")
    if not avcc:
        raise SystemExit("no avcC in reference -- cannot source SPS/PPS")
    params, nal_len = sps_pps_from_avcc(avcc)
    print(f"reference: {len(params)} parameter sets, NAL length prefix = {nal_len} bytes")

    payload = mdat_payload(BROKEN.read_bytes())
    print(f"mdat payload: {len(payload):,} bytes")

    start = b"\x00\x00\x00\x01"
    chunks = [start + p for p in params]  # SPS/PPS must lead the stream

    pos, nals, bad = 0, 0, 0
    n = len(payload)
    while pos + nal_len <= n:
        size = int.from_bytes(payload[pos : pos + nal_len], "big")
        pos += nal_len
        # A truncated final write, or any desync, shows up as a nonsense length.
        if size <= 0 or pos + size > n:
            bad += 1
            break
        chunks.append(start + payload[pos : pos + size])
        pos += size
        nals += 1

    print(f"recovered {nals:,} NAL units" + (f" (stopped early at byte {pos:,})" if bad else ""))
    if nals == 0:
        raise SystemExit("no NAL units parsed -- mdat is not AVCC as assumed")

    ANNEXB.write_bytes(b"".join(chunks))
    print(f"wrote {ANNEXB.name} ({ANNEXB.stat().st_size:,} bytes)")

    cmd = [
        "ffmpeg", "-v", "error", "-y",
        "-f", "h264", "-framerate", str(FPS), "-i", str(ANNEXB),
        "-c", "copy", str(FIXED),
    ]
    print("remuxing:", " ".join(cmd))
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        raise SystemExit("remux failed")
    print(f"wrote {FIXED.name} ({FIXED.stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
