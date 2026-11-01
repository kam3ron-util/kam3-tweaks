"""Build original Kam3 Tweaks green K3 mark assets and multi-size Windows icon."""
from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIZES = (16, 24, 32, 48, 64, 128, 256)
BG = (21, 26, 29, 255)
SCREEN = (32, 39, 42, 255)
GREEN = (169, 232, 50, 255)
SS = 3


def rounded_rect(buf, dim, box, radius, color):
    x0, y0, x1, y1 = box
    radius = min(radius, (x1 - x0) / 2, (y1 - y0) / 2)
    for y in range(max(0, int(y0)), min(dim, math.ceil(y1))):
        for x in range(max(0, int(x0)), min(dim, math.ceil(x1))):
            cx = min(max(x, x0 + radius), x1 - radius)
            cy = min(max(y, y0 + radius), y1 - radius)
            if (x - cx) ** 2 + (y - cy) ** 2 <= radius**2:
                i = (y * dim + x) * 4
                buf[i:i + 4] = bytes(color)


def line(buf, dim, a, b, width, color):
    ax, ay = a
    bx, by = b
    r = width / 2
    x0, x1 = max(0, int(min(ax, bx) - r)), min(dim, math.ceil(max(ax, bx) + r))
    y0, y1 = max(0, int(min(ay, by) - r)), min(dim, math.ceil(max(ay, by) + r))
    dx, dy = bx - ax, by - ay
    denom = dx * dx + dy * dy or 1
    for y in range(y0, y1):
        for x in range(x0, x1):
            t = min(1, max(0, ((x - ax) * dx + (y - ay) * dy) / denom))
            if (x - (ax + t * dx)) ** 2 + (y - (ay + t * dy)) ** 2 <= r * r:
                i = (y * dim + x) * 4
                buf[i:i + 4] = bytes(color)


def triangle(buf, dim, pts, color):
    (x1, y1), (x2, y2), (x3, y3) = pts
    for y in range(max(0, int(min(y1, y2, y3))), min(dim, math.ceil(max(y1, y2, y3)))):
        for x in range(max(0, int(min(x1, x2, x3))), min(dim, math.ceil(max(x1, x2, x3)))):
            d1 = (x - x2) * (y1 - y2) - (x1 - x2) * (y - y2)
            d2 = (x - x3) * (y2 - y3) - (x2 - x3) * (y - y3)
            d3 = (x - x1) * (y3 - y1) - (x3 - x1) * (y - y1)
            if not ((d1 < 0 or d2 < 0 or d3 < 0) and (d1 > 0 or d2 > 0 or d3 > 0)):
                i = (y * dim + x) * 4
                buf[i:i + 4] = bytes(color)


def raster(size):
    dim = size * SS
    k = dim / 256
    cv = lambda x, y: (x * k, y * k)
    buf = bytearray(dim * dim * 4)
    rounded_rect(buf, dim, (12*k, 12*k, 244*k, 244*k), 42*k, BG)
    rounded_rect(buf, dim, (36*k, 36*k, 220*k, 220*k), 28*k, SCREEN)
    # Compact geometric K3 monogram. The heavy strokes remain legible at 16 px.
    for a, b, width in [((77, 65), (77, 191), 17), ((83, 128), (151, 67), 17),
                        ((83, 128), (151, 189), 17), ((150, 72), (193, 72), 15),
                        ((193, 72), (171, 126), 15), ((171, 126), (193, 183), 15),
                        ((193, 183), (150, 183), 15)]:
        line(buf, dim, cv(*a), cv(*b), width*k, GREEN)
    # Downsample a fixed high-resolution drawing for clean 16-256px frames.
    out = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            for c in range(4):
                total = 0
                for yy in range(SS):
                    for xx in range(SS):
                        total += buf[(((y*SS+yy)*dim)+(x*SS+xx))*4+c]
                out[(y*size+x)*4+c] = total // (SS*SS)
    return bytes(out)


def png(size, rgba):
    def chunk(kind, payload):
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xffffffff)
    raw = b"".join(b"\0" + rgba[y*size*4:(y+1)*size*4] for y in range(size))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">2I5B", size, size, 8, 6, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def main():
    frames = [(size, png(size, raster(size))) for size in SIZES]
    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = len(header) + 16 * len(frames)
    entries, payloads = [], []
    for size, data in frames:
        entries.append(struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(data), offset))
        payloads.append(data)
        offset += len(data)
    (ROOT / "Kam3Tweaks.ico").write_bytes(header + b"".join(entries) + b"".join(payloads))
    assets=ROOT/"assets"
    assets.mkdir(exist_ok=True)
    (assets/"Kam3Tweaks.png").write_bytes(png(256,raster(256)))
    print(f"Wrote {ROOT / 'Kam3Tweaks.ico'} with {', '.join(map(str, SIZES))}px frames")


if __name__ == "__main__":
    main()
