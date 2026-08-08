"""Narration, one audio file per beat, with subtitles timed to match.

Synthesising each beat separately gives us its exact duration, which is what
lets the visuals line up with the narration without any manual timing.

Two engines, selected by config.TTS_ENGINE:
  "edge"   Microsoft edge-tts. Cloud, free, and it reports word or sentence
           boundaries, which gives the most accurate captions.
  "kokoro" Local Kokoro-82M (see voice_kokoro.py). Runs offline on CPU but
           returns audio only, so captions fall back to proportional timing.
"""
import asyncio
import subprocess
from pathlib import Path

import edge_tts

import config
import voice_eleven

TICKS_PER_SECOND = 10_000_000  # edge-tts reports offsets in 100-nanosecond ticks
MAX_LINE_CHARS = 40
MAX_LINE_WORDS = 7


def _split_sentence(sentence: dict) -> list:
    """Spread a sentence's timing across its words, weighted by word length.

    Indian-locale voices only emit SentenceBoundary events, so this is what
    keeps captions in sync for hi-IN / en-IN.
    """
    words = sentence["text"].split()
    if not words:
        return []

    weights = [len(w) + 1 for w in words]
    total_weight = sum(weights)
    span = max(0.2, sentence["end"] - sentence["start"])

    out, cursor = [], sentence["start"]
    for word, weight in zip(words, weights):
        length = span * weight / total_weight
        out.append({"start": cursor, "end": cursor + length, "text": word})
        cursor += length
    return out


async def _synth_one(text: str, out_path: Path) -> list:
    communicate = edge_tts.Communicate(
        text, config.VOICE, rate=config.VOICE_RATE, pitch=config.VOICE_PITCH,
        boundary="WordBoundary")

    words, sentences = [], []
    with open(out_path, "wb") as fh:
        async for chunk in communicate.stream():
            kind = chunk["type"]
            if kind == "audio":
                fh.write(chunk["data"])
            elif kind in ("WordBoundary", "SentenceBoundary"):
                event = {
                    "start": chunk["offset"] / TICKS_PER_SECOND,
                    "end": (chunk["offset"] + chunk["duration"]) / TICKS_PER_SECOND,
                    "text": chunk["text"],
                }
                (words if kind == "WordBoundary" else sentences).append(event)

    if out_path.stat().st_size == 0:
        raise RuntimeError(f"TTS ne khaali audio banaya: {text[:60]}")

    if words:
        return words
    if sentences:
        return [w for s in sentences for w in _split_sentence(s)]
    return []


def _duration(path: Path) -> float:
    out = subprocess.run(
        [config.FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def _srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _build_srt(word_groups: list, path: Path) -> None:
    """Group word timings into short caption lines, never merging across beats.

    A line that straddles two beats would show the next beat's words while the
    previous beat's audio is still playing.
    """
    lines = []
    for beat_words in word_groups:
        current = []
        for word in beat_words:
            current.append(word)
            chars = sum(len(w["text"]) + 1 for w in current)
            if chars >= MAX_LINE_CHARS or len(current) >= MAX_LINE_WORDS:
                lines.append(current)
                current = []
        if current:
            lines.append(current)

    blocks, prev_end = [], 0.0
    for i, group in enumerate(lines, 1):
        start, end = max(group[0]["start"], prev_end), group[-1]["end"]
        if end <= start:
            end = start + 0.6
        prev_end = end
        text = " ".join(w["text"] for w in group).strip()
        blocks.append(f"{i}\n{_srt_time(start)} --> {_srt_time(end)}\n{text}\n")

    path.write_text("\n".join(blocks), encoding="utf-8")


def narrate(beats: list, work_dir: Path, label: str) -> dict:
    """Synthesise every beat, concat into one track, and write matching subtitles.

    Returns {"audio", "srt", "total", "beats": [{"text","keywords","duration"}]}
    """
    if config.TTS_ENGINE == "kokoro":
        speaker = config.KOKORO_VOICE
    elif config.TTS_ENGINE == "eleven" and voice_eleven.available():
        speaker = voice_eleven.voice_for(label)
        chars = voice_eleven.estimate_characters(beats)
        print(f"[4/7] Voice bana raha hoon ({label}, elevenlabs, "
              f"~{chars:,} characters)...")
        speaker = None
    else:
        speaker = config.VOICE
    if speaker is not None:
        print(f"[4/7] Voice bana raha hoon ({label}, {config.TTS_ENGINE}: "
              f"{speaker})...")
    audio_dir = work_dir / f"audio_{label}"
    audio_dir.mkdir(parents=True, exist_ok=True)

    parts, word_groups, offset = [], [], 0.0
    files = [audio_dir / f"beat_{i:02d}.mp3" for i in range(len(beats))]

    if config.TTS_ENGINE == "kokoro":
        # Every beat in a single worker run: the model load dominates the cost,
        # so one process for the whole video instead of one per beat.
        import voice_kokoro
        voice_kokoro.synth_batch([b["text"] for b in beats], files)

    async def run_all():
        nonlocal offset
        for i, beat in enumerate(beats):
            part = files[i]
            words = []
            if config.TTS_ENGINE == "kokoro":
                pass                      # already synthesised in one batch
            elif config.TTS_ENGINE == "eleven" and voice_eleven.available():
                try:
                    voice_eleven.synth(beat["text"], part, label)
                except voice_eleven.QuotaGone:
                    # Credits gone mid-video. Finish on edge-tts rather than
                    # abandon a video that is most of the way done.
                    print("    [!] ElevenLabs credits khatam — "
                          "baaki beats edge-tts par")
                    words = await _synth_one(beat["text"], part)
                except RuntimeError as exc:
                    print(f"    [!] ElevenLabs fail ({str(exc)[:70]}) — edge-tts par")
                    words = await _synth_one(beat["text"], part)
            else:
                words = await _synth_one(beat["text"], part)
            seconds = _duration(part)
            if not words:
                # Kokoro emits audio only, no boundary events. Spreading the
                # beat's words across its measured duration is the same
                # approximation already used for hi-IN sentence boundaries.
                words = _split_sentence(
                    {"text": beat["text"], "start": 0.0, "end": seconds})
            shifted = []
            for word in words:
                start = min(word["start"], seconds) + offset
                end = min(word["end"], seconds) + offset
                shifted.append({"start": start, "end": max(end, start + 0.15),
                                "text": word["text"]})
            word_groups.append(shifted)
            parts.append({**beat, "file": part, "duration": seconds})
            offset += seconds
            print(f"    beat {i + 1}/{len(beats)}  {seconds:5.1f}s")

    asyncio.run(run_all())

    # concat demuxer resolves entries relative to the list file's own directory,
    # so these must be bare filenames, not paths relative to the CWD.
    list_file = audio_dir / "concat.txt"
    list_file.write_text(
        "\n".join(f"file '{p['file'].name}'" for p in parts), encoding="utf-8")

    combined = work_dir / f"voice_{label}.mp3"
    subprocess.run(
        [config.FFMPEG, "-y", "-v", "error", "-f", "concat", "-safe", "0",
         "-i", str(list_file), "-c", "copy", str(combined)], check=True)

    srt = work_dir / f"subtitles_{label}.srt"
    _build_srt(word_groups, srt)

    total = _duration(combined)
    captioned = sum(len(g) for g in word_groups)
    print(f"    Total: {total:.1f}s ({total / 60:.1f} min), {captioned} words captioned")

    return {
        "audio": combined,
        "srt": srt,
        "total": total,
        "beats": [{"text": p["text"], "keywords": p["keywords"], "duration": p["duration"]}
                  for p in parts],
    }
