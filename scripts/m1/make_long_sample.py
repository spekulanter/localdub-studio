"""Build a ~5 minute test video by concatenating the clips in samples/ (re-encoded to 720p).

The content repeats, so this tests duration, memory and stability, not translation variety.
"""

from __future__ import annotations

import sys
from pathlib import Path

from localdub.core.media.ffmpeg import FFmpeg

TARGET_S = 300.0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    ff = FFmpeg()
    clips = sorted(p for p in Path("samples").glob("*.mp4") if not p.name.startswith("long_"))
    if not clips:
        print("No clips in samples/")
        return 1
    durations = {p: ff.probe(p).duration for p in clips}
    chosen: list[Path] = []
    total = 0.0
    while total < TARGET_S:
        for p in clips:
            chosen.append(p)
            total += durations[p]
            if total >= TARGET_S:
                break
    args: list[str | Path] = []
    for p in chosen:
        args += ["-i", p]
    n = len(chosen)
    parts = "".join(
        f"[{i}:v:0]scale=1280:720:force_original_aspect_ratio=decrease,"
        f"pad=1280:720:(ow-iw)/2:(oh-ih)/2,fps=25,format=yuv420p,setsar=1[v{i}];"
        f"[{i}:a:0]aresample=48000,aformat=channel_layouts=stereo[a{i}];"
        for i in range(n)
    )
    concat = "".join(f"[v{i}][a{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=1[v][a]"
    out = Path("samples/long_5min_test.mp4")
    encode = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac"]
    ff.run([*args, "-filter_complex", parts + concat, "-map", "[v]", "-map", "[a]", *encode, out])
    print(out, f"{ff.probe(out).duration:.1f}s from {n} clips, {out.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
