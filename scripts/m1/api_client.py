"""Tiny API client for manual and acceptance runs against a running `localdub serve`.

Usage: uv run python scripts/m1/api_client.py upload <video> [--mute] [--no-start]
       uv run python scripts/m1/api_client.py watch <job_id>
       uv run python scripts/m1/api_client.py fetch <project_id> <out_dir>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

BASE = "http://127.0.0.1:8765"


def upload(video: Path, mute: bool, start: bool) -> None:
    data = {
        "original_audio": "mute" if mute else "duck",
        "start": "true" if start else "false",
    }
    with video.open("rb") as fh, httpx.Client(timeout=600) as c:
        r = c.post(f"{BASE}/api/projects", files={"file": (video.name, fh, "video/mp4")}, data=data)
    r.raise_for_status()
    print(json.dumps(r.json(), ensure_ascii=False))


def watch(job_id: int, quiet: bool) -> int:
    last = ""
    with httpx.Client(timeout=None) as c, c.stream("GET", f"{BASE}/api/jobs/{job_id}/events") as r:
        for line in r.iter_lines():
            if not line.startswith("data: "):
                continue
            job = json.loads(line[6:])
            row = (
                f"{job['status']:9} {job['stage']:9} {job['progress'] * 100:5.1f}% {job['message']}"
            )
            if row != last and not quiet:
                print(row, flush=True)
            last = row
            if job["status"] in ("done", "failed", "cancelled"):
                print(json.dumps(job, ensure_ascii=False))
                return 0 if job["status"] == "done" else 1
    return 2


def fetch(pid: int, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=600) as c:
        for kind in ("video", "srt", "srt_en"):
            r = c.get(f"{BASE}/api/projects/{pid}/files/{kind}")
            r.raise_for_status()
            name = r.headers["content-disposition"].split("filename*=utf-8''")[-1]
            from urllib.parse import unquote

            (out / unquote(name)).write_bytes(r.content)
            print(unquote(name), len(r.content))


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    up = sub.add_parser("upload")
    up.add_argument("video", type=Path)
    up.add_argument("--mute", action="store_true")
    up.add_argument("--no-start", action="store_true")
    w = sub.add_parser("watch")
    w.add_argument("job_id", type=int)
    w.add_argument("--quiet", action="store_true")
    f = sub.add_parser("fetch")
    f.add_argument("project_id", type=int)
    f.add_argument("out", type=Path)
    a = ap.parse_args()
    if a.cmd == "upload":
        upload(a.video, a.mute, not a.no_start)
    elif a.cmd == "watch":
        return watch(a.job_id, a.quiet)
    else:
        fetch(a.project_id, a.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
