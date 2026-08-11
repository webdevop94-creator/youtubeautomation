"""Build a 1280x720 YouTube thumbnail that looks made, not generated.

The old version asked the downloaded assets for a still and, finding none,
drew a purple gradient with white text on it. That "finding none" was the
whole story: the pipeline downloads stock *video* for nearly every beat, and
the only branch that produced a picture required `is_image`. So every upload
shipped the same purple card with different words -- which is the one thing a
thumbnail must never be, because a channel's thumbnails are seen side by side
on the same screen.

So a picture is now non-negotiable, and there are three ways to get one before
the gradient is allowed to appear:

  1. a hero image generated for this video's subject (free, no key)
  2. a frame lifted out of the stock footage already on disk, picked by
     contrast and colour rather than taken from the front of the clip
  3. a stock photo, if the run happened to download one

On top of that goes an actual composition -- lifted and graded picture,
vignette, a scrim only under the words, a badge, an accent colour, and one of
three layouts. Layout and accent are chosen from a hash of the title, so two
videos are different from each other while any one video always rebuilds the
same.

The words themselves are drawn by libass through ffmpeg rather than by Pillow.
Pillow only reorders Devanagari matras when it is built against libraqm, which
the wheels used here are not, so it drew "दुनिया" as "दुनयिा" -- every Hindi
thumbnail this channel has published is misspelled in a way that is invisible
unless you read the script.
"""
import hashlib
import os
import re
import subprocess
import urllib.parse
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter

import config

W, H = 1280, 720

HERO_API = "https://image.pollinations.ai/prompt/"
HERO_TIMEOUT = int(os.getenv("THUMB_GEN_TIMEOUT", "150"))
# Off switch for a run with no internet, or when the generator is having a bad
# day. Frame-grabbing still gives a real picture, so this stays usable.
USE_HERO = os.getenv("THUMB_AI", "true").strip().lower() == "true"

# Optional channel wordmark burned into the corner. Empty by default -- a
# guessed brand name on every upload is worse than none.
BRAND = os.getenv("THUMB_BRAND", "").strip()

DIGITS = re.compile(r"[0-9०-९]")


def _font(size: int, text: str = ""):
    """Shared with video.py so both surfaces pick a Devanagari-capable face.

    Segoe UI Black has no Devanagari and draws Hindi as empty boxes, and the
    old Windows-only path meant every non-Windows run silently fell back to a
    tiny bitmap font.
    """
    import video

    return video._font(size, text)


# --- look ------------------------------------------------------------------
# Accent colour + how the picture is graded under it. Picked per video, not
# per day: two videos published in the same run must not look like one video
# uploaded twice.
LOOKS = [
    {"accent": (255, 209, 0),   "warm": 1.06, "name": "yellow"},
    {"accent": (255, 59, 48),   "warm": 1.04, "name": "red"},
    {"accent": (0, 224, 255),   "warm": 0.96, "name": "cyan"},
    {"accent": (124, 252, 79),  "warm": 1.00, "name": "green"},
    {"accent": (255, 138, 0),   "warm": 1.08, "name": "orange"},
    {"accent": (255, 61, 180),  "warm": 1.02, "name": "pink"},
]

LAYOUTS = ("left", "bottom", "center")

# What the badge says. Kind wins over category: "FACTS" describes the video a
# viewer is about to watch, "world" describes how the pipeline filed it.
KIND_BADGE = {"facts": "FACTS", "jokes": "JOKES", "riddles": "PAHELI",
              "stories": "KAHANI"}
CATEGORY_BADGE = {"world": "WORLD FACTS", "tech": "TECH", "science": "SCIENCE",
                  "sports": "SPORTS", "business": "BUSINESS",
                  "entertainment": "ENTERTAINMENT", "health": "HEALTH",
                  "general": "DID YOU KNOW"}


def _look_of(seed_text: str) -> dict:
    digest = hashlib.md5(seed_text.encode("utf-8")).digest()
    look = dict(LOOKS[digest[0] % len(LOOKS)])
    look["layout"] = LAYOUTS[digest[1] % len(LAYOUTS)]
    return look


# --- background ------------------------------------------------------------
# A thumbnail wants one loud subject, which is the opposite of what the beat
# prompts in visuals.py ask for -- those describe a scene that has to sit
# quietly behind narration.
HERO_STYLE = ("dramatic cinematic photograph, one striking subject filling the "
              "frame, shallow depth of field, bright colourful lighting, "
              "vivid saturated colour, punchy contrast, epic scale, "
              "professional youtube thumbnail background, "
              "no text, no watermark, no letters, no logos, no captions")

DROP = {"the", "and", "for", "with", "a", "an", "of", "to", "in", "on", "at"}


def _hero_prompt(script: dict, category: str) -> str:
    """Describe the video's subject in English, from the beats' own keywords.

    The title is Devanagari and the generator does badly with it; the beats
    already carry English keywords picked for exactly this purpose.
    """
    beats = script.get("long_beats") or script.get("shorts_beats") or []
    words, seen = [], set()
    for beat in beats[:2]:
        for word in re.findall(r"[a-zA-Z]{2,}", beat.get("keywords", "")):
            low = word.lower()
            if low not in DROP and low not in seen:
                seen.add(low)
                words.append(low)
    scene = " ".join(words[:7])
    if not scene:
        scene = f"{category or 'world'} documentary hero shot"
    return f"{scene}, {HERO_STYLE}"


def _generate_hero(script: dict, category: str, dest: Path) -> bool:
    """Draw a picture for this specific video. False lets the caller fall back."""
    seed = int(hashlib.md5(
        script.get("title", "").encode("utf-8")).hexdigest()[:6], 16)
    url = (HERO_API + urllib.parse.quote(_hero_prompt(script, category))
           + f"?width={W}&height={H}&seed={seed}&nologo=true&model=flux")
    try:
        resp = requests.get(url, timeout=HERO_TIMEOUT)
        if resp.status_code != 200 or len(resp.content) < 20_000:
            return False
        dest.write_bytes(resp.content)
        Image.open(dest).verify()          # truncated download reaching PIL later
        return True                        # is a crash in the middle of a run
    except Exception:
        dest.unlink(missing_ok=True)
        return False


def _interest(img: Image.Image) -> float:
    """How much is going on in this frame. Used to reject black fades."""
    from PIL import ImageStat

    small = img.resize((160, 90))
    grey = ImageStat.Stat(small.convert("L"))
    if grey.mean[0] < 28:                  # a fade-to-black is not a thumbnail
        return -1.0
    sat = ImageStat.Stat(small.convert("HSV").getchannel("S")).mean[0]
    return grey.stddev[0] + 0.6 * sat


def _grab_frame(video_path: Path, work: Path):
    """Best of a few frames from a clip, rather than whatever is at 0:00.

    Stock clips routinely open on a fade or an empty establishing shot, so the
    first frame is the worst available choice.
    """
    best, best_score = None, 0.0
    for i, when in enumerate((1.2, 2.8, 4.5)):
        shot = work / f"_thumb_frame_{i}.jpg"
        try:
            done = subprocess.run(
                [config.FFMPEG, "-y", "-v", "error", "-ss", str(when),
                 "-i", str(video_path), "-frames:v", "1", "-q:v", "2",
                 str(shot)], capture_output=True)
            if done.returncode != 0 or not shot.exists():
                continue
            frame = Image.open(shot).convert("RGB")
            score = _interest(frame)
            if score > best_score:
                best, best_score = frame, score
        except Exception:
            continue
        finally:
            shot.unlink(missing_ok=True)
    return best


def _fill(img: Image.Image) -> Image.Image:
    """Cover 1280x720, centre-cropped, no squashing."""
    scale = max(W / img.width, H / img.height)
    img = img.resize((max(W, int(img.width * scale)), max(H, int(img.height * scale))),
                     Image.LANCZOS)
    left = (img.width - W) // 2
    top = (img.height - H) // 2
    return img.crop((left, top, left + W, top + H))


def _gradient(look: dict) -> Image.Image:
    """Last resort, and it at least carries the video's own accent colour now."""
    r, g, b = look["accent"]
    top = (max(6, r // 9), max(8, g // 9), max(14, b // 9))
    bottom = (max(24, r // 4), max(20, g // 4), max(40, b // 4))
    image = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(image)
    for y in range(H):
        t = y / (H - 1)
        draw.line([(0, y), (W, y)],
                  fill=tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3)))
    # Diagonal light streaks: something for the eye to land on besides the text.
    streaks = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(streaks)
    for i in range(-2, 7):
        x = i * 210
        sd.polygon([(x, H), (x + 150, H), (x + 470, 0), (x + 320, 0)],
                   fill=(r, g, b, 16))
    return Image.alpha_composite(image.convert("RGBA"), streaks).convert("RGB")


def _background(assets: list, script: dict, category: str, work: Path,
                look: dict) -> Image.Image:
    if USE_HERO and script:
        hero = work / "_thumb_hero.jpg"
        if _generate_hero(script, category, hero):
            try:
                image = _fill(Image.open(hero).convert("RGB"))
                hero.unlink(missing_ok=True)
                return image
            except Exception:
                hero.unlink(missing_ok=True)

    # Footage already on disk. Scored, so a black frame does not win by being
    # first, and capped at four clips so a 12-beat video does not spend a
    # minute in ffmpeg.
    for asset in [a for a in assets if a and not a["is_image"]][:4]:
        frame = _grab_frame(Path(asset["path"]), work)
        if frame is not None:
            return _fill(frame)

    for asset in [a for a in assets if a and a["is_image"]]:
        try:
            return _fill(Image.open(asset["path"]).convert("RGB"))
        except Exception:
            continue

    return _gradient(look)


# --- treatment -------------------------------------------------------------
def _vignette(image: Image.Image, strength: float = 0.5) -> Image.Image:
    mask = Image.new("L", (64, 36), 0)
    ImageDraw.Draw(mask).ellipse((-15, -9, 79, 45), fill=255)
    mask = mask.resize((W, H), Image.BICUBIC).filter(ImageFilter.GaussianBlur(70))
    return Image.composite(image, ImageEnhance.Brightness(image).enhance(1 - strength),
                           mask)


def _smooth(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


def _scrim(image: Image.Image, layout: str, edge: int) -> Image.Image:
    """Darken only where the words go, so the picture survives everywhere else.

    Flattening the whole frame -- which is what the old blur-and-dim did -- is
    why the background stopped mattering at all. `edge` is where the text block
    actually ends, measured after wrapping: a scrim placed at a guessed
    coordinate leaves half a line sitting on bare picture.
    """
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    if layout == "left":
        for x in range(W):
            alpha = int(238 * (1 - _smooth((x - edge) / 330)))
            draw.line([(x, 0), (x, H)], fill=(4, 6, 12, alpha))
    elif layout == "bottom":
        for y in range(H):
            alpha = int(246 * _smooth((y - edge) / 190))
            draw.line([(0, y), (W, y)], fill=(4, 6, 12, alpha))
    else:
        # Centre layout has no edge to hide behind, so the whole frame dims --
        # but from the middle outwards, which keeps the corners of the picture
        # alive instead of flattening all of it to the same grey.
        for y in range(H):
            alpha = int(64 + 54 * (1 - abs(y - H / 2) / (H / 2)))
            draw.line([(0, y), (W, y)], fill=(4, 6, 12, alpha))

    return Image.alpha_composite(image.convert("RGBA"), overlay).convert("RGB")


def _lift(image: Image.Image) -> Image.Image:
    """Open the picture up before anything is asked of its colour.

    Both sources arrive dark: the hero prompt asks for cinematic lighting and
    gets night, and a frame pulled out of stock footage carries whatever grade
    the clip had. Saturating a dark frame gives a murky one, so the levels are
    stretched first and a genuinely underexposed picture is brought up to a
    workable mean -- a thumbnail is judged as a postage stamp on a bright feed,
    where dark reads as nothing at all.
    """
    from PIL import ImageOps, ImageStat

    image = ImageOps.autocontrast(image, cutoff=(1, 2), preserve_tone=True)
    mean = ImageStat.Stat(image.convert("L")).mean[0]
    if mean < 100:
        image = ImageEnhance.Brightness(image).enhance(min(1.85, 100 / max(mean, 26)))
    return image


def _grade(image: Image.Image, look: dict, layout: str) -> Image.Image:
    image = _lift(image)
    image = ImageEnhance.Color(image).enhance(1.34)
    image = ImageEnhance.Contrast(image).enhance(1.12)
    image = ImageEnhance.Brightness(image).enhance(0.95 if layout != "center" else 0.84)

    # Warm or cool the picture toward the accent, gently -- enough to tie the
    # colour of the words to the colour of the light.
    warm = look["warm"]
    if abs(warm - 1.0) > 0.01:
        red, green, blue = image.split()
        red = red.point(lambda v: min(255, int(v * warm)))
        blue = blue.point(lambda v: min(255, int(v * (2 - warm))))
        image = Image.merge("RGB", (red, green, blue))

    return _vignette(image)


# --- text ------------------------------------------------------------------
# Hindi has to be *shaped*, not just drawn. Pillow only reorders Devanagari
# matras when it was built against libraqm, and the wheels here report
# raqm=False -- so `ImageDraw.text` lays the glyphs out in logical order and
# "दुनिया" arrives as "दुनयिा". Every Hindi thumbnail this channel has ever
# uploaded is misspelled in exactly that way, and it is invisible unless you
# read Devanagari.
#
# libass shapes properly through HarfBuzz, and it is already a hard dependency
# of this pipeline -- video.py burns the captions with the same library. So the
# title is drawn by ffmpeg onto a transparent canvas, one line at a time, and
# composited here. PIL keeps the jobs it is good at: measuring the wrap,
# stacking the lines, and everything that is not a glyph.
LINE_W, LINE_H = 2400, 900          # roomy, so a long line is measured, not clipped

ASS_LINE = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: T,{font},{size},{fill},&H000000FF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,{outline},0,5,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:00.00,0:00:05.00,T,,0,0,0,,{text}
"""


def _ass_colour(rgb: tuple) -> str:
    """ASS wants &HBBGGRR, which is backwards from everything else here."""
    red, green, blue = rgb
    return f"&H00{blue:02X}{green:02X}{red:02X}"


def _ass_text(text: str) -> str:
    """Braces open an override block in ASS, so a title containing one would
    silently swallow the words after it."""
    return text.replace("\\", "/").replace("{", "(").replace("}", ")")


def _render_line(text: str, size: int, colour: tuple, work: Path, index: int):
    """One shaped line on a transparent canvas, or None if ffmpeg cannot.

    Every line is drawn centred on an identically sized canvas, so the line
    boxes -- and therefore the baselines -- already agree with each other; the
    stacking below only has to move them vertically.
    """
    import video

    ass = work / f"_thumb_line_{index}.ass"
    png = work / f"_thumb_line_{index}.png"
    ass.write_text(ASS_LINE.format(
        w=LINE_W, h=LINE_H, font=video._caption_font(text), size=size,
        fill=_ass_colour(colour), outline=max(5, round(size / 11)),
        text=_ass_text(text)), encoding="utf-8")
    try:
        # Run from the work directory and pass bare filenames: a Windows path
        # inside a filter graph has to escape both the colon and the
        # backslashes, and getting that wrong fails as "file not found".
        done = subprocess.run(
            [config.FFMPEG, "-y", "-v", "error",
             "-f", "lavfi", "-i", f"color=c=black@0.0:s={LINE_W}x{LINE_H}:d=1,format=rgba",
             "-vf", f"ass={ass.name}:alpha=1", "-frames:v", "1",
             "-pix_fmt", "rgba", png.name],
            cwd=str(work), capture_output=True)
        if done.returncode != 0 or not png.exists():
            return None
        layer = Image.open(png).convert("RGBA")
        layer.load()
        return layer if layer.getchannel("A").getbbox() else None
    except Exception:
        return None
    finally:
        ass.unlink(missing_ok=True)
        png.unlink(missing_ok=True)


def _stack(layers: list, step: int, align: str):
    """Lay the rendered lines out and crop to the ink.

    Cropping at the end -- rather than per line -- is what keeps the spacing
    even: a line carrying an ऊपर की मात्रा has taller ink than one without, and
    stacking by ink height would push it around.
    """
    boxes = [layer.getchannel("A").getbbox() for layer in layers]
    left, right = min(b[0] for b in boxes), max(b[2] for b in boxes)
    shifts = [left - b[0] if align == "left" else (left + right - b[0] - b[2]) // 2
              for b in boxes]

    # Left alignment only ever moves a line left, and alpha_composite refuses
    # negative coordinates, so the whole stack is nudged right by the largest
    # shift and the padding is cropped off at the end.
    pad = max(0, -min(shifts))
    canvas = Image.new("RGBA",
                       (LINE_W + pad + max(0, max(shifts)),
                        LINE_H + step * (len(layers) - 1)), (0, 0, 0, 0))
    for i, (layer, shift) in enumerate(zip(layers, shifts)):
        canvas.alpha_composite(layer, (pad + shift, i * step))
    return canvas.crop(canvas.getchannel("A").getbbox())


def _shaped_block(lines: list, look: dict, work: Path, max_w: int, max_h: int,
                  align: str, accent_index: int):
    """The title as one transparent image, sized to fill its box.

    Measured at a reference size and then scaled to what was measured, because
    the PIL wrap above can only guess at Devanagari widths -- it counts each
    matra as a separate advance -- and a guess is fine for choosing where the
    lines break but not for choosing how big they are.
    """
    colours = [look["accent"] if i == accent_index and len(lines) > 1
               else (255, 255, 255) for i in range(len(lines))]
    size = 120
    for attempt in range(3):
        layers = []
        for i, line in enumerate(lines):
            layer = _render_line(line, size, colours[i], work, i)
            if layer is None:
                return None, 0
            layers.append(layer)
        block = _stack(layers, int(size * 1.12), align)
        scale = min(max_w / block.width, max_h / block.height)
        if 0.99 <= scale <= 1.05 or attempt == 2:
            return (block, size) if scale >= 0.99 else (
                block.resize((int(block.width * scale), int(block.height * scale)),
                             Image.LANCZOS), int(size * scale))
        size = max(40, int(size * scale * 0.995))
    return None, 0


def _wrap(words: list, font, probe, width: float) -> list:
    lines, current = [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if not current or probe.textlength(trial, font=font) <= width:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _layout_text(text: str, max_w: int, max_h: int, max_lines: int):
    """Largest size at which the words fit the box, wrapped into even lines.

    Greedy wrapping alone fills the first line to the brim and leaves the last
    one holding a single short word -- "DUNIYA KE 4 AJEEB" over "SACH". So once
    a size is settled, the narrowest column that still yields the same number
    of lines is found, and the words are re-wrapped into it: same lines, but
    balanced.
    """
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    words = text.split()
    for size in range(140, 45, -4):
        font = _font(size, text)
        lines = _wrap(words, font, probe, max_w)
        if len(lines) > max_lines:
            continue
        if any(probe.textlength(line, font=font) > max_w for line in lines):
            continue
        step = int(size * 1.16)
        if step * len(lines) > max_h:
            continue

        low, high = 40, int(max_w)
        while low < high:
            mid = (low + high) // 2
            if len(_wrap(words, font, probe, mid)) <= len(lines):
                high = mid
            else:
                low = mid + 1
        balanced = _wrap(words, font, probe, low)
        if len(balanced) == len(lines):
            lines = balanced

        widest = max(probe.textlength(line, font=font) for line in lines)
        return lines, font, size, step, widest

    font = _font(48, text)
    return [text], font, 48, 56, probe.textlength(text, font=font)


def _draw_block(image: Image.Image, lines, font, size, step, look, anchor_x,
                top, align):
    """Shadow, stroke, fill -- in that order, on separate layers.

    A stroke alone holds text over a busy photo only until the photo has
    something dark behind it too; the blurred shadow is what keeps the words
    off the picture at phone size.
    """
    accent_index = next((i for i, line in enumerate(lines) if DIGITS.search(line)),
                        len(lines) - 1)
    stroke = max(6, size // 10)

    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shadow)
    for i, line in enumerate(lines):
        y = top + i * step
        sdraw.text((anchor_x, y + size * 0.09), line, font=font, anchor=align,
                   fill=(0, 0, 0, 210), stroke_width=stroke, stroke_fill=(0, 0, 0, 210))
    image = Image.alpha_composite(
        image.convert("RGBA"), shadow.filter(ImageFilter.GaussianBlur(14)))

    draw = ImageDraw.Draw(image)
    for i, line in enumerate(lines):
        y = top + i * step
        fill = look["accent"] if i == accent_index and len(lines) > 1 else (255, 255, 255)
        draw.text((anchor_x, y), line, font=font, anchor=align, fill=fill,
                  stroke_width=stroke, stroke_fill=(0, 0, 0))
    return image.convert("RGB")


def _badge(image: Image.Image, label: str, look: dict, x: int, y: int):
    if not label:
        return image
    font = _font(38, label)
    draw = ImageDraw.Draw(image)
    width = draw.textlength(label, font=font)
    box = [x, y, x + width + 52, y + 66]
    draw.rounded_rectangle(box, radius=12, fill=look["accent"])
    draw.text((x + 26, y + 33), label, font=font, anchor="lm", fill=(10, 10, 12))
    return image


def _badge_label(script: dict, category: str) -> str:
    kind = (script or {}).get("kind", "").lower()
    if kind in KIND_BADGE:
        return KIND_BADGE[kind]
    return CATEGORY_BADGE.get((category or "").lower(), "")


# How much room the words get, per layout: (width, height, most lines).
BOXES = {"left": (640, 470, 3), "bottom": (1120, 320, 2), "center": (1060, 430, 3)}


def _place(image: Image.Image, block: Image.Image, x: int, y: int, look: dict):
    """Glow, shadow, then the words -- three passes, in that order.

    The glow is the accent colour smeared out behind the letters. It reads as
    lighting rather than as a box, and it is what keeps a white title legible
    on a pale sky without dimming the whole picture to get there.
    """
    alpha = block.getchannel("A")

    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    glow.paste(Image.new("RGBA", block.size, look["accent"] + (120,)), (x, y), alpha)
    glow = glow.filter(ImageFilter.GaussianBlur(44))

    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    shadow.paste(Image.new("RGBA", block.size, (0, 0, 0, 235)), (x, y + 12), alpha)
    shadow = shadow.filter(ImageFilter.GaussianBlur(17))

    out = Image.alpha_composite(image.convert("RGBA"), glow)
    out = Image.alpha_composite(out, shadow)
    out.alpha_composite(block, (x, y))
    return out.convert("RGB")


def make_thumbnail(text: str, assets: list, dest: Path, script: dict = None,
                   category: str = "") -> Path:
    script = script or {}
    category = category or script.get("category", "")
    text = (text or script.get("title", "")).strip().upper()
    # A blank thumbnail_text used to reach _layout_text and die on max() of an
    # empty wrap -- at the very last step before upload, with the video already
    # rendered.
    text = text or (category or "video").strip().upper()

    look = _look_of(script.get("title", "") + text)
    layout = look["layout"]
    work = Path(dest).parent
    max_w, max_h, max_lines = BOXES[layout]

    # PIL picks where the lines break; libass decides how big they are and
    # draws them. Both happen before the scrim, which has to be told where the
    # words actually ended up rather than guessing and missing.
    lines, font, size, step, widest = _layout_text(text, max_w, max_h, max_lines)
    accent_index = next((i for i, line in enumerate(lines) if DIGITS.search(line)),
                        len(lines) - 1)
    align = "left" if layout == "left" else "center"
    block, shaped = _shaped_block(lines, look, work, max_w, max_h, align, accent_index)
    size = shaped or size          # the fallback still needs a stroke width
    width, height = block.size if block else (int(widest), step * len(lines))

    if layout == "left":
        x, y = 76, (H - height) // 2 + 8
        edge = x + width + 26
    elif layout == "bottom":
        x, y = (W - width) // 2, H - height - 92
        edge = y - 130
    else:
        x, y = (W - width) // 2, (H - height) // 2 + 4
        edge = 0

    image = _background(assets, script, category, work, look)
    image = _grade(image, look, layout)
    image = _scrim(image, layout, int(edge))
    image = image.filter(ImageFilter.UnsharpMask(radius=2, percent=105, threshold=3))

    image = _badge(image, _badge_label(script, category), look,
                   76 if layout == "left" else 64,
                   max(40, y - 112) if layout == "left" else 58)

    if block is not None:
        image = _place(image, block, x, y, look)
    else:                                  # no ffmpeg: ugly Hindi beats no file
        image = _draw_block(image, lines, font, size, step, look,
                            x if layout == "left" else W // 2, y,
                            "la" if layout == "left" else "ma")

    draw = ImageDraw.Draw(image)
    if layout == "left":
        draw.rectangle([44, y + 4, 58, y + height - 4], fill=look["accent"])
    elif layout == "bottom":
        draw.rectangle([W // 2 - 130, y - 46, W // 2 + 130, y - 34], fill=look["accent"])
    else:
        draw.rectangle([W // 2 - 160, y + height + 26, W // 2 + 160, y + height + 38],
                       fill=look["accent"])

    if BRAND:
        bfont = _font(34, BRAND)
        draw = ImageDraw.Draw(image)
        draw.text((W - 46, H - 44), BRAND, font=bfont, anchor="rs",
                  fill=(255, 255, 255), stroke_width=5, stroke_fill=(0, 0, 0))

    image.save(dest, "JPEG", quality=90)
    # YouTube rejects thumbnails over 2 MB.
    quality = 90
    while dest.stat().st_size > 1_900_000 and quality > 40:
        quality -= 10
        image.save(dest, "JPEG", quality=quality)
    return dest
