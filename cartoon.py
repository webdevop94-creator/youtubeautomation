"""Draw flat 2D cartoon characters and scenes with PIL.

Why drawing and not generating: a generator cannot hold a character across
scenes. The same frozen description and seed produced a different character
every time it was tried. Drawing removes the problem instead of fighting it --
the same numbers produce the same character on every frame, forever.

It also makes the thing generation cannot do at all: talking. A mouth that
opens and closes, and eyes that blink, only need two variants of one drawing.

The style is deliberately simple -- circles, rounded rectangles, thick
outlines -- because that is the style that reads on a phone screen and the
style the reference channels use.
"""
import math
from pathlib import Path

from PIL import Image, ImageDraw

OUTLINE = (25, 25, 25)
OUTLINE_W = 5

SKINS = [(240, 205, 170), (226, 180, 140), (200, 150, 110), (170, 120, 85)]
SHIRTS = [(240, 110, 60), (40, 170, 160), (90, 130, 220), (230, 190, 60),
          (200, 90, 150), (120, 190, 90)]
PANTS = [(90, 60, 45), (35, 80, 90), (55, 55, 90), (70, 70, 70)]
HAIRS = [(30, 25, 25), (60, 40, 30), (20, 20, 30)]

# Rooms are three flat bands: wall, floor, and whatever hangs on the wall.
ROOMS = {
    "classroom": {"wall": (228, 205, 170), "floor": (150, 110, 75),
                  "board": (35, 85, 65), "board_frame": (120, 80, 50)},
    "clinic":    {"wall": (205, 228, 235), "floor": (170, 185, 190),
                  "board": (245, 245, 245), "board_frame": (180, 190, 195)},
    "home":      {"wall": (240, 220, 195), "floor": (160, 120, 90),
                  "board": (225, 205, 175), "board_frame": (150, 110, 80)},
    "office":    {"wall": (215, 220, 230), "floor": (120, 125, 135),
                  "board": (250, 250, 250), "board_frame": (170, 175, 185)},
    "shop":      {"wall": (235, 225, 190), "floor": (145, 115, 85),
                  "board": (240, 230, 200), "board_frame": (160, 125, 90)},
}


class Character:
    """One cartoon person. The numbers here ARE the character -- keep them and
    the same person appears in every frame of every video."""

    def __init__(self, seed: int, glasses: bool = False, cap: bool = False,
                 female: bool = False):
        self.skin = SKINS[seed % len(SKINS)]
        self.shirt = SHIRTS[(seed * 3) % len(SHIRTS)]
        self.pants = PANTS[(seed * 5) % len(PANTS)]
        self.hair = HAIRS[(seed * 7) % len(HAIRS)]
        self.cap_colour = SHIRTS[(seed * 11) % len(SHIRTS)]
        self.glasses = glasses
        self.cap = cap
        self.female = female

    def draw(self, d: ImageDraw.ImageDraw, cx: int, feet_y: int, scale: float,
             mouth_open: bool = False, blink: bool = False, flip: bool = False):
        s = scale
        head_r = int(60 * s)
        body_w, body_h = int(120 * s), int(130 * s)
        leg_h = int(80 * s)

        body_top = feet_y - leg_h - body_h
        head_cy = body_top - head_r + int(12 * s)

        # legs
        for dx in (-int(30 * s), int(30 * s)):
            d.rounded_rectangle(
                [cx + dx - int(16 * s), feet_y - leg_h, cx + dx + int(16 * s), feet_y],
                radius=int(10 * s), fill=self.pants, outline=OUTLINE, width=OUTLINE_W)
        # shoes
        for dx in (-int(30 * s), int(30 * s)):
            d.rounded_rectangle(
                [cx + dx - int(22 * s), feet_y - int(14 * s),
                 cx + dx + int(22 * s), feet_y + int(6 * s)],
                radius=int(7 * s), fill=(45, 45, 55), outline=OUTLINE, width=OUTLINE_W)

        # arms behind the body
        for dx in (-1, 1):
            ax = cx + dx * (body_w // 2 + int(6 * s))
            d.rounded_rectangle(
                [ax - int(16 * s), body_top + int(14 * s),
                 ax + int(16 * s), body_top + body_h - int(6 * s)],
                radius=int(14 * s), fill=self.shirt, outline=OUTLINE, width=OUTLINE_W)
            d.ellipse([ax - int(17 * s), body_top + body_h - int(22 * s),
                       ax + int(17 * s), body_top + body_h + int(12 * s)],
                      fill=self.skin, outline=OUTLINE, width=OUTLINE_W)

        # torso
        d.rounded_rectangle(
            [cx - body_w // 2, body_top, cx + body_w // 2, body_top + body_h],
            radius=int(34 * s), fill=self.shirt, outline=OUTLINE, width=OUTLINE_W)

        # head
        d.ellipse([cx - head_r, head_cy - head_r, cx + head_r, head_cy + head_r],
                  fill=self.skin, outline=OUTLINE, width=OUTLINE_W)
        # ears
        for dx in (-1, 1):
            ex = cx + dx * head_r
            d.ellipse([ex - int(11 * s), head_cy - int(10 * s),
                       ex + int(11 * s), head_cy + int(16 * s)],
                      fill=self.skin, outline=OUTLINE, width=OUTLINE_W)

        # hair: a cap sits on top, otherwise a simple fringe
        if self.cap:
            d.pieslice([cx - head_r - int(4 * s), head_cy - head_r - int(10 * s),
                        cx + head_r + int(4 * s), head_cy + int(14 * s)],
                       start=180, end=360, fill=self.cap_colour,
                       outline=OUTLINE, width=OUTLINE_W)
            peak = int(70 * s)
            d.rounded_rectangle(
                [cx - int(10 * s), head_cy - int(24 * s),
                 cx + peak, head_cy - int(6 * s)],
                radius=int(9 * s), fill=self.cap_colour,
                outline=OUTLINE, width=OUTLINE_W)
        else:
            d.pieslice([cx - head_r - int(3 * s), head_cy - head_r - int(6 * s),
                        cx + head_r + int(3 * s), head_cy + int(20 * s)],
                       start=180, end=360, fill=self.hair,
                       outline=OUTLINE, width=OUTLINE_W)
            if self.female:
                for dx in (-1, 1):
                    hx = cx + dx * (head_r - int(4 * s))
                    d.ellipse([hx - int(20 * s), head_cy - int(16 * s),
                               hx + int(20 * s), head_cy + int(56 * s)],
                              fill=self.hair, outline=OUTLINE, width=OUTLINE_W)

        # eyes
        eye_dx, eye_y, eye_r = int(24 * s), head_cy + int(2 * s), int(17 * s)
        for dx in (-eye_dx, eye_dx):
            if blink:
                d.line([cx + dx - eye_r, eye_y, cx + dx + eye_r, eye_y],
                       fill=OUTLINE, width=OUTLINE_W)
            else:
                d.ellipse([cx + dx - eye_r, eye_y - eye_r,
                           cx + dx + eye_r, eye_y + eye_r],
                          fill=(255, 255, 255), outline=OUTLINE, width=OUTLINE_W)
                pupil = int(8 * s)
                look = int(4 * s) * (-1 if flip else 1)
                d.ellipse([cx + dx - pupil + look, eye_y - pupil,
                           cx + dx + pupil + look, eye_y + pupil], fill=OUTLINE)

        if self.glasses:
            for dx in (-eye_dx, eye_dx):
                d.ellipse([cx + dx - eye_r - int(5 * s), eye_y - eye_r - int(5 * s),
                           cx + dx + eye_r + int(5 * s), eye_y + eye_r + int(5 * s)],
                          outline=OUTLINE, width=OUTLINE_W)
            d.line([cx - eye_dx + eye_r + int(5 * s), eye_y,
                    cx + eye_dx - eye_r - int(5 * s), eye_y],
                   fill=OUTLINE, width=OUTLINE_W)

        # mouth -- the whole point of drawing rather than generating
        my = head_cy + int(34 * s)
        if mouth_open:
            d.ellipse([cx - int(18 * s), my - int(14 * s),
                       cx + int(18 * s), my + int(18 * s)],
                      fill=(120, 40, 45), outline=OUTLINE, width=OUTLINE_W)
            d.chord([cx - int(13 * s), my + int(2 * s),
                     cx + int(13 * s), my + int(20 * s)],
                    start=0, end=180, fill=(235, 130, 140))
        else:
            d.arc([cx - int(20 * s), my - int(18 * s),
                   cx + int(20 * s), my + int(12 * s)],
                  start=20, end=160, fill=OUTLINE, width=OUTLINE_W)


def draw_scene(size: tuple, room: str, left: Character, right: Character,
               speaking: str = "left", board_text: str = "",
               blink: bool = False, dest: Path = None) -> Image.Image:
    """One frame: a room, two characters, one of them talking."""
    w, h = size
    palette = ROOMS.get(room, ROOMS["classroom"])
    img = Image.new("RGB", (w, h), palette["wall"])
    d = ImageDraw.Draw(img)

    floor_y = int(h * 0.78)
    d.rectangle([0, floor_y, w, h], fill=palette["floor"])
    d.line([0, floor_y, w, floor_y], fill=OUTLINE, width=OUTLINE_W)

    # The board doubles as a caption plate; text is drawn by the caller.
    bx0, by0 = int(w * 0.10), int(h * 0.10)
    bx1, by1 = int(w * 0.90), int(h * 0.52)
    d.rectangle([bx0 - 12, by0 - 12, bx1 + 12, by1 + 12],
                fill=palette["board_frame"], outline=OUTLINE, width=OUTLINE_W)
    d.rectangle([bx0, by0, bx1, by1], fill=palette["board"],
                outline=OUTLINE, width=OUTLINE_W)

    scale = h / 720.0
    feet = floor_y + int(70 * scale)
    left.draw(d, int(w * 0.24), feet, scale,
              mouth_open=(speaking == "left"), blink=blink, flip=False)
    right.draw(d, int(w * 0.76), feet, scale,
               mouth_open=(speaking == "right"), blink=blink, flip=True)

    if dest:
        img.save(dest, quality=95)
    return img
