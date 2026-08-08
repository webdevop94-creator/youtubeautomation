"""Kokoro synthesis worker. Runs inside .venv-tts, NOT the main venv.

Kokoro needs spacy, and spacy has no Python 3.14 wheels, so it lives in its own
Python 3.12 environment and is driven from here by subprocess.

Called as:
    .venv-tts\\Scripts\\python.exe tts_kokoro_worker.py job.json

job.json: {"voice": "hm_omega", "speed": 1.0, "lang": "h",
           "items": [{"text": "...", "out": "C:\\...\\beat_00.wav"}, ...]}

Every beat is synthesised in one process because loading the model costs far
more than generating a beat -- doing it per beat would multiply that by twelve.
Progress goes to stderr so the parent can show it without parsing stdout.
"""
import json
import sys

import numpy as np
import soundfile as sf
from kokoro import KPipeline

SAMPLE_RATE = 24_000


def main() -> int:
    job = json.loads(open(sys.argv[1], encoding="utf-8").read())
    items = job["items"]

    print(f"kokoro: model load ho raha hai (lang={job['lang']}, "
          f"voice={job['voice']})...", file=sys.stderr, flush=True)
    pipeline = KPipeline(lang_code=job["lang"])

    for i, item in enumerate(items, 1):
        chunks = [audio for _, _, audio in
                  pipeline(item["text"], voice=job["voice"], speed=job["speed"],
                           split_pattern=r"\n+")]
        if not chunks:
            print(f"kokoro: beat {i} khaali aaya", file=sys.stderr, flush=True)
            return 2
        waveform = np.concatenate([np.asarray(c, dtype="float32") for c in chunks])
        sf.write(item["out"], waveform, SAMPLE_RATE)
        print(f"kokoro: beat {i}/{len(items)}  "
              f"{len(waveform) / SAMPLE_RATE:.1f}s", file=sys.stderr, flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
