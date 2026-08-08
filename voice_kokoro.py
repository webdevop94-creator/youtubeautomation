"""Kokoro-82M narration: a local Hindi TTS that needs no internet at runtime.

Kokoro depends on spacy, and spacy has no Python 3.14 wheels -- its `blis`
dependency fails to build from source. Rather than pin the whole project back
to 3.12, Kokoro lives in its own environment (`.venv-tts`, Python 3.12) and is
driven from here by subprocess. That also keeps a heavy torch install out of
the main venv.

Set up once:
    C:\\...\\Python312\\python.exe -m venv .venv-tts
    .venv-tts\\Scripts\\pip install kokoro soundfile

Kokoro emits no word-level timings, so subtitles for this engine fall back to
proportional timing (voice._split_sentence handles that).
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import config

SAMPLE_RATE = 24_000
LANG_CODE = "h"  # Hindi. Voices: hf_alpha, hf_beta (F) / hm_omega, hm_psi (M)
TTS_VENV = config.ROOT / ".venv-tts"
WORKER = config.ROOT / "tts_kokoro_worker.py"


def python_path() -> Path:
    exe = TTS_VENV / "Scripts" / "python.exe"          # Windows
    return exe if exe.exists() else TTS_VENV / "bin" / "python"   # Linux/macOS


def available() -> bool:
    return python_path().exists() and WORKER.exists()


def _require() -> Path:
    exe = python_path()
    if not exe.exists():
        raise RuntimeError(
            f"Kokoro ka venv nahi mila: {TTS_VENV}\n"
            f"    Banane ke liye:\n"
            f"      python3.12 -m venv .venv-tts\n"
            f"      .venv-tts\\Scripts\\pip install kokoro soundfile\n"
            f"    Ya .env mein TTS_ENGINE=edge kar do.")
    return exe


def synth_batch(texts: list, out_paths: list) -> None:
    """Synthesise every beat in one worker process, then convert to mp3.

    One process for the whole video: loading the model costs far more than
    generating a beat, so doing it per beat would multiply that by the beat
    count for no benefit.
    """
    exe = _require()
    wavs = [Path(p).with_suffix(".wav") for p in out_paths]
    job = {
        "voice": config.KOKORO_VOICE,
        "speed": config.KOKORO_SPEED,
        "lang": LANG_CODE,
        "items": [{"text": t, "out": str(w)} for t, w in zip(texts, wavs)],
    }

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                     encoding="utf-8") as fh:
        json.dump(job, fh, ensure_ascii=False)
        job_path = fh.name

    try:
        # stderr is inherited so the worker's per-beat progress reaches the log
        # live; a captured pipe would only surface it after the whole run.
        result = subprocess.run([str(exe), str(WORKER), job_path],
                                stdout=subprocess.PIPE, stderr=sys.stderr,
                                text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"Kokoro worker fail (exit {result.returncode}). "
                f"Upar ka error dekho, ya .env mein TTS_ENGINE=edge kar do.")
    finally:
        Path(job_path).unlink(missing_ok=True)

    for wav, mp3 in zip(wavs, out_paths):
        if not wav.exists() or wav.stat().st_size < 1000:
            raise RuntimeError(f"Kokoro ne audio nahi banaya: {wav.name}")
        # The rest of the pipeline concatenates beats with ffmpeg's copy
        # demuxer, which needs every part in the same codec -- so mp3.
        subprocess.run(
            [config.FFMPEG, "-y", "-v", "error", "-i", str(wav),
             "-codec:a", "libmp3lame", "-q:a", "2", str(mp3)], check=True)
        wav.unlink(missing_ok=True)
