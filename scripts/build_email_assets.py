"""Build the PNG assets the booking email references (static/email/*.png). Run once after changing a shape:

    python scripts/build_email_assets.py

Email clients do not render SVG (Gmail, Outlook), so the icons and the hero background ship as PNGs at 2x, served by
the app from /static/email/. Pillow is only needed here, never at send time. Everything is drawn 4x larger than the
2x output and downscaled, which gives clean anti-aliased edges.
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "static" / "email"
SS = 4                                   # supersampling on top of the 2x output
NAVY, INK, STATUS = (16, 30, 80), (20, 34, 79), (35, 59, 145)
LAVENDER, WHITE = (230, 235, 255), (255, 255, 255)


def rgba(c, a=255):
    return (*c, a)


def canvas(px: int, h: int | None = None):
    img = Image.new("RGBA", (px * 2 * SS, (h or px) * 2 * SS), (0, 0, 0, 0))
    return img, ImageDraw.Draw(img), 2 * SS


def save(img: Image.Image, name: str, px: int, h: int | None = None):
    img.resize((px * 2, (h or px) * 2), Image.LANCZOS).save(OUT / name, optimize=True)


def star_points(cx, cy, r, steps=160):
    """Four-point star with concave sides (an astroid): the Champions Group mark."""
    pts = []
    for i in range(steps):
        t = 2 * math.pi * i / steps
        pts.append((cx + r * math.cos(t) ** 3, cy + r * math.sin(t) ** 3))
    return pts


# ---------------------------------------------------------------- line icons (24-unit grid, like the widget's icons)
def icon_calendar(d, ox, oy, u, col, w):
    d.rounded_rectangle([ox + 3 * u, oy + 5 * u, ox + 21 * u, oy + 21 * u], radius=2.5 * u, outline=col, width=w)
    d.line([ox + 3 * u, oy + 10 * u, ox + 21 * u, oy + 10 * u], fill=col, width=w)
    for x in (8, 16):
        d.line([ox + x * u, oy + 2.5 * u, ox + x * u, oy + 7 * u], fill=col, width=w)
    for x, y in ((8, 14), (12, 14), (16, 14), (8, 17.5), (12, 17.5)):
        r = 1.0 * u
        d.ellipse([ox + x * u - r, oy + y * u - r, ox + x * u + r, oy + y * u + r], fill=col)


def icon_clock(d, ox, oy, u, col, w):
    d.ellipse([ox + 3 * u, oy + 3 * u, ox + 21 * u, oy + 21 * u], outline=col, width=w)
    d.line([ox + 12 * u, oy + 7 * u, ox + 12 * u, oy + 12 * u, ox + 15.5 * u, oy + 14 * u], fill=col, width=w, joint="curve")


def icon_video(d, ox, oy, u, col, w):
    d.rounded_rectangle([ox + 2.5 * u, oy + 6.5 * u, ox + 15.5 * u, oy + 17.5 * u], radius=2.5 * u, outline=col, width=w)
    d.polygon([(ox + 15.5 * u, oy + 10.5 * u), (ox + 21.5 * u, oy + 7.5 * u), (ox + 21.5 * u, oy + 16.5 * u), (ox + 15.5 * u, oy + 13.5 * u)], outline=col, width=w)


def icon_user(d, ox, oy, u, col, w):
    d.ellipse([ox + 8 * u, oy + 3.5 * u, ox + 16 * u, oy + 11.5 * u], outline=col, width=w)
    d.arc([ox + 4.5 * u, oy + 14 * u, ox + 19.5 * u, oy + 28 * u], 180, 360, fill=col, width=w)


def icon_building(d, ox, oy, u, col, w):
    d.rounded_rectangle([ox + 5 * u, oy + 3 * u, ox + 19 * u, oy + 21 * u], radius=1.5 * u, outline=col, width=w)
    for x in (9, 15):
        for y in (7, 11, 15):
            d.rounded_rectangle([ox + (x - 1) * u, oy + (y - 0.9) * u, ox + (x + 1) * u, oy + (y + 0.9) * u], radius=0.4 * u, fill=col)
    d.rectangle([ox + 10.5 * u, oy + 17.5 * u, ox + 13.5 * u, oy + 21 * u], fill=col)


def icon_external(d, ox, oy, u, col, w):
    d.line([ox + 10 * u, oy + 5 * u, ox + 5 * u, oy + 5 * u, ox + 5 * u, oy + 19 * u, ox + 19 * u, oy + 19 * u, ox + 19 * u, oy + 14 * u], fill=col, width=w, joint="curve")
    d.line([ox + 13 * u, oy + 4 * u, ox + 20 * u, oy + 4 * u, ox + 20 * u, oy + 11 * u], fill=col, width=w, joint="curve")
    d.line([ox + 20 * u, oy + 4 * u, ox + 11 * u, oy + 13 * u], fill=col, width=w)


def badge(name: str, px: int, draw_icon, shape: str, icon_px: float, bg=LAVENDER, col=NAVY, stroke=1.7):
    img, d, k = canvas(px)
    size = px * k
    if shape == "circle":
        d.ellipse([0, 0, size - 1, size - 1], fill=rgba(bg))
    elif shape == "square":
        d.rounded_rectangle([0, 0, size - 1, size - 1], radius=size * 12 / 56, fill=rgba(bg))
    u = icon_px * k / 24
    off = (size - 24 * u) / 2
    draw_icon(d, off, off, u, rgba(col), max(1, round(stroke * u)))
    save(img, name, px)


def bare(name: str, px: int, draw_icon, col, stroke=2.0):
    img, d, k = canvas(px)
    u = px * k / 24
    draw_icon(d, 0, 0, u, rgba(col), max(1, round(stroke * u)))
    save(img, name, px)


def star(name: str, px: int, col, bg=None):
    img, d, k = canvas(px)
    size = px * k
    if bg:
        d.rounded_rectangle([0, 0, size - 1, size - 1], radius=size * 0.26, fill=rgba(bg))
        d.polygon(star_points(size / 2, size / 2, size * 0.30), fill=rgba(col))
    else:
        d.polygon(star_points(size / 2, size / 2, size * 0.48), fill=rgba(col))
    save(img, name, px)


# ---------------------------------------------------------------- hero background: navy-to-indigo with low-contrast curves
def hero(name: str, w: int = 600, h: int = 380):
    W, H = w * 2, h * 2
    base = Image.new("RGB", (W, H))
    stops = [(0.0, (7, 19, 45)), (0.55, (17, 31, 77)), (1.0, (41, 63, 145))]

    def lerp(a, b, t):
        return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))

    px = base.load()
    for y in range(H):
        for x in range(W):
            t = min(1.0, max(0.0, (x / W) * 0.78 + (1 - y / H) * 0.22))  # darkest on the left, lifting to the upper right
            for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
                if t <= p1:
                    px[x, y] = lerp(c0, c1, (t - p0) / (p1 - p0))
                    break
    img = base.convert("RGBA")

    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse([W * 0.62, -H * 0.55, W * 1.25, H * 0.55], fill=(86, 108, 204, 70))
    img = Image.alpha_composite(img, glow.filter(ImageFilter.GaussianBlur(W * 0.07)))

    # overlapping arcs along the right and lower-right edges, each a slightly different navy/indigo
    shapes = Image.new("RGBA", (W * SS, H * SS), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shapes)
    S = SS
    for (cx, cy, r, fill) in [
        (1.10, 1.25, 0.62, (58, 82, 170, 52)),
        (1.02, 1.42, 0.56, (24, 40, 98, 150)),
        (0.86, 1.62, 0.52, (36, 56, 128, 95)),
        (1.22, 0.92, 0.30, (70, 96, 188, 38)),
    ]:
        R = r * W * S
        sd.ellipse([cx * W * S - R, cy * H * S - R, cx * W * S + R, cy * H * S + R], fill=fill)
    for (cx, cy, r, a) in [(1.06, 1.30, 0.66, 60), (0.92, 1.50, 0.60, 42)]:
        R = r * W * S
        sd.ellipse([cx * W * S - R, cy * H * S - R, cx * W * S + R, cy * H * S + R], outline=(150, 170, 235, a), width=2 * S)
    img = Image.alpha_composite(img, shapes.resize((W, H), Image.LANCZOS))
    img.convert("RGB").save(OUT / name, optimize=True, quality=90)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    badge("ic-event.png", 56, icon_calendar, "square", 26)
    badge("ic-date.png", 36, icon_calendar, "circle", 18)
    badge("ic-time.png", 36, icon_clock, "circle", 18)
    badge("ic-platform.png", 36, icon_video, "circle", 18)
    badge("ic-user.png", 36, icon_user, "circle", 18)
    badge("ic-company.png", 36, icon_building, "circle", 18)
    bare("ic-status.png", 16, icon_calendar, STATUS, 2.0)
    bare("ic-external.png", 14, icon_external, WHITE, 2.2)
    star("brand-tile.png", 44, WHITE, bg=NAVY)
    star("star-white.png", 22, WHITE)
    star("star-navy.png", 20, NAVY)
    hero("hero.png")
    for p in sorted(OUT.glob("*.png")):
        print(f"{p.name:18} {p.stat().st_size:>7} bytes")


if __name__ == "__main__":
    main()
