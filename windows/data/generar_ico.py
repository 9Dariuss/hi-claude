"""Genera hi-claude.ico (16…256 px) con el mismo dibujo que linux/data/icons/generar_iconos.py.

En Windows no hay rsvg-convert ni cairo a mano, así que el estallido-mano se dibuja con Pillow:

    python generar_ico.py      (escribe ../hi_claude/hi-claude.ico)
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw

S = 8                      # sobremuestreo: se dibuja a 1024 px y se reduce
SIZE = 128 * S
ORANGE = (0xd9, 0x77, 0x57, 255)

# (ángulo desde la vertical, largo, grosor): igual que en generar_iconos.py
RAYS = [(-34, 50, 10), (-12, 58, 10.5), (10, 55, 10.5), (31, 45, 10),   # dedos
        (-78, 38, 10),                                                   # pulgar
        (62, 22, 9), (95, 25, 9), (125, 27, 9), (152, 28, 9.5), (180, 28, 9.5),
        (208, 27, 9), (236, 25, 9), (-108, 24, 9)]                       # palma
MOTION = [(34, 62, 72), (54, 58, 69), (74, 56, 65)]


def line(draw, p1, p2, width, color):
    draw.line([p1, p2], fill=color, width=round(width))
    r = width / 2
    for x, y in (p1, p2):  # extremos redondeados
        draw.ellipse([x - r, y - r, x + r, y + r], fill=color)


def burst_hand(draw, cx, cy, s, color, rot=-12):
    k = S
    rot = math.radians(rot)

    def turn(x, y):  # rotate(rot cx cy) del SVG
        dx, dy = x - cx, y - cy
        return (cx + dx * math.cos(rot) - dy * math.sin(rot), cy + dx * math.sin(rot) + dy * math.cos(rot))

    r = 15 * s
    draw.ellipse([(cx - r) * k, (cy - r) * k, (cx + r) * k, (cy + r) * k], fill=color)
    for ang, ln, w in RAYS:
        a = math.radians(ang)
        x2, y2 = turn(cx + math.sin(a) * ln * s, cy - math.cos(a) * ln * s)
        line(draw, (cx * k, cy * k), (x2 * k, y2 * k), w * s * k, color)
    ox, oy = cx + 2 * s, cy - 4 * s
    for ang, r1, r2 in MOTION:
        a = math.radians(ang)
        line(draw, ((ox + math.sin(a) * r1 * s) * k, (oy - math.cos(a) * r1 * s) * k),
             ((ox + math.sin(a) * r2 * s) * k, (oy - math.cos(a) * r2 * s) * k), 5.5 * s * k, color)


def icon() -> Image.Image:
    img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    k = S
    draw.rounded_rectangle([8 * k, 12 * k, 120 * k, 120 * k], radius=28 * k, fill=(0xcd, 0xbc, 0xa8, 255))
    # placa crema con degradado vertical (#faf6f0 → #efe6da)
    plate = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    grad = ImageDraw.Draw(plate)
    top, bottom = (0xfa, 0xf6, 0xf0), (0xef, 0xe6, 0xda)
    for y in range(8 * k, 116 * k):
        t = (y - 8 * k) / (108 * k)
        grad.line([(0, y), (SIZE, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,))
    mask = Image.new("L", (SIZE, SIZE), 0)
    ImageDraw.Draw(mask).rounded_rectangle([8 * k, 8 * k, 120 * k, 116 * k], radius=28 * k, fill=255)
    img.paste(plate, (0, 0), mask)
    burst_hand(draw, 58, 70, 0.78, ORANGE)
    return img


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "hi_claude" / "hi-claude.ico"
    big = icon().resize((256, 256), Image.LANCZOS)
    big.save(out, sizes=[(16, 16), (20, 20), (24, 24), (32, 32), (40, 40), (48, 48), (64, 64), (128, 128), (256, 256)])
    big.save(out.with_suffix(".png"))
    print(out)
