"""Draw the LocalDub icon (rounded tile, audio waveform) into localdub/assets/localdub-orange.ico.

Pure numpy + zlib: no imaging library needed. Re-run to regenerate.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parents[1] / "localdub" / "assets" / "localdub-orange.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def draw(size: int) -> np.ndarray:
    s = size * 4  # supersample for smooth edges
    y, x = np.mgrid[0:s, 0:s].astype(np.float32)
    u, v = x / s, y / s
    img = np.zeros((s, s, 4), np.float32)
    # rounded square with a diagonal orange -> amber gradient
    r = 0.22
    cx = np.clip(u, r, 1 - r)
    cy = np.clip(v, r, 1 - r)
    inside = (u - cx) ** 2 + (v - cy) ** 2 <= r**2
    t = (u + v) / 2
    # the same orange as the interface (--accent #de4a1c, shading to amber like the in-app logo)
    top, bottom = np.array([222, 74, 28], np.float32), np.array([236, 130, 40], np.float32)
    rgb = top[None, None, :] * (1 - t[..., None]) + bottom[None, None, :] * t[..., None]
    img[..., :3] = rgb
    img[..., 3] = inside * 255
    # waveform bars in white: heights follow a dub-like envelope
    heights = [0.18, 0.34, 0.56, 0.74, 0.5, 0.64, 0.3, 0.16]
    n = len(heights)
    left, right = 0.17, 0.83
    pitch = (right - left) / n
    bar = pitch * 0.58
    for i, h in enumerate(heights):
        c = left + pitch * (i + 0.5)
        x0, x1 = c - bar / 2, c + bar / 2
        y0, y1 = 0.5 - h / 2, 0.5 + h / 2
        rr = bar / 2
        bx = np.clip(u, x0 + rr, x1 - rr)
        by = np.clip(v, y0 + rr, y1 - rr)
        m = ((u - bx) ** 2 + (v - by) ** 2 <= rr**2) & inside
        img[m, :3] = 255
    img = img.reshape(size, 4, size, 4, 4).mean(axis=(1, 3))
    return np.clip(img, 0, 255).astype(np.uint8)


def png(rgba: np.ndarray) -> bytes:
    h, w, _ = rgba.shape
    raw = b"".join(b"\x00" + rgba[i].tobytes() for i in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw, 9))
        + chunk(b"IEND", b"")
    )


def main() -> None:
    images = [png(draw(s)) for s in SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b""
    for size, data in zip(SIZES, images, strict=True):
        entries += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,
            0 if size >= 256 else size,
            0,
            0,
            1,
            32,
            len(data),
            offset,
        )
        offset += len(data)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(header + entries + b"".join(images))
    # a PNG preview for quick inspection
    (OUT.with_suffix(".png")).write_bytes(images[-1])
    print(f"wrote {OUT} ({OUT.stat().st_size} bytes, sizes {SIZES})")


if __name__ == "__main__":
    main()
