#!/usr/bin/env python3
"""Generate the macOS DMG window background for Mixed in P.

Produces a 600x400 `dmg-background.png` (plus a 1200x800 `@2x` for Retina)
matching the app's dark theme + neon-yellow accent. The drag-to-Applications
window in `create-dmg` places the app icon at (150, 200) and the Applications
shortcut at (450, 200); this art fills the gap with branding and an arrow.

Run from the repo root:  ./venv/bin/python scripts/make_dmg_background.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# --- theme (from src/gui/styles/theme.py, default palette) -----------------
BG_TOP = (32, 32, 36)      # subtle gradient top
BG_BOTTOM = (18, 18, 21)   # subtle gradient bottom
ACCENT = (240, 255, 0)     # NEON_YELLOW
CHROME = (176, 176, 176)   # TEXT_SECONDARY

SCALE = 2                  # render at 2x, then downscale the 1x copy
W, H = 600, 400

REPO = Path(__file__).resolve().parent.parent
LOGO = REPO / "src" / "gui" / "assets" / "logo_title.png"
OUT_1X = REPO / "dmg-background.png"
OUT_2X = REPO / "dmg-background@2x.png"

# create-dmg icon centres (1x space); arrow lives in the gap between them
APP_X, APP_X_R = 150, 450
ICON_Y = 200


def _font(size):
    """Best-effort system font; falls back to PIL default."""
    for path in (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _centred(draw, text, cx, y, font, fill):
    l, t, r, b = draw.textbbox((0, 0), text, font=font)
    draw.text((cx - (r - l) / 2, y), text, font=font, fill=fill)


def render():
    s = SCALE
    img = Image.new("RGB", (W * s, H * s), BG_BOTTOM)
    draw = ImageDraw.Draw(img)

    # vertical gradient background
    for y in range(H * s):
        t = y / (H * s)
        draw.line(
            [(0, y), (W * s, y)],
            fill=tuple(round(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM)),
        )

    # logo, centred near the top
    if LOGO.exists():
        logo = Image.open(LOGO).convert("RGBA")
        target_w = 300 * s
        target_h = round(logo.height * target_w / logo.width)
        logo = logo.resize((target_w, target_h), Image.LANCZOS)
        img.paste(logo, ((W * s - target_w) // 2, 34 * s), logo)

    # tagline under the logo
    _centred(draw, "Drag the app into your Applications folder",
             W * s / 2, 126 * s, _font(15 * s), CHROME)

    # accent arrow in the gap between the two icons, at icon centre height
    y = ICON_Y * s
    x0, x1 = 222 * s, 378 * s
    draw.line([(x0, y), (x1, y)], fill=ACCENT, width=6 * s)
    head = 16 * s
    draw.polygon([(x1, y - head), (x1 + head, y), (x1, y + head)], fill=ACCENT)

    img.save(OUT_2X)
    img.resize((W, H), Image.LANCZOS).save(OUT_1X)
    print(f"wrote {OUT_1X.relative_to(REPO)} (600x400)")
    print(f"wrote {OUT_2X.relative_to(REPO)} (1200x800, Retina)")


if __name__ == "__main__":
    render()
