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


def voice_for(label: str) -> str:
    """Long-form and Shorts can use different voices."""
    if label.startswith("shorts") and config.ELEVEN_VOICE_SHORTS:
        return config.ELEVEN_VOICE_SHORTS
    return config.ELEVEN_VOICE


class QuotaGone(Exception):
    """Credits finished. Caller should fall back rather than retry."""


def synth(text: str, out_path: Path, label: str = "long", tries: int = 2) -> None:
    """Write one beat to out_path as mp3. Raises QuotaGone when out of credits."""
    global _exhausted

    body = {
        "text": text,
        "model_id": MODEL,
        "voice_settings": {
            "stability": config.ELEVEN_STABILITY,
            "similarity_boost": 0.75,
            # Style is what separates a performance from a newsreader; it is
            # also what makes a joke land.
            "style": config.ELEVEN_STYLE,
            "use_speaker_boost": True,
        },
    }
    url = f"{BASE}/text-to-speech/{voice_for(label)}"
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
