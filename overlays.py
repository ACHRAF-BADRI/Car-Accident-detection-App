"""Synthetic text / logo overlays, so the classifier cannot use "there is a watermark" as a shortcut.

The accident images come from online compilations (channel logos, captions, site names) and the
normal-traffic images mostly don't: without this, a model learns "text on screen = accident".
Real CCTV frames also carry timestamps and camera names, on both kinds of scenes.
"""
import random
import string
from datetime import datetime, timedelta

from PIL import Image, ImageDraw, ImageFont

FONTS = ["arial.ttf", "arialbd.ttf", "impact.ttf", "consola.ttf", "verdana.ttf", "tahoma.ttf",
         "segoeui.ttf", "calibri.ttf", "cour.ttf", "trebuc.ttf", "georgia.ttf", "times.ttf"]
WORDS = ["CAM", "CCTV", "LIVE", "REC", "TRAFFIC", "CHANNEL", "NEWS", "ROAD", "CITY", "CAMERA", "HD",
         "POLICE", "DASH", "VIDEO", "TV", "STREET", "HIGHWAY", "NORTH", "SOUTH", "EXIT", "ZONE", "INFO"]
COLORS = [(255, 255, 255), (255, 255, 0), (255, 60, 60), (0, 255, 255), (0, 0, 0), (255, 165, 0), (120, 200, 255)]


def _font(size):
    try:
        return ImageFont.truetype(random.choice(FONTS), size)
    except OSError:
        return ImageFont.load_default()


def _random_text():
    kind = random.random()
    if kind < 0.35:  # camera timestamp
        t = datetime(2015, 1, 1) + timedelta(seconds=random.randint(0, 10 ** 8))
        return t.strftime(random.choice(["%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%m-%d-%Y %a %H:%M:%S"]))
    if kind < 0.55:  # website / channel
        word = "".join(random.choices(string.ascii_lowercase, k=random.randint(4, 10)))
        return word + random.choice([".com", ".tv", ".net", ".org", ".camera", " TV", " Channel"])
    if kind < 0.8:  # caption in capitals
        return " ".join(random.choices(WORDS, k=random.randint(1, 3))) + random.choice(["", f" {random.randint(1, 99)}"])
    return "".join(random.choices(string.ascii_letters + string.digits + " ", k=random.randint(4, 18))).strip() or "CAM 1"


def add_overlays(img, count=None):
    """Draw 1-3 random texts and sometimes a small logo block, anywhere on the image (mostly edges / corners)."""
    img = img.convert("RGB").copy()
    w, h = img.size
    draw = ImageDraw.Draw(img, "RGBA")
    for _ in range(count or random.randint(1, 3)):
        text = _random_text()
        size = max(10, int(h * random.uniform(0.03, 0.09)))
        font = _font(size)
        tw, th = draw.textbbox((0, 0), text, font=font)[2:]
        edge = random.random() < 0.75
        x = random.choice([random.randint(0, max(1, w // 12)), max(0, w - tw - random.randint(0, w // 12))]) if edge else random.randint(0, max(1, w - tw))
        y = random.choice([random.randint(0, max(1, h // 12)), max(0, h - th - random.randint(0, h // 12))]) if edge else random.randint(0, max(1, h - th))
        if random.random() < 0.3:  # text on a band
            draw.rectangle((x - 4, y - 2, x + tw + 4, y + th + 4), fill=random.choice(COLORS) + (random.randint(120, 230),))
        color = random.choice(COLORS)
        if random.random() < 0.5:  # outline, as TV captions often have
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0, 200))
        draw.text((x, y), text, font=font, fill=color + (random.randint(170, 255),))
    if random.random() < 0.35:  # channel logo block
        lw, lh = int(w * random.uniform(0.08, 0.2)), int(h * random.uniform(0.05, 0.12))
        x = random.choice([8, w - lw - 8]); y = random.choice([8, h - lh - 8])
        draw.rounded_rectangle((x, y, x + lw, y + lh), radius=lh // 4, fill=random.choice(COLORS) + (random.randint(150, 230),))
        draw.text((x + 4, y + 2), "".join(random.choices(string.ascii_uppercase, k=random.randint(2, 5))),
                  font=_font(max(10, lh - 6)), fill=random.choice(COLORS) + (255,))
    return img


def title_card(size=(640, 360)):
    """Intro / outro screen of a video: plain or dark background with text. Not an accident."""
    base = random.choice([(0, 0, 0), (10, 10, 30), (240, 240, 240), (20, 40, 90), (90, 10, 10),
                          tuple(random.randint(0, 255) for _ in range(3))])
    img = Image.new("RGB", size, base)
    draw = ImageDraw.Draw(img)
    for i in range(random.randint(1, 4)):
        text = " ".join(random.choices(WORDS + [w.lower() for w in WORDS], k=random.randint(2, 6)))
        font = _font(random.randint(16, 40))
        draw.text((random.randint(10, size[0] // 3), 40 + i * random.randint(50, 80)), text, font=font,
                  fill=random.choice(COLORS))
    return add_overlays(img, count=random.randint(0, 2)) if random.random() < 0.5 else img
