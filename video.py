"""Assemble narration + visuals + burned-in subtitles into a finished MP4."""
import random
import re
import subprocess
import textwrap
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import config

GRADIENTS = [
    ((14, 20, 48), (86, 30, 120)),
    ((10, 40, 60), (18, 110, 130)),
    ((45, 12, 30), (140, 45, 40)),
    ((12, 32, 22), (30, 110, 80)),
]

# --- The daily look --------------------------------------------------------
# Two videos a day, every day, out of one pipeline: left alone they are the
# same video with different words, and a channel of those reads as a template.
# Rotating the caption treatment, the fallback card and the music gives each
# day its own look without touching what the video says.
#
# Picked from the date rather than at random, for two reasons: consecutive days
# can never collide, and re-rendering a folder tomorrow reproduces the video it
# produced today instead of quietly restyling it.
#
# ASS colours are &HAABBGGRR -- alpha first, then BLUE, green, red. Written the
# other way round (as RGB) yellow comes out sky blue, which is the kind of
# mistake that only shows up in the finished upload.
LOOKS = [
    {   # thick yellow, black outline -- the loud one
        "name": "bold-yellow",
        "primary": "&H0000FFFF", "outline_colour": "&H00000000",
        "border_style": 1, "outline": 5.5, "shadow": 2.0,
        "font_ratio": 23, "margin_v": 0.17,
        "gradient": ((45, 12, 30), (140, 45, 40)),
    },
    {   # white on a translucent slab -- the readable one
        "name": "white-box",
        "primary": "&H00FFFFFF", "outline_colour": "&H99000000",
        "border_style": 3, "outline": 14.0, "shadow": 0.0,
        "font_ratio": 25, "margin_v": 0.15,
        "gradient": ((14, 20, 48), (86, 30, 120)),
    },
    {   # small and low, out of the way of the picture
        "name": "lower-third",
        "primary": "&H00FFFFFF", "outline_colour": "&H00000000",
        "border_style": 1, "outline": 3.0, "shadow": 3.5,
        "font_ratio": 27, "margin_v": 0.09,
        "gradient": ((12, 32, 22), (30, 110, 80)),
    },
    {   # pale blue, sitting high -- the calm one
        "name": "sky-outline",
        "primary": "&H00FFF0A0", "outline_colour": "&H00201000",
        "border_style": 1, "outline": 5.0, "shadow": 1.5,
        "font_ratio": 22, "margin_v": 0.23,
        "gradient": ((10, 40, 60), (18, 110, 130)),
    },
]


def look_of_the_day(when: date = None) -> dict:
    """Today's caption/card/music treatment. Same for both of a day's videos."""
    day = (when or date.today()).toordinal()
    return LOOKS[day % len(LOOKS)]


def _run(args: list, cwd: Path = None) -> None:
    result = subprocess.run(args, cwd=str(cwd) if cwd else None,
                            capture_output=True, text=True)
    if result.returncode != 0:
        tail = (result.stderr or "").strip().splitlines()[-15:]
        raise RuntimeError("FFmpeg fail:\n  " + "\n  ".join(tail))


DEVANAGARI = re.compile(r"[ऀ-ॿ]")

# Windows first, then the usual Linux locations so the same code works on a
# server. Devanagari-capable faces lead when the text needs them: Segoe UI
# Black draws Hindi as empty boxes.
FONT_DIRS = [Path(r"C:\Windows\Fonts"), Path("/usr/share/fonts"),
             Path("/usr/local/share/fonts"), Path.home() / ".fonts"]

# (filename, face index). Windows ships Nirmala as a .ttc COLLECTION, not a
# .ttf -- searching for "Nirmala.ttf" finds nothing and Hindi silently falls
# back to a Latin face that draws it as empty boxes. Index 1 is the Bold face.
DEVANAGARI_FONTS = (("Nirmala.ttc", 1), ("Nirmala.ttc", 0),
                    ("mangalb.ttf", 0), ("mangal.ttf", 0),
                    ("NotoSansDevanagari-Bold.ttf", 0),
                    ("NotoSansDevanagari-Regular.ttf", 0),
                    ("Lohit-Devanagari.ttf", 0))
LATIN_FONTS = (("seguibl.ttf", 0), ("arialbd.ttf", 0), ("segoeuib.ttf", 0),
               ("DejaVuSans-Bold.ttf", 0), ("LiberationSans-Bold.ttf", 0))


def _find_font(candidates: tuple):
    for name, index in candidates:
        for folder in FONT_DIRS:
            if not folder.exists():
                continue
            direct = folder / name
            for path in ([direct] if direct.exists() else list(folder.rglob(name))):
                return str(path), index
    return "", 0


def _font(size: int, text: str = ""):
    order = (DEVANAGARI_FONTS + LATIN_FONTS if DEVANAGARI.search(text)
             else LATIN_FONTS + DEVANAGARI_FONTS)
    path, index = _find_font(order)
    if path:
        try:
            return ImageFont.truetype(path, size, index=index)
        except OSError:
            pass
    return ImageFont.load_default()


def _text_card(text: str, size: tuple, dest: Path, show_text: bool = True,
               look: dict = None) -> Path:
    """Gradient fallback card, used when no stock clip is found.

    show_text is off when subtitles are burned in — otherwise the same words
    appear twice on screen, stacked on top of each other.
    """
    width, height = size
    # The day's colour rather than a fresh random one per card: cards that
    # disagree with each other inside one video look like a fault, not variety.
    top, bottom = (look or look_of_the_day())["gradient"]
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)

    for y in range(height):
        ratio = y / max(1, height - 1)
        draw.line([(0, y), (width, y)], fill=(
            int(top[0] + (bottom[0] - top[0]) * ratio),
            int(top[1] + (bottom[1] - top[1]) * ratio),
            int(top[2] + (bottom[2] - top[2]) * ratio)))

    if not show_text:
        image.save(dest, quality=92)
        return dest

    words = " ".join(text.split()[:14])
    font = _font(int(width * 0.055), words)
    wrapped = textwrap.fill(words, width=28)

    box = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=14)
    x = (width - (box[2] - box[0])) / 2
    y = (height - (box[3] - box[1])) / 2
    draw.multiline_text((x, y), wrapped, font=font, fill=(255, 255, 255),
                        align="center", spacing=14,
                        stroke_width=max(2, width // 400), stroke_fill=(0, 0, 0))

    image.save(dest, quality=92)
    return dest


# Where the camera drifts, cycled per beat so consecutive shots do not all
# move the same way. (x_expr, y_expr) over zoompan's progress variable `on`.
DRIFTS = [
    ("(iw-iw/zoom)*on/{frames}", "(ih-ih/zoom)/2"),          # left  -> right
    ("(iw-iw/zoom)*(1-on/{frames})", "(ih-ih/zoom)/2"),      # right -> left
    ("(iw-iw/zoom)/2", "(ih-ih/zoom)*on/{frames}"),          # top   -> bottom
    ("(iw-iw/zoom)/2", "(ih-ih/zoom)*(1-on/{frames})"),      # bottom-> top
]


def _clip_from_image(src: Path, duration: float, size: tuple, dest: Path,
                     index: int = 0) -> None:
    """Ken Burns move that lasts the whole beat.

    The old version used a fixed per-frame zoom step capped at 1.15, which it
    reached in about five seconds. Beats run four to six times longer than
    that, so the shot froze for most of its screen time and the video read as
    a slideshow. The rate is now derived from the beat's own length, and the
    frame also pans, with the direction cycling so consecutive shots differ.
    """
    width, height = size
    frames = max(2, int(duration * config.FPS))

    # Alternate push-in and pull-out; a whole video of push-ins feels uniform.
    zoom_in = index % 2 == 0
    span = 0.28
    if zoom_in:
        zoom_expr = f"min(1+{span}*on/{frames},{1 + span})"
    else:
        zoom_expr = f"max({1 + span}-{span}*on/{frames},1.0)"

    x_expr, y_expr = DRIFTS[index % len(DRIFTS)]
    vf = (
        f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,"
        f"crop={width * 2}:{height * 2},"
        f"zoompan=z='{zoom_expr}'"
        f":x='{x_expr.format(frames=frames)}':y='{y_expr.format(frames=frames)}'"
        f":d={frames}:s={width}x{height}:fps={config.FPS},"
        f"format=yuv420p"
    )
    _run([config.FFMPEG, "-y", "-v", "error", "-loop", "1", "-i", str(src),
          "-t", f"{duration:.3f}", "-vf", vf, "-r", str(config.FPS),
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", str(dest)])


def _clip_from_video(src: Path, duration: float, size: tuple, dest: Path) -> None:
    width, height = size
    vf = (f"scale={width}:{height}:force_original_aspect_ratio=increase,"
          f"crop={width}:{height},fps={config.FPS},format=yuv420p")
    # -stream_loop makes short stock clips fill a long beat instead of freezing.
    _run([config.FFMPEG, "-y", "-v", "error", "-stream_loop", "-1", "-i", str(src),
          "-t", f"{duration:.3f}", "-an", "-vf", vf, "-r", str(config.FPS),
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", str(dest)])


ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,{font},{fs},{primary},&H000000FF,{outline_colour},&H60000000,-1,0,0,0,100,100,0,0,{border_style},{outline},{shadow},2,{ml},{mr},{mv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ass_time(srt_stamp: str) -> str:
    """00:00:02,724 -> 0:00:02.72"""
    hms, ms = srt_stamp.strip().split(",")
    h, m, s = hms.split(":")
    return f"{int(h)}:{m}:{s}.{int(ms) // 10:02d}"


def _caption_font(text: str) -> str:
    """A font that can actually draw this text.

    Arial has no Devanagari, so Hindi captions render as empty boxes. Nirmala
    UI ships with Windows and covers Indic scripts; the others are fallbacks
    for Linux, where libass picks the closest match it has.
    """
    if not DEVANAGARI.search(text):
        return "Arial"
    # Font NAME, not filename -- libass resolves it through the system font
    # list, where Nirmala's .ttc registers as "Nirmala UI".
    if Path(r"C:\Windows\Fonts\Nirmala.ttc").exists():
        return "Nirmala UI"
    return "Noto Sans Devanagari"


def _srt_to_ass(srt_path: Path, size: tuple, dest: Path, look: dict = None) -> Path:
    """Convert captions to ASS with an explicit PlayRes.

    libass defaults to a 384x288 canvas when none is declared, which silently
    scales every font size and margin by ~6.7x on a 1080p canvas.
    """
    look = look or look_of_the_day()
    width, height = size
    body = srt_path.read_text(encoding="utf-8")
    # Outline and shadow are in ASS units against the declared PlayRes, so they
    # scale with the canvas on their own -- the old height//320 was doing that
    # arithmetic a second time.
    header = ASS_HEADER.format(
        w=width, h=height, font=_caption_font(body),
        fs=int(height / look["font_ratio"]),   # ~83px on a 1920-tall Short
        primary=look["primary"],
        outline_colour=look["outline_colour"],
        border_style=look["border_style"],
        outline=look["outline"], shadow=look["shadow"],
        ml=int(width * 0.07), mr=int(width * 0.07),
        # Clear of the Shorts/Reels UI, and today's height within that.
        mv=int(height * look["margin_v"]),
    )

    events = []
    for block in body.strip().split("\n\n"):
        lines = [ln for ln in block.strip().splitlines() if ln.strip()]
        if len(lines) < 3 or "-->" not in lines[1]:
            continue
        start, end = (part.strip() for part in lines[1].split("-->"))
        text = "\\N".join(lines[2:]).replace("{", "(").replace("}", ")")
        events.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Cap,,0,0,0,,{text}")

    dest.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return dest


# Which track suits which subject. Picking at random put an upbeat loop under
# an explainer about Venus and a calm one under a joke -- the music was never
# wrong for the library, only for the video it landed in.
#
# Nothing in the current library is named for a mood, so every lookup here
# falls through to the date rotation below. Kept because it costs nothing and
# takes effect again the moment a track named bg_calm or bg_upbeat comes back.
MOOD = {
    "science": ("steady", "calm"), "tech": ("steady", "calm"),
    "business": ("steady", "calm"), "health": ("calm", "steady"),
    "world": ("steady", "calm"),
    "entertainment": ("bright", "upbeat"), "sports": ("upbeat", "bright"),
}


def _pick_music(category: str = "", when: date = None) -> Path | None:
    """A track whose mood fits the subject, not whichever one came up."""
    if not config.MUSIC_DIR.exists():
        return None
    tracks = sorted((p for p in config.MUSIC_DIR.iterdir()
                     if p.suffix.lower() in (".mp3", ".m4a", ".wav", ".ogg")),
                    key=lambda p: p.name)
    if not tracks:
        return None
    for want in MOOD.get(category, ()):
        for track in tracks:
            if want in track.stem.lower():
                return track
    # No mood match. Step through the library by date instead of choosing at
    # random: random means today's two videos can land on the same track and
    # tomorrow's on it again, which is the one thing a daily channel notices.
    return tracks[(when or date.today()).toordinal() % len(tracks)]


def build(narration: dict, assets: list, work_dir: Path, vertical: bool,
          label: str, burn_subs: bool, category: str = "") -> Path:
    """Render one finished video. Returns the output path."""
    look = look_of_the_day()
    print(f"[6/7] Video assemble kar raha hoon ({label}, look: {look['name']})...")
    size = config.VERTICAL if vertical else config.LANDSCAPE
    clips_dir = work_dir / f"clips_{label}"
    clips_dir.mkdir(parents=True, exist_ok=True)

    clip_paths = []
    for i, (beat, asset) in enumerate(zip(narration["beats"], assets)):
        duration = max(1.2, beat["duration"])
        dest = clips_dir / f"clip_{i:02d}.mp4"

        card_text = not burn_subs  # burned captions already show these words

        if asset is None:
            card = _text_card(beat["text"], size, clips_dir / f"card_{i:02d}.jpg",
                              card_text, look)
            _clip_from_image(card, duration, size, dest, i)
        elif asset["is_image"]:
            _clip_from_image(asset["path"], duration, size, dest, i)
        else:
            try:
                _clip_from_video(asset["path"], duration, size, dest)
            except RuntimeError:  # corrupt download — don't lose the whole render
                card = _text_card(beat["text"], size, clips_dir / f"card_{i:02d}.jpg",
                                  card_text, look)
                _clip_from_image(card, duration, size, dest, i)

        clip_paths.append(dest)
        print(f"    clip {i + 1}/{len(narration['beats'])} ready")

    # Bare filenames: concat entries resolve relative to the list file's directory.
    concat_list = clips_dir / "concat.txt"
    concat_list.write_text(
        "\n".join(f"file '{p.name}'" for p in clip_paths), encoding="utf-8")

    silent = work_dir / f"silent_{label}.mp4"
    _run([config.FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0",
          "-i", str(concat_list), "-c", "copy", str(silent)])

    out_name = f"video_{'9x16' if vertical else '16x9'}.mp4"
    out_path = work_dir / out_name
    music = _pick_music(category)

    # Run from work_dir so the subtitles filter gets a plain relative filename —
    # Windows drive letters need painful escaping inside filtergraphs.
    args = [config.FFMPEG, "-y", "-v", "error", "-i", silent.name,
            "-i", narration["audio"].name]
    if music:
        args += ["-stream_loop", "-1", "-i", str(music)]

    filters = []
    have_subs = narration["srt"].exists() and narration["srt"].stat().st_size > 10
    if burn_subs and not have_subs:
        print("    [!] Subtitles khaali hain, bina subs ke bana raha hoon")
    if burn_subs and have_subs:
        ass = _srt_to_ass(narration["srt"], size,
                          work_dir / f"captions_{label}.ass", look)
        filters.append(f"[0:v]subtitles={ass.name}[v]")
        video_map = "[v]"
    else:
        video_map = "0:v"

    if music:
        filters.append(
            f"[2:a]volume={config.MUSIC_VOLUME_DB}dB,afade=t=out:st="
            f"{max(0, narration['total'] - 3):.2f}:d=3[bg];"
            f"[1:a][bg]amix=inputs=2:duration=first:dropout_transition=0[a]")
        audio_map = "[a]"
    else:
        audio_map = "1:a"

    if filters:
        args += ["-filter_complex", ";".join(filters)]
    args += ["-map", video_map, "-map", audio_map,
             "-c:v", "libx264", "-preset", "medium", "-crf", "20",
             "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
             "-shortest", "-movflags", "+faststart", out_name]

    _run(args, cwd=work_dir)
    size_mb = out_path.stat().st_size / 1_048_576
    print(f"    {out_name} ready ({size_mb:.1f} MB)")
    return out_path
