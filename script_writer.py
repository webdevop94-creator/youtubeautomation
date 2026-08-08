"""Turn researched facts into a Hinglish narration script + YouTube metadata."""
import json
import re
import time

import requests

import config
import research

GEMINI_API = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
GROQ_API = "https://api.groq.com/openai/v1/chat/completions"
NVIDIA_API = "https://integrate.api.nvidia.com/v1/chat/completions"

SYSTEM = """You write scripts for a Hinglish YouTube channel aimed at an Indian audience.
The channel covers whatever is going viral worldwide, so the subject changes daily.
Assume the viewer has not heard of the people, teams, companies or places involved:
introduce them in one short clause before using them.

LANGUAGE RULES (critical — the text goes straight into a Hindi text-to-speech engine):
- Hinglish: Hindi sentence structure, English technical words kept in English
  (model, training, parameter, open source, startup, funding — do NOT translate these).
- Write everything in Roman script, NOT Devanagari.
- Short sentences. Max 15 words each. TTS sounds robotic on long sentences.
- Spell numbers out in words: "do hazaar dollar" not "$2000", "aath sau billion" not "800B".
- NO emoji, NO markdown, NO brackets, NO special characters. Only letters, commas, periods.
- Conversational, like explaining to a friend. Use "aap", "dekho", "matlab", "yaani".

CONTENT RULES:
- Use ONLY the facts given to you. Never invent numbers, names, dates or quotes.
- If a detail is not in the source material, leave it out entirely.
- NUMBERS: only state a figure if that exact figure appears in the source text AND
  the source attaches it to the same thing you are attaching it to. A number that
  appears next to a different subject is NOT usable. When unsure, omit the number
  and describe it qualitatively instead. A wrong figure destroys channel credibility.
- Hook must land in the first 5 seconds and create curiosity without clickbait lying.

NO REPETITION — this is the most common failure:
- Every beat must add information no earlier beat contained. If you have nothing
  new to say, write FEWER beats. A tight 4-minute video beats a padded 6-minute one.
- Never reuse a sentence pattern. Phrases like "madad karega", "koi kasar nahi chodi",
  "dekho kya hai isme special", "growth ko badhane me" must not appear more than once
  across the whole script.
- Do not restate the headline in multiple beats with different wording.

KEYWORDS — these are fed to a stock footage search, which is literal-minded:
- Name a scene a camera could actually film. Never an abstract concept.
- Words like cloud, growth, race, security, adoption, future, ecosystem return
  nonsense: "cloud" returns sky, "india" returns village scenery.
  BAD "cloud services"     GOOD "server racks datacenter"
  BAD "AI growth india"    GOOD "mumbai office skyline"
  BAD "competition race"   GOOD "business people meeting"
  BAD "data security"      GOOD "network cables switch"
- A named person, team, film or product will NOT be in a stock library. Describe
  the setting instead.
  BAD "elon musk"          GOOD "man speaking on stage"
  BAD "real madrid"        GOOD "football stadium crowd night"
  BAD "iphone 18"          GOOD "hands holding smartphone closeup"

Return ONLY valid JSON. No prose before or after."""

# The channel's subject changes every day, so tone and stock-footage vocabulary
# have to change with it. A sports result narrated in explainer-tech cadence
# lands flat, and searching "server room" over a film trailer story returns
# footage with nothing to do with the script.
CATEGORY_ANGLES = {
    "tech": """ANGLE: what actually changed, and whether it is worth the viewer's money
        or attention. Compare to what they already own or use.
        VISUAL VOCABULARY: hands holding smartphone, laptop keyboard closeup, circuit
        board macro, server racks datacenter, electronics factory assembly line,
        person using computer at desk.""",
    "sports": """ANGLE: the human story and what it changes going forward -- a signing, a
        record, a comeback. Explain the sport's context briefly; many viewers do not
        follow this league. Never re-narrate a scoreline nobody asked for.
        VISUAL VOCABULARY: stadium crowd cheering, football pitch aerial, cricket bat
        closeup, athlete training gym, empty locker room, trophy closeup.""",
    "entertainment": """ANGLE: why people are talking about it, and what to expect next.
        Keep it light and gossipy without stating anything the sources do not.
        VISUAL VOCABULARY: cinema hall seats, film camera on set, red carpet lights,
        concert crowd hands, recording studio microphone, popcorn closeup.""",
    "business": """ANGLE: what it means for ordinary people -- prices, jobs, savings.
        Translate large figures into something a viewer can picture.
        VISUAL VOCABULARY: stock chart on screen, busy trading floor, shipping port
        containers, factory workers, shopping mall crowd, indian currency notes.""",
    "science": """ANGLE: the discovery in plain language, then why it matters. Curiosity
        first, no jargon. Say clearly when something is early research.
        VISUAL VOCABULARY: laboratory scientist microscope, telescope night sky,
        rocket launch, dna animation, glacier ice melting, petri dish closeup.""",
    "health": """ANGLE: practical and calm. Describe what is known, name the source, and
        never give personal medical advice or dosages.
        VISUAL VOCABULARY: hospital corridor, doctor with stethoscope, fresh vegetables
        market, person jogging park, pharmacy shelves, medical lab samples.""",
    "world": """ANGLE: explain the background a viewer is missing, plainly and neutrally.
        Report only what the sources report. Take no side.
        VISUAL VOCABULARY: city skyline aerial, crowded street market, airport terminal,
        cargo ship ocean, government building exterior, world map closeup.""",
    "general": """ANGLE: why this is everywhere right now, and the part people are missing.
        VISUAL VOCABULARY: crowded street people walking, person scrolling phone,
        city skyline sunset, office workers meeting, hands typing laptop.""",
}

USER_TEMPLATE = """Write a video script from this research.

This story is a {category} story. {angle}

{facts}

Return JSON with exactly this shape:
{{
  "title": "YouTube title, Hinglish, under 65 characters, curiosity + main keyword",
  "thumbnail_text": "3 to 5 words, ALL CAPS, biggest possible impact",
  "long_beats": [
    {{"text": "narration for this beat, 2 to 4 sentences",
      "keywords": "2-3 English words naming a CONCRETE FILMABLE SCENE"}}
  ],
  "shorts_beats": [
    {{"text": "narration", "keywords": "stock footage search words"}}
  ],
  "description": "YouTube description. First 2 lines are the hook. Then 3 bullet points with '-'. Hinglish.",
  "tags": ["12 to 15 lowercase search tags, mix Hindi-Roman and English"],
  "your_take": "One sentence prompting the channel owner to add their own opinion here"
}}

long_beats: AT MOST {n_long} beats, each 55 to 80 words.
  The long_beats narration must total AT LEAST {min_words} words — that is the
  single most important length rule. A beat of 25 words is far too short. Each beat
  is a short paragraph of 4 to 6 sentences, not one line.
  Beat 1 = hook. Beat 2 = context. Middle beats = the actual news, one NEW point each.
  Second-last beat = why it matters for the viewer. Last beat = call to action.
  Reach the word count with real detail from the sources above — names, figures,
  what led to it, what happens next. Never with repetition or filler. If you truly
  run out of material, write fewer beats but keep each one full length.
shorts_beats: 5 beats, total 110 to 130 words (about 45 seconds).
  Beat 1 = hook in under 3 seconds. Last beat = cliffhanger that sends them to the long video.
"""

REPETITION_FEEDBACK = """Your previous attempt repeated itself badly. These beats said
the same thing as an earlier beat:

{examples}

Rewrite the script with FEWER beats. Every beat must carry information no other beat
has. Do not pad to reach a length. Vary sentence structure completely."""

LENGTH_FEEDBACK = """Your long_beats are far too short: {words} words total across
{count} beats, averaging {average} words per beat. The target is at least {min_words}
words, with each beat 55 to 80 words.

Rewrite ONLY the long_beats, keeping the same facts and order, and expand each beat
into a full paragraph of 4 to 6 sentences. Pull the extra substance from the source
material you were given: specific names, numbers, dates, what led up to this, what
happens next, and concrete detail already present in the articles.

Do NOT repeat yourself and do NOT restate other beats.

Above all: do NOT introduce a single number, name, date or quote that is not already
in the source material. Adding length is not a licence to invent detail. If you need
more words, describe what the sources describe more fully -- never fill the gap with a
figure you are guessing at. Any invented figure is caught and the whole line is deleted.

Keep shorts_beats, title, description and tags exactly as they were."""

LANGUAGE_FEEDBACK = """These {key} drifted into plain English. This channel is Hinglish
and the narration is read by a HINDI text-to-speech voice, so English sentences sound
wrong and the video is unusable:

{examples}

Return JSON containing ONLY the key "{key}".

Rewrite EVERY beat in Hinglish: Hindi sentence structure written in Roman script, with
English kept only for technical or proper nouns. Every sentence needs Hindi connective
words -- hai, hain, ka, ki, ke, ko, ne, se, mein, aur, ye, wo, kya, lekin, isliye.

  WRONG  "She defeated the defending champion in straight sets."
  RIGHT  "Usne defending champion ko straight sets mein hara diya."

  WRONG  "The stadium was sold out and fans cheered loudly."
  RIGHT  "Stadium poora bhara hua tha, aur fans zor se cheer kar rahe the."

Keep the same facts, the same order and the same number of beats. Change only the
language. Do not add any fact that is not already there."""


def _extract_json(raw) -> dict:
    if not raw or not str(raw).strip():
        raise RuntimeError("Model ne khaali content bheja")
    raw = str(raw)
    # DeepSeek and other reasoning models emit their chain of thought first.
    # It is prose, and it frequently contains braces, so it has to go before
    # any brace matching happens.
    raw = re.sub(r"(?is)<(think|thinking|reasoning)>.*?</\1>", " ", raw)
    raw = re.sub(r"(?is)^.*?</(?:think|thinking|reasoning)>", " ", raw)
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.MULTILINE).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    # Model sometimes wraps JSON in stray text — grab the outermost object.
    start, depth = raw.find("{"), 0
    if start == -1:
        raise ValueError("Model ne JSON return nahi kiya")
    for i in range(start, len(raw)):
        depth += (raw[i] == "{") - (raw[i] == "}")
        if depth == 0:
            return json.loads(raw[start:i + 1])
    raise ValueError("JSON adhura hai")


# Curly punctuation is not in the allow-list below, so it used to be deleted
# outright -- turning "Toronto's stadium" into "Toronto s stadium". Models emit
# curly quotes constantly, so they are folded to ASCII before anything is cut.
SMART_PUNCTUATION = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "′": "'", "‵": "'",
    "–": "-", "—": "-", "―": "-", "−": "-",
    "…": "...", " ": " ", "​": "", "⁄": "/",
}

# Symbols the TTS cannot pronounce but which carry meaning. Deleting them
# silently changed "80% of requests" into "80 of requests".
# The number is captured whole: a single-digit group turned "EUR 70" into
# "7 euro0", which the voice would read as seven.
_AMOUNT = r"(\d[\d,.]*)"
SPOKEN_SYMBOLS = [
    (_AMOUNT + r"\s*%", r"\1 percent"),
    (r"%", " percent "),
    (r"€\s*" + _AMOUNT, r"\1 euro"), (_AMOUNT + r"\s*€", r"\1 euro"),
    (r"£\s*" + _AMOUNT, r"\1 pound"), (_AMOUNT + r"\s*£", r"\1 pound"),
    (r"₹\s*" + _AMOUNT, r"\1 rupees"), (_AMOUNT + r"\s*₹", r"\1 rupees"),
    (r"\$\s*" + _AMOUNT, r"\1 dollar"), (_AMOUNT + r"\s*\$", r"\1 dollar"),
    (r"&", " and "),
    (_AMOUNT + r"\s*\+", r"\1 plus"),
]


def _sanitise(text: str) -> str:
    """Strip anything the TTS engine would read out loud as garbage."""
    for smart, plain in SMART_PUNCTUATION.items():
        text = text.replace(smart, plain)
    for pattern, replacement in SPOKEN_SYMBOLS:
        text = re.sub(pattern, replacement, text)
    text = re.sub(r"[*_#`~\[\]<>|]", " ", text)
    text = re.sub(r"[^\w\s.,?!:;'\"()-]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+([.,?!:;])", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    if text and text[-1] not in ".?!":
        text += "."
    return text


STOP_WORDS = set("""ka ki ke ko me mein hai hain ye yeh wo woh aur ya bhi to toh se
ne par is us ek hi kya kaise jo cha raha rahe rahi ho hua kar liye ab ki""".split())

# --- Language drift detection ---------------------------------------------
# The prompt asks for Hinglish and the model agrees for a few beats, then
# quietly slides into pure English. A live run produced beats 4 to 9 entirely
# in English -- unusable, because the voice is a Hindi TTS reading Roman text.
# Deliberately excludes words that are also common English: "the", "is", "us",
# "to", "me", "hi", "no". Counting those scored a fully English sentence at
# 0.14 -- above the threshold -- purely on its articles and prepositions.
HINGLISH_MARKERS = set("""ka ki ke ko ne se mein hai hain tha thi hoga hogi
ye yeh wo woh aur ya bhi toh kya kyun kaise jab tab ab abhi phir
liye lekin magar sirf bahut zyada accha achha bura naya nayi purana sab sabhi
har kuch kuchh nahi nahin haan aap aapko aapka hum humein hamara unka uska
unki uske iske inka dekho dekhiye suno samjho matlab yaani chaliye karo kar
karke karna karti karta karte hota hoti hote gaya gayi gaye raha rahi rahe
diya diye liya liye lene wala wali wale rakha rakhi mila mili milta
crore lakh hazaar baar saal mahine dono teeno itna itni kitna kitni
apna apni apne uska unko usne isne isse usse yahan wahan kahan""".split())

# Below this share of Hinglish marker words, a beat has drifted into English.
MIN_HINGLISH_SHARE = 0.10


def _hinglish_share(text: str) -> float:
    words = re.findall(r"[a-zA-Z']+", text.lower())
    if len(words) < 8:
        return 1.0  # too short to judge; the length guard handles these
    return sum(1 for w in words if w.strip("'") in HINGLISH_MARKERS) / len(words)


def _english_beats(beats: list) -> list:
    """Indexes of beats that are effectively English, not Hinglish."""
    return [i for i, beat in enumerate(beats)
            if _hinglish_share(beat.get("text", "")) < MIN_HINGLISH_SHARE]


def _shingles(text: str) -> set:
    words = [w for w in re.findall(r"[a-z]+", text.lower()) if w not in STOP_WORDS]
    return {" ".join(words[i:i + 3]) for i in range(max(0, len(words) - 2))}


def _find_repeats(beats: list, threshold: float = 0.42) -> list:
    """Flag beats that mostly restate an earlier beat."""
    repeats, seen = [], []
    for i, beat in enumerate(beats):
        current = _shingles(beat["text"])
        if not current:
            continue
        for j, earlier in seen:
            overlap = len(current & earlier) / max(1, min(len(current), len(earlier)))
            if overlap >= threshold:
                repeats.append((i, j, round(overlap, 2)))
                break
        seen.append((i, current))
    return repeats


def _providers() -> list:
    """Script writers to try, in order. Only those with a key configured.

    Groq first: fast, and generous per minute. NVIDIA NIM takes over when
    Groq's daily budget is gone -- on a 100,000 token/day allowance that
    happens after roughly five videos, which would otherwise cost a whole day.
    """
    chain = []
    if config.GEMINI_API_KEY:
        # Gemini's OpenAI-compatible endpoint takes a Bearer header. Its native
        # endpoint wants ?key= instead, so do not swap one for the other.
        # Generous budget: Gemini's flash models think before answering, and
        # that thinking is billed against max_tokens. At 8000 a full 12-beat
        # script came back with the JSON cut off mid-object.
        chain.append({"name": "gemini", "url": GEMINI_API, "key": config.GEMINI_API_KEY,
                      "model": config.GEMINI_MODEL, "json_mode": True,
                      "max_tokens": 16000})
    if config.GROQ_API_KEY:
        chain.append({"name": "groq", "url": GROQ_API, "key": config.GROQ_API_KEY,
                      "model": config.GROQ_MODEL, "json_mode": True})
    if config.NVIDIA_API_KEY:
        reasoning = bool(re.search(r"gpt-oss|deepseek-r|reason|nemotron|qwq|think",
                                   config.NVIDIA_MODEL, re.I))
        # NIM does not accept response_format on every model, and
        # _extract_json already copes with prose around the object.
        chain.append({"name": "nvidia", "url": NVIDIA_API, "key": config.NVIDIA_API_KEY,
                      "model": config.NVIDIA_MODEL, "json_mode": False,
                      "low_reasoning": reasoning,
                      # Room for the answer after the thinking is done.
                      "max_tokens": 8000 if reasoning else 4000})
    return chain


def _retry_after(resp) -> float:
    """Seconds to wait before retrying a rate-limited call.

    A free tier's per-minute token budget is smaller than two script calls, so
    a revision pass reliably trips it. Groq states the exact wait in the error
    body ("Please try again in 35.965s"), which beats guessing.
    """
    match = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", resp.text)
    if match:
        minutes = float(match.group(1) or 0)
        return min(minutes * 60 + float(match.group(2)) + 2, 90)
    header = resp.headers.get("retry-after", "")
    if header.replace(".", "", 1).isdigit():
        return min(float(header) + 2, 90)
    return 25.0


def _is_daily_limit(resp) -> bool:
    """A daily budget does not free up by waiting -- switch provider instead."""
    return bool(re.search(r"tokens? per day|\bTPD\b|requests? per day|\bRPD\b"
                          r"|quota exceeded", resp.text, re.I))


# --- Invented-figure detection --------------------------------------------
# Asking the model for more words is exactly when it starts inventing numbers.
# A live test expanded a match report and produced "38,000 fans" from sources
# that said "150 invited fans". The prompt already forbids this; prompts are
# not a control, so every figure is checked against the source text.

NUM_WORDS = {
    "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5,
    "chhe": 6, "che": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10, "bees": 20,
    "pachees": 25, "tees": 30, "chalees": 40, "pachaas": 50, "sattar": 70,
    "assi": 80, "nabbe": 90,
}
SCALES = {
    "sau": 100, "hazaar": 1000, "hazar": 1000, "lakh": 100_000, "lakhs": 100_000,
    "crore": 10_000_000, "crores": 10_000_000, "million": 1_000_000,
    "billion": 1_000_000_000, "trillion": 1_000_000_000_000,
}
# Tens and units that can follow a scale word, so "do hazaar chhabbis" reads as
# 2026 rather than 2000. Getting this wrong deleted six correct lines in a live
# run, every one of them simply stating a year.
TENS_UNITS = {
    "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5,
    "chhe": 6, "che": 6, "saat": 7, "aath": 8, "nau": 9, "das": 10,
    "gyarah": 11, "barah": 12, "baarah": 12, "terah": 13, "chaudah": 14,
    "pandrah": 15, "solah": 16, "satrah": 17, "atharah": 18, "unnis": 19,
    "bees": 20, "ikkis": 21, "baais": 22, "bais": 22, "teis": 23, "chaubis": 24,
    "pachees": 25, "chhabbis": 26, "chhabis": 26, "sattais": 27, "atthais": 28,
    "untis": 29, "tees": 30, "chalees": 31, "saintis": 37, "chalis": 40,
    "pachaas": 50, "saath": 60, "sattar": 70, "assi": 80, "nabbe": 90,
}
_NUMS = "|".join(sorted(NUM_WORDS, key=len, reverse=True))
_SCALES = "|".join(sorted(SCALES, key=len, reverse=True))
_TENS = "|".join(sorted(TENS_UNITS, key=len, reverse=True))
# Two scale words can stack in Indian usage: "do hazaar crore" is 2,000 crore,
# not the year 2000. The second scale is tried before the tens-and-units tail
# so that "crore" is read as a multiplier rather than skipped.
_SCALE_RE = re.compile(
    rf"(\d[\d,.]*|{_NUMS})\s+({_SCALES})\b"
    rf"(?:\s+({_SCALES})\b)?"
    rf"(?:\s+({_TENS})\b)?", re.I)
_DIGIT_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")

# Figures below this are skipped: scorelines, dates and counts like "do teams"
# are unverifiable in isolation and produce constant false positives.
MIN_CHECKED = 100

# Years are dates, and dates are never checked -- the same rule that skips
# "7 August" has to skip "2026" and its spelled-out form "do hazaar chhabbis".
YEAR_RANGE = (1500, 2200)


def _as_number(raw: str):
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return NUM_WORDS.get(raw.lower())


def _numbers_in(text: str) -> set:
    """Every quantity the text states, digits or Hinglish words."""
    values = set()
    for amount, scale, scale2, tail in _SCALE_RE.findall(text):
        base = _as_number(amount)
        if base is None:
            continue
        total = base * SCALES[scale.lower()]
        if scale2:
            total *= SCALES[scale2.lower()]
        if tail:
            total += TENS_UNITS[tail.lower()]
        values.add(total)
    for token in _DIGIT_RE.findall(text):
        value = _as_number(token)
        if value is not None:
            values.add(value)
    return values


def _checkable(value: float) -> bool:
    """Figures worth verifying: not tiny, not a year."""
    return value >= MIN_CHECKED and not (
        YEAR_RANGE[0] <= value <= YEAR_RANGE[1] and float(value).is_integer())


def _source_numbers(facts: dict) -> set:
    body = " ".join(
        [facts.get("topic", "")] + facts.get("headlines", []) + facts.get("snippets", [])
        + [a["text"] for a in facts.get("articles", [])])
    return _numbers_in(body)


def _is_supported(value: float, sources: set) -> bool:
    # 0.5% tolerance so "1.2 billion" matches a source's "1,200,000,000".
    return any(abs(value - known) <= max(1.0, abs(value) * 0.005) for known in sources)


def _sentences(text: str) -> list:
    return [s for s in re.split(r"(?<=[.?!])\s+", text) if s.strip()]


def _strip_invented_numbers(beats: list, facts: dict, label: str) -> int:
    """Delete sentences stating figures no source supports. Returns the count."""
    sources = _source_numbers(facts)
    removed = 0
    for beat in beats:
        kept = []
        for sentence in _sentences(beat["text"]):
            bad = [v for v in _numbers_in(sentence)
                   if _checkable(v) and not _is_supported(v, sources)]
            if bad:
                shown = ", ".join(f"{v:,.0f}" for v in sorted(bad))
                print(f"    [!] {label}: source mein nahi mila ({shown}) — "
                      f"line hata di: \"{sentence.strip()[:70]}\"")
                removed += 1
                continue
            kept.append(sentence)
        if kept:
            beat["text"] = " ".join(kept)
    return removed


def _finish_reason(resp) -> str:
    try:
        return (resp.json().get("choices") or [{}])[0].get("finish_reason") or ""
    except ValueError:
        return ""


def _post(provider: dict, messages: list, max_tokens: int = None):
    body = {"model": provider["model"], "temperature": 0.7,
            "max_tokens": max_tokens or provider.get("max_tokens", 4000),
            "messages": messages}
    if provider["json_mode"]:
        body["response_format"] = {"type": "json_object"}
    if provider.get("low_reasoning"):
        # Reasoning models spend the token budget thinking and then have
        # nothing left for the answer -- gpt-oss-20b returned content=None on
        # a real 5,000-token prompt while every short test passed.
        body["chat_template_kwargs"] = {"reasoning_effort": "low"}
    return requests.post(
        provider["url"],
        headers={"Authorization": f"Bearer {provider['key']}",
                 "Content-Type": "application/json", "Accept": "application/json"},
        json=body, timeout=180)


def _content(resp) -> str:
    """The model's answer, wherever this provider decided to put it."""
    message = (resp.json().get("choices") or [{}])[0].get("message") or {}
    for field in ("content", "reasoning_content", "reasoning"):
        text = message.get(field)
        if text and str(text).strip():
            return str(text)
    finish = (resp.json().get("choices") or [{}])[0].get("finish_reason")
    raise RuntimeError(
        f"Model ne khaali jawab diya (finish_reason={finish}). "
        f"Reasoning model ho to max_tokens badhao ya reasoning_effort low karo.")


def _call_llm(messages: list, retries: int = 3) -> dict:
    """Ask each configured provider in turn until one answers."""
    chain = _providers()
    if not chain:
        raise SystemExit(
            "\n[X] Koi script writer key nahi mili.\n"
            "    GROQ_API_KEY (https://console.groq.com) ya\n"
            "    NVIDIA_API_KEY (https://build.nvidia.com) .env mein daalo.\n")

    problems = []
    for index, provider in enumerate(chain):
        last = index == len(chain) - 1
        budget = provider.get("max_tokens", 4000)
        for attempt in range(retries):
            resp = _post(provider, messages, max_tokens=budget)
            if resp.status_code == 200:
                try:
                    data = _extract_json(_content(resp))
                except (ValueError, RuntimeError) as exc:
                    # Truncated or empty output. Usually the token budget ran
                    # out mid-JSON -- thinking models spend a lot before they
                    # write anything -- so grow it and ask again.
                    truncated = _finish_reason(resp) == "length"
                    if truncated and attempt + 1 < retries:
                        budget = min(budget * 2, 32000)
                        print(f"    [!] {provider['name']} ka jawab kata hua tha, "
                              f"max_tokens {budget} karke dobara...")
                        continue
                    problems.append(f"{provider['name']}: {exc}")
                    if not last:
                        print(f"    [!] {provider['name']} ka JSON kharab — "
                              f"{chain[index + 1]['name']} try kar raha hoon")
                    break
                if index > 0:
                    print(f"    {provider['name']} ne likhi ({provider['model']})")
                return data

            if resp.status_code == 429:
                # Daily budget gone: waiting cannot help, hand over now.
                if _is_daily_limit(resp) and not last:
                    print(f"    [!] {provider['name']} ka daily quota khatam — "
                          f"{chain[index + 1]['name']} par ja raha hoon")
                    problems.append(f"{provider['name']}: daily quota")
                    break
                if attempt + 1 < retries:
                    wait = _retry_after(resp)
                    print(f"    [!] {provider['name']} rate limit, "
                          f"{wait:.0f}s ruk raha hoon...")
                    time.sleep(wait)
                    continue

            problems.append(
                f"{provider['name']} HTTP {resp.status_code}: {resp.text[:150]}")
            if not last:
                print(f"    [!] {provider['name']} fail ({resp.status_code}) — "
                      f"{chain[index + 1]['name']} try kar raha hoon")
            break

    # RuntimeError, not SystemExit: the unattended agent catches this and
    # moves on to the next topic instead of the whole run dying.
    raise RuntimeError("Koi provider script nahi likh paya. " + " | ".join(problems))


# Older name, kept so nothing else has to change.
_call_groq = _call_llm


def write_script(facts: dict, n_long_beats: int = 12, category: str = "general") -> dict:
    chain = " -> ".join(p["name"] for p in _providers()) or "koi provider nahi"
    print(f"[3/7] Script likh raha hoon ({chain})...")

    category = category if category in CATEGORY_ANGLES else "general"
    # fact_depth() already capped the beat count at what the sources support,
    # so asking for 45 words per allowed beat cannot push the model into filler.
    min_words = n_long_beats * 45
    user_prompt = USER_TEMPLATE.format(
        facts=research.facts_prompt_block(facts), n_long=n_long_beats,
        category=category, angle=CATEGORY_ANGLES[category], min_words=min_words)
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": user_prompt}]

    data = _call_groq(messages)

    repeats = _find_repeats(data.get("long_beats") or [])
    if repeats:
        beats = data["long_beats"]
        examples = "\n".join(
            f'- beat {i + 1} repeats beat {j + 1} ({score:.0%} overlap): "{beats[i]["text"][:90]}..."'
            for i, j, score in repeats[:5])
        print(f"    [!] {len(repeats)} beats repeat ho rahe the, dobara likhwa raha hoon")
        # Only the beats go back, not the whole JSON. The per-minute token
        # budget on Groq's free tier is smaller than two full script calls.
        messages += [
            {"role": "assistant",
             "content": json.dumps({"long_beats": data["long_beats"]}, ensure_ascii=False)},
            {"role": "user", "content": REPETITION_FEEDBACK.format(examples=examples)},
        ]
        retry = _call_groq(messages)
        if retry.get("long_beats"):
            still = _find_repeats(retry["long_beats"])
            if len(still) < len(repeats):
                data = {**data, **{k: v for k, v in retry.items() if v}}
            if still:
                print(f"    [!] Retry ke baad bhi {len(still)} repeat beats — "
                      f"script approve karte waqt dekh lena")

    # Length check. The model reliably under-writes: a first live run produced
    # six 25-word beats for a story with five full articles behind it, which is
    # a one-minute video sold as long-form. The prompt alone does not fix this,
    # so the shortfall is measured and sent back.
    beats = data.get("long_beats") or []
    words = sum(len(b.get("text", "").split()) for b in beats)
    if beats and words < min_words * 0.75:
        print(f"    [!] Script chhoti hai ({words} words, chahiye {min_words}) — "
              f"expand karwa raha hoon")
        messages += [
            {"role": "assistant",
             "content": json.dumps({"long_beats": beats}, ensure_ascii=False)},
            {"role": "user", "content": LENGTH_FEEDBACK.format(
                words=words, count=len(beats), average=words // max(1, len(beats)),
                min_words=min_words)},
        ]
        longer = _call_groq(messages)
        longer_beats = longer.get("long_beats") or []
        grown = sum(len(b.get("text", "").split()) for b in longer_beats)
        # Only accept the expansion if it actually grew without reintroducing
        # the repetition the first pass was checked for.
        if grown > words and len(_find_repeats(longer_beats)) <= len(repeats):
            # The revision is asked for long_beats only and often drops the
            # other keys; merging keeps the original title, tags and shorts.
            data = {**data, **{k: v for k, v in longer.items() if v}}
            words = grown
            print(f"    Expand ho gaya: {words} words")
        else:
            print(f"    [!] Expand fail, chhoti script hi use ho rahi hai")

    # Language check. The model agrees to write Hinglish, holds it for a few
    # beats, then slides into English -- a live run produced beats 4 to 9
    # entirely in English, which a Hindi TTS voice cannot read convincingly.
    # Shorts get the same treatment: they are the Short's entire script, so a
    # drifted one is exactly as unusable as a drifted long-form.
    for key in ("long_beats", "shorts_beats"):
        for attempt in range(2):
            beats = data.get(key) or []
            drifted = _english_beats(beats)
            if not beats or not drifted:
                break
            print(f"    [!] {key}: {len(drifted)}/{len(beats)} beats English mein "
                  f"chale gaye — Hinglish mein dobara likhwa raha hoon")
            examples = "\n".join(
                f'- beat {i + 1}: "{beats[i]["text"][:110]}..."' for i in drifted[:4])
            messages += [
                {"role": "assistant",
                 "content": json.dumps({key: beats}, ensure_ascii=False)},
                {"role": "user", "content": LANGUAGE_FEEDBACK.format(
                    key=key, examples=examples)},
            ]
            try:
                fixed = _call_llm(messages)
            except RuntimeError as exc:
                print(f"    [!] Hinglish retry fail: {str(exc)[:90]}")
                break
            fixed_beats = fixed.get(key) or []
            if fixed_beats and len(_english_beats(fixed_beats)) < len(drifted):
                # Only this key is replaced: the revision is asked for one list
                # and returning it should never disturb the other.
                data[key] = fixed_beats
                still = _english_beats(fixed_beats)
                print(f"    {key}: Hinglish theek hui"
                      + (f", {len(still)} abhi bhi English" if still else ""))
            else:
                print(f"    [!] {key}: Hinglish retry se fayda nahi hua")
                break

    for key in ("long_beats", "shorts_beats"):
        beats = data.get(key) or []
        cleaned = []
        for beat in beats:
            text = _sanitise(str(beat.get("text", "")))
            if len(text) < 15:
                continue
            cleaned.append({
                "text": text,
                "keywords": str(beat.get("keywords", "technology")).strip() or "technology",
            })
        if not cleaned:
            raise RuntimeError(f"Script mein {key} khaali hai. Dobara chalao.")

        # Runs after sanitising so the sentence text checked here is exactly
        # the text that will be spoken.
        _strip_invented_numbers(cleaned, facts, key)
        cleaned = [b for b in cleaned if len(b["text"].split()) >= 4]
        if not cleaned:
            raise RuntimeError(
                f"{key}: har line mein unverified numbers the. Ye topic chhod do.")
        data[key] = cleaned

    data["title"] = _sanitise(str(data.get("title", facts["topic"])))[:95]
    data["thumbnail_text"] = str(data.get("thumbnail_text", "AI NEWS")).upper()[:40]
    data["tags"] = [str(t).lower().strip()[:30] for t in (data.get("tags") or [])][:15]
    data["sources"] = facts["links"][:5]
    # Carried into the script so the stock-footage search and the YouTube
    # category both know what kind of story this is.
    data["category"] = category

    words = sum(len(b["text"].split()) for b in data["long_beats"])
    print(f"    Title: {data['title']}")
    print(f"    {len(data['long_beats'])} beats, ~{words} words (~{words // 150} min)")
    return data


def script_as_text(script: dict) -> str:
    lines = [f"TITLE: {script['title']}", "=" * 70, "", "--- LONG FORM ---", ""]
    for i, beat in enumerate(script["long_beats"], 1):
        lines += [f"[beat {i}]  (visual: {beat['keywords']})", beat["text"], ""]
    lines += ["", "--- SHORTS ---", ""]
    for i, beat in enumerate(script["shorts_beats"], 1):
        lines += [f"[beat {i}]  (visual: {beat['keywords']})", beat["text"], ""]
    lines += ["", "--- YOUR TAKE (apni raay yahan add karo) ---",
              script.get("your_take", ""), "",
              "--- DESCRIPTION ---", script.get("description", ""), "",
              "--- TAGS ---", ", ".join(script.get("tags", [])), "",
              "--- SOURCES ---"] + list(script.get("sources", []))
    return "\n".join(lines)
