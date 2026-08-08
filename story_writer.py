"""Write original Hindi content for animation videos: jokes, facts, riddles, stories.

This is the other half of the channel. `script_writer` turns real articles into
a factual script and spends most of its effort making sure nothing is invented.
Here everything is invented on purpose, so the guards that matter are different:

  kept     Devanagari check, length check, sanitising
  dropped  fact research, source verification, invented-number detection
           -- there are no sources to check a made-up story against

What each kind may look like on screen decided which kinds exist. Free image
generation cannot hold a character across scenes (tested twice: the same frozen
description and seed produced a different character every time), so the kinds
below are the ones whose scenes are *supposed* to be unrelated. A serial with a
recurring hero would need reference-image conditioning, which is paid.
"""
import json
import re

import config
import script_writer as sw

# One entry per content type: what to write, and how the scenes should look.
KINDS = {
    "jokes": {
        "hindi": "चुटकुले",
        "category": "entertainment",
        "brief": """Write {n} short Hindi jokes (चुटकुले) that are genuinely funny to an
Indian audience -- the everyday kind people actually retell: teacher-student,
husband-wife, Pappu, doctor, boss-employee, shopkeeper, exam, mobile phone.
Each joke is ONE beat: setup then punchline, about {w} words including a short lead-in. Land the punchline on the last sentence. No joke may target religion,
caste, region, disability, gender or anyone's appearance.""",
        "scene_hint": "an everyday Indian setting matching the joke -- classroom, "
                      "clinic, small shop, office desk, kitchen, street",
    },
    "facts": {
        "hindi": "रोचक तथ्य",
        "category": "science",
        "brief": """Write {n} surprising, TRUE facts about space, oceans, animals, the
human body, history or technology. Each fact is ONE beat of about {w} words: state
it, then explain why it is surprising. Only well-established facts that a
curious adult could verify -- no rumours, no "scientists say" without saying
who. If you are unsure a fact is true, choose a different one.""",
        "scene_hint": "the thing the fact is about -- a planet, a deep sea creature, "
                      "a desert, a laboratory, an ancient ruin",
    },
    "riddles": {
        "hindi": "पहेलियाँ",
        "category": "entertainment",
        "brief": """Write {n} Hindi riddles (पहेलियाँ). Each riddle is ONE beat of about {w} words: pose the riddle, tell the viewer to think, then give the answer at the
end of the same beat. Everyday objects and animals -- things a child would
know. Keep them solvable, not obscure.""",
        "scene_hint": "the object or animal that is the answer, shown plainly",
    },
    "stories": {
        "hindi": "कहानियाँ",
        "category": "entertainment",
        "brief": """Write ONE short Hindi moral story (कहानी) told across {n} beats, in the
Panchatantra spirit -- animals or village folk, a simple problem, a clear moral
in the last beat. About {w} words per beat. Original: do not retell a known
story word for word.""",
        "scene_hint": "the setting of that moment -- a forest clearing, a river bank, "
                      "a village path, a tree with birds",
    },
}

SYSTEM = """You write Hindi content for a YouTube animation channel.

LANGUAGE (the text goes straight into a Hindi text-to-speech engine):
- Write in DEVANAGARI (देवनागरी), never Roman script.
- Everyday spoken Hindi, the way people actually talk -- not literary Hindi.
  English words Indians normally use stay, written in Devanagari: मोबाइल, स्कूल,
  ऑफिस, डॉक्टर.
- Vary sentence length. A page of identical short sentences sounds robotic.
- Numbers as digits (5, 100, 2026).
- NO emoji, NO markdown, NO brackets, NO special characters.

CONTENT RULES:
- Everything must be original. Do not reproduce copyrighted lyrics, film
  dialogue, or a published story word for word.
- Nothing cruel, scary, sexual, political or religious. This plays to families.
- Never target religion, caste, region, disability, gender or appearance.

KEYWORDS -- ENGLISH ONLY, never Devanagari. They go to an image generator that
only understands English.
- Name a scene that can be drawn: a place, an object, an action.
- No named real people, no brands, no logos.
- Each beat needs its OWN distinct scene. Do not repeat a scene.

Return ONLY valid JSON. No prose before or after."""

USER = """{brief}

For each beat also give an English scene description for the illustration:
{scene_hint}.

Return JSON with exactly this shape:
{{
  "title": "YouTube title in Devanagari, under 65 characters, makes someone click",
  "thumbnail_text": "3 to 5 words in Devanagari, big and punchy",
  "long_beats": [
    {{"text": "narration in Devanagari",
      "keywords": "2-5 ENGLISH words naming a drawable scene"}}
  ],
  "shorts_beats": [
    {{"text": "narration in Devanagari", "keywords": "english scene words"}}
  ],
  "description": "YouTube description in Devanagari. Two hook lines, then 3 bullets with '-'.",
  "tags": ["12 to 15 lowercase tags, mix Hindi-Roman and English"]
}}

long_beats: exactly {n} beats, each {beat_lo} to {beat_hi} words. The whole
  narration must stay under {max_words} words -- the video has a fixed runtime.
  The first beat is a 2-line hook that makes someone stay. The last beat asks
  for a like and subscribe in one short line.
shorts_beats: 4 beats, 100 to 130 words total. Beat 1 hooks in under 3 seconds,
  the last beat sends them to the full video.
"""


def write_story(kind: str = "jokes", n_beats: int = None) -> dict:
    """Generate an original script. Same shape as script_writer.write_script."""
    if kind not in KINDS:
        raise RuntimeError(f"Unknown kind '{kind}'. Options: {', '.join(KINDS)}")
    spec = KINDS[kind]
    n_beats = n_beats or config.MAX_LONG_BEATS

    chain = " -> ".join(p["name"] for p in sw._providers()) or "koi provider nahi"
    print(f"[2/6] {spec['hindi']} likh raha hoon ({chain})...")

    beat_words = config.WORDS_PER_BEAT
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": USER.format(
            brief=spec["brief"].format(n=n_beats, w=beat_words),
            scene_hint=spec["scene_hint"], n=n_beats,
            beat_lo=int(beat_words * 0.8), beat_hi=int(beat_words * 1.2),
            max_words=int(n_beats * beat_words * 1.2))},
    ]
    data = sw._call_llm(messages)

    # Devanagari drift is the one guard that still applies -- the voice cannot
    # read Roman text convincingly whether the content is true or invented.
    for key in ("long_beats", "shorts_beats"):
        for _ in range(2):
            beats = data.get(key) or []
            drifted = sw._english_beats(beats)
            if not beats or not drifted:
                break
            print(f"    [!] {key}: {len(drifted)} beats Devanagari mein nahi — "
                  f"dobara likhwa raha hoon")
            examples = "\n".join(f'- beat {i + 1}: "{beats[i]["text"][:90]}..."'
                                 for i in drifted[:3])
            messages += [
                {"role": "assistant",
                 "content": json.dumps({key: beats}, ensure_ascii=False)},
                {"role": "user", "content": sw.LANGUAGE_FEEDBACK.format(
                    key=key, examples=examples)},
            ]
            try:
                fixed = sw._call_llm(messages)
            except RuntimeError as exc:
                print(f"    [!] retry fail: {str(exc)[:80]}")
                break
            if fixed.get(key) and len(sw._english_beats(fixed[key])) < len(drifted):
                data[key] = fixed[key]
            else:
                break

    for key in ("long_beats", "shorts_beats"):
        cleaned = []
        for beat in data.get(key) or []:
            text = sw._sanitise(str(beat.get("text", "")))
            if len(text) < 15:
                continue
            cleaned.append({
                "text": text,
                "keywords": str(beat.get("keywords", "colourful scene")).strip()
                            or "colourful scene",
            })
        if not cleaned:
            raise RuntimeError(f"{kind}: {key} khaali aaya. Dobara chalao.")
        data[key] = cleaned

    # No invented-number check here: there is no source text to check against,
    # and a made-up story is allowed to contain made-up numbers.
    data["title"] = sw._sanitise(str(data.get("title", spec["hindi"])))[:95]
    data["thumbnail_text"] = str(data.get("thumbnail_text", spec["hindi"]))[:40]
    data["tags"] = [str(t).lower().strip()[:30] for t in (data.get("tags") or [])][:15]
    data["sources"] = []
    data["category"] = spec["category"]
    data["kind"] = kind

    words = sum(len(b["text"].split()) for b in data["long_beats"])
    print(f"    {data['title']}")
    print(f"    {len(data['long_beats'])} beats, ~{words} words "
          f"(~{words / 145:.1f} min)")
    return data


def story_as_text(script: dict) -> str:
    return sw.script_as_text(script)
