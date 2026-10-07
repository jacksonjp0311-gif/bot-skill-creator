"""Draw the Bot Skill Creator mark as a PNG and a Windows icon. No third-party packages."""
from __future__ import annotations
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs' / 'assets'


def sd_round_rect(px, py, x, y, w, h, radius):
    half_w = w / 2 - radius
    half_h = h / 2 - radius
    dx = abs(px - (x + w / 2)) - half_w
    dy = abs(py - (y + h / 2)) - half_h
    outside = (max(dx, 0) ** 2 + max(dy, 0) ** 2) ** 0.5
    return outside + min(max(dx, dy), 0) - radius


def sd_circle(px, py, cx, cy, radius):
    return ((px - cx) ** 2 + (py - cy) ** 2) ** 0.5 - radius


def cover(distance):
    if distance <= -0.6:
        return 1.0
    if distance >= 0.6:
        return 0.0
    return max(0.0, min(1.0, 0.5 - distance))


def composite(base, color, amount):
    if amount <= 0:
        return base
    src_r, src_g, src_b, src_a = color
    amount *= src_a
    keep = 1 - amount
    return (
        base[0] * keep + src_r * amount,
        base[1] * keep + src_g * amount,
        base[2] * keep + src_b * amount,
        base[3] * keep + amount,
    )


def pixel(px, py, scale):
    """One sample in 64-unit logo space."""
    x = px / scale
    y = py / scale
    color = (0.0, 0.0, 0.0, 0.0)
    shapes = (
        (sd_round_rect(x, y, 0, 0, 64, 64, 16), (36, 24, 51, 1)),
        (sd_round_rect(x, y, 30.75, 11, 2.5, 7, 1.25), (196, 182, 255, 1)),
        (sd_circle(x, y, 32, 10, 2.35), (244, 240, 255, 1)),
        (sd_round_rect(x, y, 16, 18, 32, 30, 12), (109, 90, 230, 1)),
        (sd_round_rect(x, y, 12.5, 29, 3.5, 8, 1.75), (196, 182, 255, 1)),
        (sd_round_rect(x, y, 48, 29, 3.5, 8, 1.75), (196, 182, 255, 1)),
        (sd_round_rect(x, y, 22, 28, 20, 9, 4.5), (20, 15, 34, 1)),
        (sd_round_rect(x, y, 25, 30.5, 6.5, 4, 2), (247, 244, 255, 1)),
        (sd_circle(x, y, 37.5, 32.5, 1.7), (126, 224, 184, 1)),
    )
    for distance, ink in shapes:
        color = composite(color, ink, cover(distance * scale))
    return tuple(max(0, min(255, round(channel))) for channel in color)


def raster(size):
    step = 4 if size <= 64 else 2
    buffer = bytearray(size * size * 4)
    for y in range(size):
        for x in range(size):
            total = [0, 0, 0, 0]
            for oy in range(step):
                for ox in range(step):
                    sample = pixel((x * step + ox + 0.5) * (64 / (size * step)),
                                   (y * step + oy + 0.5) * (64 / (size * step)), 1)
                    for index, channel in enumerate(sample):
                        total[index] += channel
            count = step * step
            start = (y * size + x) * 4
            buffer[start:start + 4] = bytes(channel // count for channel in total)
    return bytes(buffer)


def png(size, rgba):
    def chunk(tag, data):
        return struct.pack('>I', len(data)) + tag + data + struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF)

    rows = b''.join(b'\x00' + rgba[y * size * 4:(y + 1) * size * 4] for y in range(size))
    header = struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', header) + chunk(b'IDAT', zlib.compress(rows, 9)) + chunk(b'IEND', b'')


def ico(images):
    header = struct.pack('<HHH', 0, 1, len(images))
    offset = 6 + 16 * len(images)
    entries = b''
    body = b''
    for size, blob in images:
        entries += struct.pack('<BBBBHHII', size if size < 256 else 0, size if size < 256 else 0, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
        body += blob
    return header + entries + body


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    images = []
    for size in (16, 32, 48, 256):
        blob = png(size, raster(size))
        images.append((size, blob))
        if size == 256:
            (OUT / 'bot-skill-creator.png').write_bytes(blob)
    (OUT / 'bot-skill-creator.ico').write_bytes(ico(images))


if __name__ == '__main__':
    main()
