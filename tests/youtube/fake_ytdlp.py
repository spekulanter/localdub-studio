"""A stand-in for yt-dlp used by the tests: prints what the real one would, writes a file."""

import os
import sys
from pathlib import Path

args = sys.argv[1:]
mode = os.environ.get("FAKE_YTDLP_MODE", "ok")
out_dir = Path(args[args.index("-P") + 1])
template = args[args.index("-o") + 1]
if mode == "fail_age":
    print(
        "ERROR: [youtube] abc: Sign in to confirm your age. This video may be inappropriate",
        file=sys.stderr,
    )
    sys.exit(1)
if mode == "fail_bytes":
    sys.stderr.buffer.write(b"ERROR: video unavailable \xff\xfe broken bytes\n")
    sys.exit(1)
passes = [("  5.0%", " 50.0%", "100.0%")]
if mode == "two_streams":
    passes = [("  0.0%", " 60.0%", "100.0%"), ("  0.0%", " 50.0%", "100.0%")]
for pct in [p for group in passes for p in group]:
    print(f"__LD_PROGRESS__{pct}|1.5MiB/s|00:0{int(float(pct.strip('% ')) < 100)}", flush=True)
print("[Merger] Merging formats into x.mp4", flush=True)
target = out_dir / template.replace("%(ext)s", "mp4")
target.write_bytes(b"not really a video")
if mode == "odd_name":
    odd = out_dir / "Some Title [abc].mp4"
    target.replace(odd)
    target = odd
print(f"__LD_FILE__{target}", flush=True)
