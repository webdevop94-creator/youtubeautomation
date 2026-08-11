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

import history
import config
import script_writer as sw

# Who is on screen. The names are fixed rather than invented per video so a
# viewer who watches twice meets the same two characters, and -- the part that
# is not cosmetic -- so the writer knows their gender. Hindi conjugates verbs
# by the speaker's gender, and a female voice reading "मैं गया" instead of
# "मैं गई" is wrong in a way no amount of animation covers up.
CAST_A = {"name": "आर्यन", "gender": "male", "roman": "Aryan"}
CAST_B = {"name": "रिया", "gender": "female", "roman": "Riya"}

# One entry per content type: what to write, and how the scenes should look.
# `brief` writes one narrator reading; `dialogue` writes the two of them
# talking. Both are kept because news-style explainers still want a narrator.
KINDS = {
    "jokes": {
        "hindi": "चुटकुले",
        "category": "entertainment",
        "brief": """Write {n} short Hindi jokes (चुटकुले) that are genuinely funny to an
Indian audience -- the everyday kind people actually retell: teacher-student,
husband-wife, Pappu, doctor, boss-employee, shopkeeper, exam, mobile phone.
Each joke is ONE beat: setup then punchline, about {w} words including a short lead-in. Land the punchline on the last sentence. No joke may target religion,
caste, region, disability, gender or anyone's appearance.""",
        "dialogue": """आर्यन and रिया are two friends messing about. Write about {j} short
Hindi jokes (चुटकुले) delivered as their back-and-forth -- the everyday kind
Indians actually retell: teacher-student, Pappu, doctor, boss-employee,
shopkeeper, exam, mobile phone.

Each joke runs over 3 to 5 lines: one of them sets it up, the other reacts or
asks, the first lands the punchline, and the other LAUGHS with action "laugh".
Then move straight to the next joke -- do not announce it.

They are friends, so let them interrupt, tease and argue -- and write at least
one exchange where they are genuinely squabbling with each other (one accuses,
the other denies) and one where somebody is too excited to stand still and
says so. Those lines carry actions "fight" and "jump" or "run" because of what
they say, not the other way round.

No joke may target religion, caste, region, disability, gender or anyone's
appearance.""",
        "scene_hint": "an everyday Indian setting matching the joke -- classroom, "
                      "clinic, small shop, office desk, kitchen, street",
    },
    "facts": {
        "hindi": "रोचक तथ्य",
        # "world", not "science": this drives the stock fallbacks and the
        # generated-still style, and world facts want city streets, markets and
        # coastlines rather than the laboratory-and-telescope set that
        # "science" reaches for.
        "category": "world",
        # Filed under Education on YouTube, though. The "world" category maps
        # to News & Politics for the news pipeline, which is right for actual
        # news and wrong for an explainer -- browse and suggested treat the two
        # very differently, and that is where a new channel gets its views.
        "yt_category": "education",
        "brief": """Write {n} surprising, TRUE facts about the WORLD -- countries, cities,
places, landscapes, cultures and customs, languages, food, wildlife, oceans,
and the odd corners of history that go with them. Each fact is ONE beat of
about {w} words: state it, then explain why it is surprising.

Every fact must be about a DIFFERENT country or region. Do not spend two beats
in the same place, and do not build the whole video out of one continent.

Reach past the famous ones. "Venus has a long day", "honey never spoils" and
"an octopus has three hearts" are what every list already opens with; a viewer
who has seen one of these videos has seen those. Prefer a fact about a real,
namable place that most people could not have guessed.

Only well-established facts that a curious adult could verify -- no rumours,
and no "scientists say" without saying who. If you are unsure a fact is true,
choose a different one.""",
        "dialogue": """आर्यन and रिया are two friends. Write about {j} surprising, TRUE facts
about space, oceans, animals, the human body, history or technology, delivered
as their conversation.

For each fact: one of them brings it up, the other refuses to believe it
(action "surprise") or asks how (action "ask"), and the first explains why it
is true. Let them get excited -- somebody should jump or run at least once,
and at least one fact should end in laughter.

Only well-established facts a curious adult could verify. No rumours, and no
"scientists say" without saying who. If you are unsure a fact is true, choose
a different one.""",
        "scene_hint": "the real place the fact is about, named -- a named desert, "
                      "coastline, mountain range, city street, market, ruin or "
                      "animal in its habitat. Stock footage has to be findable "
                      "from these words, so name the thing rather than the idea",
    },
    "riddles": {
        "hindi": "पहेलियाँ",
        "category": "entertainment",
        "brief": """Write {n} Hindi riddles (पहेलियाँ). Each riddle is ONE beat of about {w} words: pose the riddle, tell the viewer to think, then give the answer at the
end of the same beat. Everyday objects and animals -- things a child would
know. Keep them solvable, not obscure.""",
        "dialogue": """आर्यन and रिया are two friends playing a riddle game. Write about {j}
Hindi riddles (पहेलियाँ) as their back-and-forth.

For each riddle: one poses it, the other thinks aloud (action "think") and
guesses wrong, and then the answer lands -- with the wrong guess being funny
enough that somebody laughs. Have them keep score and squabble about it once
(action "fight"). Everyday objects and animals a child would know; solvable,
not obscure.""",
        "scene_hint": "the object or animal that is the answer, shown plainly",
    },
    "stories": {
        "hindi": "कहानियाँ",
        "category": "entertainment",
        "brief": """Write ONE short Hindi moral story (कहानी) told across {n} beats, in the
Panchatantra spirit -- animals or village folk, a simple problem, a clear moral
in the last beat. About {w} words per beat. Original: do not retell a known
story word for word.""",
        "dialogue": """आर्यन is telling रिया one short Hindi moral story (कहानी) in the
Panchatantra spirit -- animals or village folk, a simple problem, a clear
moral at the end. Original: do not retell a known story word for word.

Build the story so that it CONTAINS both of these, because they are what the
video shows:
  a CHASE -- somebody runs, and somebody runs after them. Give those lines
  action "run", and write them so the running is what the line is about.
  a CONFRONTATION -- two of the characters in the story argue or scuffle face
  to face. Give those lines action "fight". Playful or comic, never cruel.
Do not announce them. A fox raiding a field and the farmer tearing after her
is a chase; the fox and the crow snapping at each other over the stolen corn
is a confrontation. The story should want both anyway.

रिया is the audience and must behave like one: she interrupts with questions
(action "ask"), gasps at the turn (action "surprise"), laughs at the funny
part, and says the moral back in her own words at the end.

In long_beats the story must REACH ITS ENDING and state its moral. Do not stop
partway and send the viewer off to watch the full video -- long_beats IS the
full video, and a story that breaks off before its own ending is the worst
thing you can hand back. (shorts_beats is the trailer and may point at it.)""",
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

# Written separately from USER rather than bolted onto it with conditionals.
# The two ask for different things at every level -- beat length, who speaks,
# what a beat even is -- and the one prompt that tried to cover both produced
# narration with speaker labels stapled on.
DIALOGUE_SYSTEM = SYSTEM + """

THIS IS A TWO-CHARACTER SCENE, NOT NARRATION.
- speaker 0 is आर्यन, a BOY. Every line he says must use MASCULINE Hindi verb
  forms: मैं गया, मैंने सोचा था, मैं थक गया.
- speaker 1 is रिया, a GIRL. Every line she says must use FEMININE Hindi verb
  forms: मैं गई, मैंने सोचा था, मैं थक गई.
  Getting this wrong is the worst mistake you can make here: a girl's voice
  will read the line aloud, and masculine endings will be obvious to everyone.
- They talk TO EACH OTHER, not to the camera. No "दोस्तों", no "आइए जानते हैं",
  no narrator voice. If a line would work read by a newsreader, rewrite it.
- One beat is ONE thing ONE character says: {line_lo} to {line_hi} words.
  Short. People do not speak in paragraphs.
- Alternate speakers most of the time. Two lines in a row from the same
  character is fine occasionally; four is a monologue.

KEYWORDS name WHAT IS BEING TALKED ABOUT, never who is talking or how they
feel. The two characters are heard, not seen -- the screen shows the subject.

This matters most on the reaction lines. When रिया gasps at the octopus, the
keywords are still the octopus: "giant octopus swimming reef". Write "surprised
girl gasping" and the footage becomes a stranger in a stock library pulling a
face, which has nothing to do with the sentence being spoken over it.

Keep the subject on screen across a whole exchange. Three lines about honey get
three different shots OF HONEY -- a jar, a spoon lifting, a hive -- not one of
honey and two of people discussing it.

ACTION -- what the character is DOING while saying the line. Choose exactly one
of: {actions}.

The animation plays whatever you name here, so the line has to earn it. Write
the line first, then name what it shows. A character who says "so what
happened at the shop?" tagged "run" is animated sprinting on the spot while
asking a calm question, and that looks worse than no action at all.

The test is simple: if someone read the line alone, with no label, would they
say the character is doing that? If not, the action is "talk".
- "laugh": they are laughing out loud. Goes on the line AFTER a punchline,
  never on the punchline itself.
- "fight": they are squabbling with each other right now -- accusing, denying,
  snatching something back. Playful between friends, never real violence. A
  change of subject is not a fight.
- "run": they are moving somewhere in this line -- chasing, fleeing, dragging
  the other one along.
- "jump": they cannot keep still from excitement, and the line says so.
- "ask": a question. "think": working something out aloud. "surprise":
  refusing to believe what they just heard. "talk": everything else, and most
  lines are everything else."""

DIALOGUE_USER = """{brief}

For each line also give an English scene description for the background:
{scene_hint}.

Return JSON with exactly this shape:
{{
  "title": "YouTube title in Devanagari, under 65 characters, makes someone click",
  "thumbnail_text": "3 to 5 words in Devanagari, big and punchy",
  "long_beats": [
    {{"speaker": 0, "action": "talk",
      "text": "one line of dialogue in Devanagari",
      "keywords": "2-5 ENGLISH words naming a drawable scene"}}
  ],
  "shorts_beats": [
    {{"speaker": 0, "action": "talk", "text": "...", "keywords": "english scene words"}}
  ],
  "description": "YouTube description in Devanagari. Two hook lines, then 3 bullets with '-'.",
  "tags": ["12 to 15 lowercase tags, mix Hindi-Roman and English"]
}}

long_beats: exactly {n} lines, {line_lo} to {line_hi} words each, {max_words}
  words in total at the very most -- the video has a fixed runtime. The first
  line drops us mid-conversation so nobody can scroll past it. The last line is
  one of them asking for a like and subscribe, in character.
shorts_beats: 8 to 10 lines, 100 to 130 words total. The first line hooks in
  under 3 seconds; the last sends them to the full video.
"""


def _dialogue_messages(spec: dict, n_lines: int) -> list:
    words = config.WORDS_PER_LINE
    lo, hi = max(4, int(words * 0.6)), int(words * 1.6)
    # Roughly four lines to land a joke or a fact: set up, react, pay off,
    # laugh. Asking for more items than the line budget can carry is what makes
    # a model rush the punchline.
    items = max(1, n_lines // 4)
    return [
        {"role": "system", "content": DIALOGUE_SYSTEM.format(
            actions=", ".join(f'"{a}"' for a in config.ACTIONS),
            line_lo=lo, line_hi=hi)},
        {"role": "user", "content": DIALOGUE_USER.format(
            brief=spec["dialogue"].format(j=items, n=n_lines, w=words),
            scene_hint=spec["scene_hint"], n=n_lines,
            line_lo=lo, line_hi=hi, max_words=int(n_lines * words * 1.3))},
    ]


def _clean_dialogue(beats: list) -> list:
    """Force speaker and action into the vocabulary the renderer can play.

    A model that is asked for eight action names will occasionally invent a
    ninth, and an unknown action reaches the 3D scene as a missing animation
    file. Coercing here means every later stage can trust the field.
    """
    out = []
    for i, beat in enumerate(beats):
        try:
            speaker = int(beat.get("speaker", i % 2))
        except (TypeError, ValueError):
            speaker = i % 2
        action = str(beat.get("action", "")).strip().lower()
        out.append({**beat, "speaker": 0 if speaker == 0 else 1,
                    "action": action if action in config.ACTIONS
                              else config.DEFAULT_ACTION})

    # A "conversation" in which one character never speaks is the failure this
    # guards: it renders as the old alternating narration, silently.
    if out and len({b["speaker"] for b in out}) < 2:
        for i, beat in enumerate(out):
            beat["speaker"] = i % 2
        print("    [!] sirf ek speaker aaya tha — baari-baari kar diya")
    return out


def _already_covered(limit: int = 45) -> list:
    """Titles of what this channel has recently published.

    Both sources, because neither is complete on its own: history.json only
    grows when agent.py runs, so anything built by hand is invisible to it,
    and the output folders only survive until housekeeping ages them out.

    Without this the writer kept returning to the same handful of famous
    facts -- Venus's long day, honey that never spoils, the octopus's three
    hearts -- because those are what "surprising fact" most strongly means.
    Two videos in a row opened with Venus.
    """
    seen, titles = set(), []
    try:
        # Titles AND beat subjects, both out of history.json. The subjects are
        # the half that matters -- "3 surprising facts" forbids nothing, while
        # "planet venus spinning space cosmos" forbids exactly the fact that
        # kept coming back -- and history.json is the only copy of them that
        # survives a fresh cloud checkout.
        for text in history.covered_topics():
            if text not in seen:
                seen.add(text)
                titles.append(text)
    except Exception:
        pass
    try:
        folders = sorted(config.OUTPUT_DIR.glob("*/script.json"),
                         key=lambda p: p.stat().st_mtime, reverse=True)
        for path in folders[:limit]:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            t = data.get("title", "").strip()
            if t and t not in seen:
                seen.add(t)
                titles.append(t)
            # The titles alone are not enough. "3 surprising facts" names
            # nothing, so the writer cheerfully opened on Venus's long day for
            # a third time. Each beat's keywords DO name its subject, in
            # English, which is exactly the list to hand back as off-limits.
            for beat in data.get("long_beats", []):
                k = str(beat.get("keywords", "")).strip()
                if k and k not in seen:
                    seen.add(k)
                    titles.append(k)
    except Exception:
        pass
    return titles[:limit]


AVOID = """
ALREADY PUBLISHED ON THIS CHANNEL -- do not cover any of these subjects again,
and do not open with the same fact as any of them:
{titles}

Pick subjects that are NOT on that list. If the obvious answer is on it, that
is a reason to go further, not a reason to repeat it.
"""


def write_story(kind: str = "jokes", n_beats: int = None) -> dict:
    """Generate an original script. Same shape as script_writer.write_script."""
    if kind not in KINDS:
        raise RuntimeError(f"Unknown kind '{kind}'. Options: {', '.join(KINDS)}")
    spec = KINDS[kind]
    dialogue = config.DIALOGUE and "dialogue" in spec
    n_beats = n_beats or (config.MAX_DIALOGUE_LINES if dialogue
                          else config.MAX_LONG_BEATS)

    chain = " -> ".join(p["name"] for p in sw._providers()) or "koi provider nahi"
    shape = "do character ki baat-cheet" if dialogue else "narration"
    print(f"[2/6] {spec['hindi']} likh raha hoon ({shape}, {chain})...")

    beat_words = config.WORDS_PER_BEAT
    if dialogue:
        messages = _dialogue_messages(spec, n_beats)
    else:
        messages = [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": USER.format(
                brief=spec["brief"].format(n=n_beats, w=beat_words),
                scene_hint=spec["scene_hint"], n=n_beats,
                beat_lo=int(beat_words * 0.8), beat_hi=int(beat_words * 1.2),
                max_words=int(n_beats * beat_words * 1.2))},
        ]

    # What has already gone out, appended to whichever brief was built. Left
    # to itself the writer returns to the same few famous facts every time --
    # two videos running opened on Venus's long day.
    covered = _already_covered()
    if covered:
        messages[-1]["content"] += AVOID.format(
            titles="\n".join(f"- {t}" for t in covered))
        print(f"    {len(covered)} purane topics se bacha raha hoon")
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
            # A spoken line is allowed to be much shorter than a narrated beat.
            # The old 15-character floor silently deleted "अच्छा? सच में?",
            # which is exactly the kind of line that makes a scene a
            # conversation rather than two speeches.
            if len(text) < (4 if dialogue else 15):
                continue
            line = {
                "text": text,
                "keywords": str(beat.get("keywords", "colourful scene")).strip()
                            or "colourful scene",
            }
            if dialogue:
                line["speaker"] = beat.get("speaker")
                line["action"] = beat.get("action")
            cleaned.append(line)
        if not cleaned:
            raise RuntimeError(f"{kind}: {key} khaali aaya. Dobara chalao.")
        data[key] = _clean_dialogue(cleaned) if dialogue else cleaned

    # No invented-number check here: there is no source text to check against,
    # and a made-up story is allowed to contain made-up numbers.
    data["title"] = sw._sanitise(str(data.get("title", spec["hindi"])))[:95]
    data["thumbnail_text"] = str(data.get("thumbnail_text", spec["hindi"]))[:40]
    data["tags"] = [str(t).lower().strip()[:30] for t in (data.get("tags") or [])][:15]
    data["sources"] = []
    data["category"] = spec["category"]
    data["yt_category"] = spec.get("yt_category", spec["category"])
    data["kind"] = kind

    words = sum(len(b["text"].split()) for b in data["long_beats"])
    print(f"    {data['title']}")
    print(f"    {len(data['long_beats'])} beats, ~{words} words "
          f"(~{words / 145:.1f} min)")
    if dialogue:
        used = {}
        for beat in data["long_beats"]:
            used[beat["action"]] = used.get(beat["action"], 0) + 1
        print("    actions: " + ", ".join(f"{a}x{n}" for a, n in
                                          sorted(used.items(), key=lambda kv: -kv[1])))
    return data


def story_as_text(script: dict) -> str:
    return sw.script_as_text(script)
