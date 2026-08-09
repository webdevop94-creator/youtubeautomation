"""ElevenLabs narration, with an automatic fall back to edge-tts.

ElevenLabs sounds markedly better in Hindi than anything free, but it bills
per CHARACTER and the free tier is 10,000 a month -- roughly five videos. This
channel wants three a day. So the interesting part of this module is not the
synthesis, it is what happens when the credits run out: the run must continue
on edge-tts rather than stop.

Quota is never assumed, only observed. The API answers 401 with
"quota_exceeded" when it is out, and that answer is the trigger.
"""
import time
from pathlib import Path

import requests

import config

BASE = "https://api.elevenlabs.io/v1"
MODEL = "eleven_multilingual_v2"   # the model that actually speaks Hindi

# Set once per run when the API says the credits are gone, so the remaining
# beats do not each pay for their own failed request.
_exhausted = False


def available() -> bool:
    return bool(config.ELEVEN_API_KEY) and not _exhausted


# How hard the voice performs, per action, as (stability, style) overriding the
# configured defaults. Lower stability is a less even read, which is what makes
# a laugh sound like a laugh; raising it steadies a line that has to land.
DELIVERY = {
    "laugh":    (0.20, 0.90),
    "surprise": (0.22, 0.85),
    "jump":     (0.25, 0.85),
    "run":      (0.28, 0.80),
    "fight":    (0.28, 0.80),
    "ask":      (0.40, 0.70),
    "think":    (0.60, 0.45),
}


def voice_for(label: str, speaker: int = None) -> str:
    """Which voice says this.

    Who is speaking wins over which format it is. Two characters sharing one
    voice is the failure that matters; long-form and Shorts sounding alike is
    not, and there are only so many voices in the free tier.
    """
    if speaker is not None:
        return config.ELEVEN_VOICE_B if speaker == 1 else config.ELEVEN_VOICE
    if label.startswith("shorts") and config.ELEVEN_VOICE_SHORTS:
        return config.ELEVEN_VOICE_SHORTS
    return config.ELEVEN_VOICE


class QuotaGone(Exception):
    """Credits finished. Caller should fall back rather than retry."""


def synth(text: str, out_path: Path, label: str = "long", tries: int = 2,
          speaker: int = None, action: str = None) -> None:
    """Write one beat to out_path as mp3. Raises QuotaGone when out of credits."""
    global _exhausted

    stability, style = DELIVERY.get(
        action, (config.ELEVEN_STABILITY, config.ELEVEN_STYLE))
    body = {
        "text": text,
        "model_id": MODEL,
        "voice_settings": {
            "stability": stability,
            "similarity_boost": 0.75,
            # Style is what separates a performance from a newsreader; it is
            # also what makes a joke land.
            "style": style,
            "use_speaker_boost": True,
        },
    }
    url = f"{BASE}/text-to-speech/{voice_for(label, speaker)}"
    headers = {"xi-api-key": config.ELEVEN_API_KEY, "Content-Type": "application/json"}

    for attempt in range(tries):
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=180)
        except Exception:
            if attempt + 1 < tries:
                time.sleep(3)
                continue
            raise

        if resp.status_code == 200 and len(resp.content) > 2000:
            out_path.write_bytes(resp.content)
            return

        body_text = resp.text[:300]
        if resp.status_code in (401, 402) and "quota" in body_text.lower():
            _exhausted = True
            raise QuotaGone(body_text)
        if resp.status_code == 429 and attempt + 1 < tries:
            time.sleep(5)
            continue

        raise RuntimeError(f"ElevenLabs {resp.status_code}: {body_text}")


def estimate_characters(beats: list) -> int:
    return sum(len(b.get("text", "")) for b in beats)
