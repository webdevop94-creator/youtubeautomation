"""Act each beat out with 3D cartoon characters instead of stock footage.

Drop-in replacement for visuals.fetch_visuals: same call, same return shape, so
video.build treats the result as ordinary clips and captions, music and the
narration track all keep working untouched.

The rendering itself lives in scene3d/ and runs under node -- three.js in
headless Chrome, which rasterises the way a game does. That is the whole reason
this is affordable: the same minute of video takes hours to ray-trace and about
two minutes to rasterise, on a laptop with no GPU.

The mouth is driven by the narration's own loudness, sampled once per frame, so
it stops when the voice stops. A timer instead is what makes a talking
character look dubbed.
"""
import array
import json
import shutil
import subprocess
from pathlib import Path

import config

ROOT = Path(__file__).resolve().parent / "scene3d"
RENDERER = ROOT / "render.js"
MODELS = ROOT / "assets" / "mixamo"

# Characters that render correctly, in the order a video prefers them. Each is
# a Mixamo download; they share one skeleton, so any of them can play any clip.
# char_c.fbx is deliberately absent -- it loads without error but never appears
# on camera.
CAST = ["char_talking.fbx", "char_ty.fbx", "char_b.fbx"]

# One room for the whole video. Changing room every beat reads as a different
# scene each time rather than a conversation, so the camera moves instead.
ROOMS = ["classroom", "home", "park", "shop", "office", "clinic"]
SHOTS = ["wide", "left", "wide", "right"]

# Rendered small and scaled up by video.build. Frame cost grows with pixels and
# nothing in the scene carries detail that survives a 720p -> 1080p trip.
LANDSCAPE = (1280, 720)
VERTICAL = (720, 1280)

RENDER_TIMEOUT = 900


class Unavailable(RuntimeError):
    """node, Chrome or the models are missing -- caller should fall back."""


def available() -> bool:
    """True when a 3D render can actually be attempted."""
    if not RENDERER.exists() or shutil.which("node") is None:
        return False
    return sum(1 for name in CAST if (MODELS / name).exists()) >= 1


def _levels(audio: Path, start: float, seconds: float, fps: int) -> list:
    """Loudness of the narration, one value per frame, roughly 0..1.

    Decoded at a low sample rate on purpose: this drives a mouth, not a meter,
    and 8 kHz keeps a three-minute track under two megabytes.
    """
    rate = 8000
    raw = subprocess.run(
        [config.FFMPEG, "-v", "error", "-ss", f"{start:.3f}", "-i", str(audio),
         "-t", f"{seconds:.3f}", "-ac", "1", "-ar", str(rate),
         "-f", "s16le", "-"],
        capture_output=True, check=True).stdout

    samples = array.array("h")
    samples.frombytes(raw[:len(raw) - len(raw) % 2])

    frames = max(1, round(seconds * fps))
    window = max(1, len(samples) // frames)
    out = []
    for i in range(frames):
        chunk = samples[i * window:(i + 1) * window]
        if not chunk:
            out.append(0.0)
            continue
        peak = max(abs(s) for s in chunk)
        out.append(round(min(1.0, peak / 9000), 3))
    return out


def _cast_for(seed: int) -> tuple:
    """Two different characters, rotated so consecutive videos are not identical."""
    have = [name for name in CAST if (MODELS / name).exists()]
    if not have:
        raise Unavailable("scene3d/assets/mixamo mein koi character nahi mila")
    first = have[seed % len(have)]
    second = have[(seed + 1) % len(have)] if len(have) > 1 else first
    return first, second


def _render_beat(job: dict, dest: Path) -> None:
    proc = subprocess.run(["node", str(RENDERER), str(dest.with_suffix(".json"))],
                          cwd=ROOT, capture_output=True, text=True,
                          timeout=RENDER_TIMEOUT)
    if proc.returncode != 0 or not dest.exists():
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        raise RuntimeError(detail[-1] if detail else "render.js chup-chaap fail hua")


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

    actor_a, actor_b = _cast_for(seed)
    room = ROOMS[seed % len(ROOMS)]
    fps = config.FPS
    assets, start = [], 0.0

    for i, beat in enumerate(beats):
        seconds = max(1.2, beat["duration"])
        dest = out_dir / f"beat_{i:02d}.mp4"
        job = {
            "out": str(dest),
            "width": size[0], "height": size[1], "fps": fps,
            "seconds": round(seconds, 3),
            "levels": _levels(Path(audio), start, seconds, fps),
            "room": room,
            "actorA": f"./assets/mixamo/{actor_a}",
            "actorB": f"./assets/mixamo/{actor_b}",
            # Two genuinely different models need no disguising.
            "varyB": actor_a == actor_b,
            # Whoever is not speaking listens, so the pair reads as a
            # conversation rather than two narrators.
            "speaker": i % 2,
            "shot": SHOTS[i % len(SHOTS)],
        }
        dest.with_suffix(".json").write_text(json.dumps(job), encoding="utf-8")
        _render_beat(job, dest)

        assets.append({"path": dest, "is_image": False, "credit": None})
        print(f"    scene {i + 1}/{len(beats)} ready")
        start += seconds

    return assets
