"""Generate a 1280x720 YouTube thumbnail from the best downloaded visual."""
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

W, H = 1280, 720


def _font(size: int, text: str = ""):
    """Shared with video.py so both surfaces pick a Devanagari-capable face.

    Segoe UI Black has no Devanagari and draws Hindi as empty boxes, and the
    old Windows-only path meant every non-Windows run silently fell back to a
    tiny bitmap font.
    """
    import video

    return video._font(size, text)


def _background(assets: list) -> Image.Image:
    for asset in assets:
        if asset and asset["is_image"]:
            try:
                img = Image.open(asset["path"]).convert("RGB")
                img = img.resize(
                    (W, int(W * img.height / img.width)) if img.width / img.height < W / H
                    else (int(H * img.width / img.height), H), Image.LANCZOS)
                left = max(0, (img.width - W) // 2)
                top = max(0, (img.height - H) // 2)
                return img.crop((left, top, left + W, top + H))
            except Exception:
                continue

    gradient = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(gradient)
    for y in range(H):
        ratio = y / (H - 1)
        draw.line([(0, y), (W, y)],
                  fill=(int(12 + 70 * ratio), int(18 + 20 * ratio), int(48 + 80 * ratio)))
    return gradient


def make_thumbnail(text: str, assets: list, dest: Path) -> Path:
    image = _background(assets)
    image = image.filter(ImageFilter.GaussianBlur(2))
    image = ImageEnhance.Brightness(image).enhance(0.55)
    image = ImageEnhance.Color(image).enhance(1.25)

    draw = ImageDraw.Draw(image)
    # Red accent bar down the left — reads as "news" at thumbnail size.
    draw.rectangle([0, 0, 18, H], fill=(220, 30, 40))

    # .upper() only affects Latin; Devanagari has no capitals, so Hindi
    # thumbnail text passes through unchanged.
    wrapped = textwrap.fill(text.strip().upper(), width=14)
    size = 118
    font = _font(size, wrapped)
    while size > 46:
        box = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=10)
        if box[2] - box[0] < W - 140 and box[3] - box[1] < H - 140:
            break
        size -= 8
        font = _font(size, wrapped)

    box = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=10)
    x = (W - (box[2] - box[0])) / 2
    y = (H - (box[3] - box[1])) / 2 - 10
    draw.multiline_text((x, y), wrapped, font=font, fill=(255, 255, 255),
                        align="center", spacing=10, stroke_width=9,
                        stroke_fill=(0, 0, 0))

    image.save(dest, "JPEG", quality=88)
    # YouTube rejects thumbnails over 2 MB.
    quality = 88
    while dest.stat().st_size > 1_900_000 and quality > 40:
        quality -= 10
        image.save(dest, "JPEG", quality=quality)
    return dest
