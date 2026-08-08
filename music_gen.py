"""Generate a cheerful instrumental backing track from scratch.

Downloading "free" kids music is where copyright trouble starts -- licences get
misread, tracks get relicensed, and Content ID claims arrive months later.
Synthesising a simple major-pentatonic loop here means the audio is originally
ours, so there is nothing to claim.

Pure standard library: no numpy, no external audio files.
"""
import math
import random
import struct
import wave
from pathlib import Path

SAMPLE_RATE = 44100

# C major pentatonic - no semitone clashes, so any note order sounds pleasant.
PENTATONIC = [261.63, 293.66, 329.63, 392.00, 440.00, 523.25, 587.33, 659.25]
BASS = [130.81, 174.61, 196.00, 164.81]


def _envelope(i: int, total: int, attack: float = 0.02, release: float = 0.35) -> float:
    """Soft attack and release so notes do not click."""
    a = int(total * attack)
    r = int(total * release)
    if i < a:
        return i / max(1, a)
    if i > total - r:
        return max(0.0, (total - i) / max(1, r))
    return 1.0


def _note(freq: float, seconds: float, volume: float, warm: bool = True) -> list:
    """One note. A little second harmonic keeps it from sounding like a test tone."""
    total = int(SAMPLE_RATE * seconds)
    step = 2 * math.pi * freq / SAMPLE_RATE
    samples = []
    for i in range(total):
        phase = step * i
        value = math.sin(phase)
        if warm:
            value += 0.28 * math.sin(2 * phase) + 0.12 * math.sin(3 * phase)
            value /= 1.4
        samples.append(value * volume * _envelope(i, total))
    return samples


def _mix_into(track: list, samples: list, offset: int) -> None:
    needed = offset + len(samples)
    if needed > len(track):
        track.extend([0.0] * (needed - len(track)))
    for i, value in enumerate(samples):
        track[offset + i] += value


def generate(duration: float, dest: Path, seed: int = 7, bpm: int = 96) -> Path:
    """Write a looping-friendly instrumental of roughly `duration` seconds."""
    rng = random.Random(seed)
    beat = 60.0 / bpm
    total_samples = int(SAMPLE_RATE * (duration + 1.0))
    track = [0.0] * total_samples

    # Melody: a 4-note phrase that wanders gently around the scale.
    position, index = 0.0, 0
    while position < duration:
        length = beat * rng.choice([0.5, 0.5, 1.0])
        index = max(0, min(len(PENTATONIC) - 1, index + rng.choice([-2, -1, 1, 1, 2])))
        _mix_into(track, _note(PENTATONIC[index], length * 0.95, 0.22),
                  int(position * SAMPLE_RATE))
        position += length

    # Bass: one long note per bar, giving the melody something to sit on.
    position, bar = 0.0, 0
    while position < duration:
        _mix_into(track, _note(BASS[bar % len(BASS)], beat * 2 * 0.95, 0.16, warm=False),
                  int(position * SAMPLE_RATE))
        position += beat * 2
        bar += 1

    # Soft off-beat tick for rhythm, quiet enough to sit under a voice.
    position = beat
    while position < duration:
        _mix_into(track, _note(1046.5, 0.045, 0.05, warm=False),
                  int(position * SAMPLE_RATE))
        position += beat

    cut = int(SAMPLE_RATE * duration)
    track = track[:cut]

    peak = max((abs(v) for v in track), default=1.0) or 1.0
    scale = 0.75 / peak

    dest.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(dest), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(SAMPLE_RATE)
        fh.writeframes(b"".join(
            struct.pack("<h", max(-32767, min(32767, int(v * scale * 32767))))
            for v in track))
    return dest


if __name__ == "__main__":
    out = generate(20.0, Path("music_preview.wav"))
    print("wrote", out.resolve())
