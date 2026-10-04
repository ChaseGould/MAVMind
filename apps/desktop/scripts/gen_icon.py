#!/usr/bin/env python3
"""Generate the MAVMind app icon (stdlib only: zlib + struct).

Writes a 1024x1024 RGBA PNG. Then run `npx tauri icon <png>` to produce the
platform icon set in src-tauri/icons/.

    python scripts/gen_icon.py app-icon.png
"""
import math
import struct
import sys
import zlib

SIZE = 1024
BG_TOP = (24, 34, 46)
BG_BOTTOM = (9, 13, 18)
CYAN = (54, 209, 255)
YELLOW = (255, 212, 0)

# Vehicle arrow (same shape as the map marker), in a -20..20 box.
ARROW = [(0, -17), (11, 13), (0, 7), (-11, 13)]


def png(width, height, rows):
    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes(r) for r in rows)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def seg_dist(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - ax - t * dx, py - ay - t * dy)


def poly_sdf(px, py, pts):
    d = min(seg_dist(px, py, *pts[i], *pts[(i + 1) % len(pts)]) for i in range(len(pts)))
    inside = False
    j = len(pts) - 1
    for i in range(len(pts)):
        xi, yi = pts[i]
        xj, yj = pts[j]
        if (yi > py) != (yj > py) and px < (xj - xi) * (py - yi) / (yj - yi) + xi:
            inside = not inside
        j = i
    return -d if inside else d


def rounded_box_sdf(px, py, cx, cy, half, r):
    qx = abs(px - cx) - (half - r)
    qy = abs(py - cy) - (half - r)
    return math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - r


def cov(d):
    """Signed distance -> pixel coverage (1px antialiasing)."""
    return max(0.0, min(1.0, 0.5 - d))


def over(dst, src, a):
    return tuple(s * a + d * (1 - a) for s, d in zip(src, dst))


def main(out):
    c = SIZE / 2
    scale = 17.0
    arrow = [(c + x * scale, c + 20 + y * scale) for x, y in ARROW]
    rows = []
    for y in range(SIZE):
        row = bytearray()
        t = y / (SIZE - 1)
        bg = tuple(BG_TOP[i] * (1 - t) + BG_BOTTOM[i] * t for i in range(3))
        for x in range(SIZE):
            px, py = x + 0.5, y + 0.5
            a_box = cov(rounded_box_sdf(px, py, c, c, c - 24, 200))
            if a_box <= 0:
                row += b"\x00\x00\x00\x00"
                continue
            col = bg
            r = math.hypot(px - c, py - c)
            # Outer ring
            col = over(col, CYAN, 0.9 * cov(abs(r - 400) - 14))
            # Heading ticks on the ring (every 30 degrees)
            ang = math.degrees(math.atan2(py - c, px - c)) % 30
            if 340 < r < 380 and (ang < 1.6 or ang > 28.4):
                col = over(col, CYAN, 0.75)
            # Arrow with a dark outline
            d = poly_sdf(px, py, arrow)
            col = over(col, (10, 12, 16), cov(d - 18))
            col = over(col, YELLOW, cov(d))
            row += bytes((int(col[0]), int(col[1]), int(col[2]), int(round(255 * a_box))))
        rows.append(row)
    with open(out, "wb") as f:
        f.write(png(SIZE, SIZE, rows))
    print(f"wrote {out}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "app-icon.png")
