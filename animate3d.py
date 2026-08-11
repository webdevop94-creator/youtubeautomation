"""Act each beat out with 3D cartoon characters instead of stock footage.

Drop-in replacement for visuals.fetch_visuals: same call, same return shape, so
video.build treats the result as ordinary clips and captions, music and the
narration track all keep working untouched.

The rendering itself lives in scene3d/ and runs under node -- three.js in
headless Chrome, which rasterises the way a game does. That is the whole reason
this is affordable: the same minute of video takes hours to ray-trace and about
two minutes to rasterise, on a laptop with no GPU.

The mouth is driven by the narration itself, sampled once per frame, so it
stops when the voice stops. A timer instead is what makes a talking character
look dubbed. Two values come out of the audio, not one: how far the jaw is
down, and how wide the mouth is spread. See _analyse for why one was not
enough.
"""
import array
import json
import math
import os
import shutil
import subprocess
from pathlib import Path

import config

ROOT = Path(__file__).resolve().parent / "scene3d"
RENDERER = ROOT / "render.js"
MODELS = ROOT / "assets" / "mixamo"

# Characters that render correctly. Each is a Mixamo download; they share one
# skeleton, so any of them can play any clip.
#
# Grouped by gender because a dialogue script assigns one. Speaker 0 is written
# as a boy and read by a male voice, speaker 1 as a girl read by a female
# voice, and the models have to agree. The flat list this replaced handed out
# whichever model came first, which put the girl on screen speaking in the male
# voice -- and Hindi conjugates by gender, so the mismatch was in the words too.
#
# Two models are deliberately absent. char_c.fbx loads without error but never
# appears on camera. char_b.fbx animates correctly from the neck down, but
# rests with its head thrown back and keeps looking at the ceiling through the
# scene -- its bind pose differs from the others' in a way retargeting does not
# recover, and a character talking at the ceiling is worse than one fewer
# character.
CAST = {
    "male": ["char_ty.fbx"],
    "female": ["char_talking.fbx"],
}
ALL_CAST = [name for names in CAST.values() for name in names]

# One set for the whole video. Changing it every beat reads as a different
# scene each time rather than a conversation, so the camera moves instead.
#
# The family house, inside and out. The classroom and clinic and shop are gone
# from the rotation: they were the same three flat planes in different colours,
# and a channel about two children at home has no reason to keep visiting an
# office. Both sets here are built room by room in scene3d/scene.html.
ROOMS = ["house_in", "house_out"]
SHOTS = ["wide", "left", "wide", "right"]

# Actions the body performs rather than the face. These get their own framing:
# see the "action" view in scene.html.
PHYSICAL = {"run", "fight", "jump"}

# Which Mixamo download plays each action. These are ordinary free clips from
# mixamo.com; every Mixamo character shares one skeleton, so any clip drives
# any of the cast.
#
# A missing file is not an error. The pipeline has to keep publishing while the
# library is still being filled in, so an action with no clip falls back to
# talking -- the line is still said, with the wrong body. MISSING_CLIPS lists
# what was asked for and not found, which is the only way to know a video came
# out flatter than it was written.
# Several names per action, first one found wins. Mixamo names a download
# after the animation, not after what you want it for, so this accepts both
# the tidy anim_<action>.fbx name and whatever the file was actually called
# when it landed in Downloads -- renaming a working file to satisfy a lookup
# table is how a library ends up with two copies of everything.
ACTION_CLIPS = {
    "talk":     ["anim_talk.fbx", "Talking.fbx", "char_talking.fbx"],
    "ask":      ["anim_ask.fbx", "Shrugging.fbx", "Asking Question.fbx"],
    "laugh":    ["anim_laugh.fbx", "Laughing.fbx"],
    "surprise": ["anim_surprise.fbx", "Surprised.fbx"],
    "think":    ["anim_think.fbx", "Thinking.fbx"],
    "run":      ["anim_run.fbx", "Running.fbx", "Fast Run.fbx"],
    # Capoeira first on purpose. This plays to families, and a martial art that
    # looks like dancing reads as a scuffle between friends; "Punch To Elbow
    # Combo" reads as someone being hit. The punch clips stay as fallbacks for
    # a library that has them and not the other.
    "fight":    ["anim_fight.fbx", "Capoeira.fbx", "Fighting Idle.fbx",
                 "Punch To Elbow Combo.fbx", "Boxing.fbx", "Punching.fbx"],
    "jump":     ["anim_jump.fbx", "Jumping.fbx", "Jump.fbx",
                 "Dancing Running Man.fbx", "char_jump.fbx"],
}
# The talking clip is the one file this cannot run without, and it is also a
# character rather than a bare animation, so it is named separately.
TALK_FALLBACK = "char_talking.fbx"
MISSING_CLIPS = set()


def _action_clip(action: str) -> str:
    """Renderer-relative path to the animation for this action."""
    for name in ACTION_CLIPS.get(action or "talk", ACTION_CLIPS["talk"]):
        if (MODELS / name).exists():
            return f"./assets/mixamo/{name}"
    if action and action != "talk":
        MISSING_CLIPS.add(action)
    return f"./assets/mixamo/{TALK_FALLBACK}"

# Rendered small and scaled up by video.build. Frame cost grows with pixels and
# nothing in the scene carries detail that survives the trip up to 1080p.
#
# Tunable because the two machines that render are not comparable. This laptop
# reaches ~12 fps through ANGLE's default backend; a cloud runner has no GPU at
# all and falls back to pure software, where the same job took 56 minutes. Cost
# scales with pixel count, so 720 -> 540 is a little over half the work for a
# difference no one watching a flat-shaded cartoon on a phone will find.
RENDER_HEIGHT = int(os.getenv("RENDER_HEIGHT", "720"))
_W = round(RENDER_HEIGHT * 16 / 9 / 2) * 2      # even numbers: h264 needs them
LANDSCAPE = (_W, RENDER_HEIGHT)
VERTICAL = (RENDER_HEIGHT, _W)

RENDER_TIMEOUT = 900


class Unavailable(RuntimeError):
    """node, Chrome or the models are missing -- caller should fall back."""


def available() -> bool:
    """True when a 3D render can actually be attempted."""
    if not RENDERER.exists() or shutil.which("node") is None:
        return False
    return any((MODELS / name).exists() for name in ALL_CAST)


# --- driving the mouth from the narration ----------------------------------
# Peak loudness was the first driver and it produced a flap rather than a
# mouth. Measured on a real 68-second narration: 54% of frames came out pinned
# at fully open, 16% fully shut, and a fifth of all frames swung more than a
# third of the range in a single frame. Peak is why -- almost any voiced 33 ms
# window contains one loud sample, so the value sat at the ceiling through
# every word and fell off a cliff between them.
#
# Three things replace it, and the mouth needs all three:
#
#   RMS in decibels, not linear peak. Speech covers roughly 30 dB of useful
#   range, and linear amplitude crushes all of it into the top of the scale.
#
#   One reference level for the whole track, not per beat. Normalising each
#   beat on its own turns a deliberately quiet line into a shouted one.
#
#   Attack and release, because a jaw has weight. It opens quickly and closes
#   more slowly, and it never crosses the full range in one 33 ms frame.
#
# The second output is width, and it is the difference between a mouth and a
# hole that grows. Loudness can only say how far the jaw is down, so every
# sound came out the same shape. Zero-crossing rate separates bright sounds
# (ee, s, sh) from dark ones (oo, o) -- a spread mouth from a pursed one --
# which is a fair approximation of visemes from a signal this cheap.
SAMPLE_RATE = 8000

# How far below the loudest speech still counts as movement. Wider makes a
# mouth that twitches at room tone; narrower makes one that only opens when
# shouted at.
SPEECH_RANGE_DB = 34.0

# Per-frame approach rates at 30 fps: roughly 30 ms to open, 90 ms to close.
ATTACK = 0.62
RELEASE = 0.27

# Analysing a track is a few seconds of pure Python, and every beat of a video
# asks about the same track.
_TRACK_CACHE = {}


def _percentile(values: list, q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * (len(ordered) - 1)))]


def _analyse(audio: Path, fps: int) -> tuple:
    """(open, wide) for the whole narration, one value per frame, each 0..1."""
    raw = subprocess.run(
        [config.FFMPEG, "-v", "error", "-i", str(audio), "-ac", "1",
         "-ar", str(SAMPLE_RATE), "-f", "s16le", "-"],
        capture_output=True, check=True).stdout
    samples = array.array("h")
    samples.frombytes(raw[:len(raw) - len(raw) % 2])

    hop = max(1, SAMPLE_RATE // fps)
    frames = max(1, len(samples) // hop)
    # The window is wider than the hop on purpose. At 30 fps a frame is 33 ms,
    # short enough that the gap between two glottal pulses reads as silence and
    # a held vowel comes out flickering.
    window = hop * 2

    energy_db, zcr = [], []
    for i in range(frames):
        chunk = samples[i * hop:i * hop + window]
        if not chunk:
            energy_db.append(-120.0)
            zcr.append(0.0)
            continue
        total, crossings, prev = 0, 0, chunk[0]
        for sample in chunk:
            total += sample * sample
            if (sample >= 0) != (prev >= 0):
                crossings += 1
            prev = sample
        rms = math.sqrt(total / len(chunk))
        energy_db.append(20.0 * math.log10(rms + 1e-9))
        zcr.append(crossings / len(chunk))

    # The 92nd percentile rather than the maximum: one clipped consonant should
    # not define what "fully open" means for the rest of the video.
    loud = _percentile([d for d in energy_db if d > -80], 0.92)
    floor = loud - SPEECH_RANGE_DB

    # ZCR is measured only where there is speech. Silence crosses zero on
    # dither noise alone, so including it puts the top of the width scale in
    # the gaps between words.
    voiced = [z for z, d in zip(zcr, energy_db) if d > floor]
    z_lo, z_hi = _percentile(voiced, 0.15), _percentile(voiced, 0.85)
    z_span = max(1e-6, z_hi - z_lo)

    norms = [min(1.0, max(0.0, (d - floor) / SPEECH_RANGE_DB)) for d in energy_db]

    # Put the ordinary speaking level at half open. Decibels compress so hard
    # that plain narration otherwise lands around 0.85 and stays there: the
    # mouth still moved, but between wide and wider, which reads as a hole that
    # breathes. Anchoring on the track's own median means a stressed vowel is
    # the only thing that reaches the top of the range, which is what makes the
    # top of the range mean anything.
    mid = _percentile([n for n in norms if n > 0.15], 0.5) or 0.5
    mid = min(0.95, max(0.05, mid))

    opens, wides = [], []
    level, width = 0.0, 0.4
    for n, z in zip(norms, zcr):
        target = (0.5 * n / mid) if n < mid else (0.5 + 0.5 * (n - mid) / (1 - mid))
        target = min(1.0, max(0.0, target))
        level += (target - level) * (ATTACK if target > level else RELEASE)
        opens.append(round(level, 3))

        # Width means nothing while no sound is being made, so between words it
        # holds its last value instead of snapping back to neutral -- a mouth
        # that resets its shape in every pause reads as chewing.
        if target > 0.08:
            width += (min(1.0, max(0.0, (z - z_lo) / z_span)) - width) * 0.35
        wides.append(round(width, 3))

    return opens, wides


def _mouth(audio: Path, start: float, seconds: float, fps: int) -> dict:
    """This beat's slice of the mouth track, as render.js expects it."""
    key = (str(audio), fps)
    if key not in _TRACK_CACHE:
        _TRACK_CACHE[key] = _analyse(Path(audio), fps)
    track_open, track_wide = _TRACK_CACHE[key]

    frames = max(1, round(seconds * fps))
    first = int(round(start * fps))

    def cut(values: list, pad: float) -> list:
        out = list(values[first:first + frames])
        # A beat can run a frame or two past the end of the narration when its
        # duration was rounded up. A closed mouth is the right tail.
        return out + [pad] * (frames - len(out))

    return {"levels": cut(track_open, 0.0), "spread": cut(track_wide, 0.4)}


def _cast_for(seed: int, gendered: bool) -> tuple:
    """(actor for speaker 0, actor for speaker 1).

    A dialogue script has already decided that speaker 0 is a boy and speaker 1
    a girl -- the voices and the Hindi verb endings both commit to it -- so the
    models are chosen by gender and only rotated within it. Narration commits
    to nothing, so there the pair rotates freely and consecutive videos get a
    different cast.
    """
    def pick(names: list, offset: int) -> str:
        have = [n for n in names if (MODELS / n).exists()]
        return have[(seed + offset) % len(have)] if have else ""

    if gendered:
        first, second = pick(CAST["male"], 0), pick(CAST["female"], 0)
        if first and second:
            return first, second
        # One gender missing from the library. Two characters who look alike
        # beats a video that does not render, and VARIANT still tells them
        # apart on screen.
        print("    [!] dono gender ke model nahi mile — jo hai usi se kaam chalaya")

    first, second = pick(ALL_CAST, 0), pick(ALL_CAST, 1)
    if not first:
        raise Unavailable("scene3d/assets/mixamo mein koi character nahi mila")
    return first, second or first


# A beat renders in its own Chrome. After a run of them one launch will
# occasionally die on nothing in particular -- the same job re-run by hand
# succeeds immediately. Without a retry that single flake discarded ten good
# scenes and dropped the whole video to stock footage, which is a far worse
# outcome than waiting another minute.
RENDER_TRIES = 2


def _render_beat(job: dict, dest: Path) -> None:
    last = ""
    for attempt in range(RENDER_TRIES):
        proc = subprocess.run(["node", str(RENDERER), str(dest.with_suffix(".json"))],
                              cwd=ROOT, capture_output=True, text=True,
                              timeout=RENDER_TIMEOUT)
        if proc.returncode == 0 and dest.exists():
            return
        # Keep several lines, not the last one. Node prints its version banner
        # last when it dies, so a one-line report said "Node.js v24.18.0" and
        # nothing about what actually failed.
        lines = [ln for ln in (proc.stderr or proc.stdout or "").strip().splitlines()
                 if ln.strip()]
        last = " | ".join(lines[-4:]) or f"exit {proc.returncode}, koi output nahi"
        if attempt + 1 < RENDER_TRIES:
            print(f"    [!] scene fail ({last[:110]}) — dobara koshish")
            dest.unlink(missing_ok=True)
    raise RuntimeError(last)


def fetch_visuals(beats: list, work_dir: Path, vertical: bool, label: str,
                  category: str = "general", audio: Path = None,
                  seed: int = 0) -> list:
    """Render one clip per beat. Returns video.build's asset list."""
    if not available():
        raise Unavailable("node ya scene3d/ nahi mila")
    if audio is None or not Path(audio).exists():
        raise Unavailable("narration audio ke bina hoth nahi hil sakte")

    print(f"[5/7] 3D scene render kar raha hoon ({label})...")
    size = VERTICAL if vertical else LANDSCAPE
    out_dir = work_dir / f"scene3d_{label}"
    out_dir.mkdir(parents=True, exist_ok=True)

    actor_a, actor_b = _cast_for(seed, any(b.get("speaker") is not None
                                           for b in beats))
    room = ROOMS[seed % len(ROOMS)]
    fps = config.FPS
    assets, start = [], 0.0

    for i, beat in enumerate(beats):
        seconds = max(1.2, beat["duration"])
        dest = out_dir / f"beat_{i:02d}.mp4"
        # The script says who is speaking. Alternating on the beat index is the
        # fallback for narration, where nobody is: it at least keeps one mouth
        # still while the other moves.
        speaker = beat.get("speaker")
        action = beat.get("action") or "talk"
        job = {
            "out": str(dest),
            "width": size[0], "height": size[1], "fps": fps,
            "seconds": round(seconds, 3),
            **_mouth(Path(audio), start, seconds, fps),
            "room": room,
            "actorA": f"./assets/mixamo/{actor_a}",
            "actorB": f"./assets/mixamo/{actor_b}",
            # Two genuinely different models need no disguising.
            "varyB": actor_a == actor_b,
            # Whoever is not speaking listens, so the pair reads as a
            # conversation rather than two narrators.
            "speaker": (i % 2) if speaker is None else int(speaker),
            # A line whose action is physical gets framed for the body rather
            # than the face. The close shots crop at the chest, which is above
            # everything a run or a scuffle actually does.
            "shot": "action" if action in PHYSICAL else SHOTS[i % len(SHOTS)],
            "clip": _action_clip(action),
        }
        dest.with_suffix(".json").write_text(json.dumps(job), encoding="utf-8")
        _render_beat(job, dest)

        assets.append({"path": dest, "is_image": False, "credit": None})
        print(f"    scene {i + 1}/{len(beats)} ready  "
              f"({'A' if job['speaker'] == 0 else 'B'} {action})")
        start += seconds

    if MISSING_CLIPS:
        print(f"    [!] in actions ka animation nahi mila, talk chal gaya: "
              f"{', '.join(sorted(MISSING_CLIPS))}")
        # One suggested filename per action, not the whole candidate list.
        # ACTION_CLIPS holds a list per action so a Mixamo download works under
        # whatever name it arrived with; joining those lists as if they were
        # strings raised TypeError and killed a finished video at the last
        # step, after every scene had already rendered.
        wanted = ", ".join(ACTION_CLIPS[a][0] for a in sorted(MISSING_CLIPS)
                           if ACTION_CLIPS.get(a))
        print(f"        mixamo.com se download karke {MODELS} mein daalo: {wanted}")
    return assets
