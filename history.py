"""Remember what the channel has already covered, so the agent never repeats.

A big story stays on the trending lists for days. Without this, an agent
scheduled daily would publish the same iPhone pricing video every morning for a
week -- which reads as spam to viewers and to YouTube.

Matching is on content keywords rather than exact titles, because the same
story arrives with a different headline from every publisher.
"""
import json
from datetime import datetime, timedelta

import config
import viral


def _load() -> list:
    if not config.HISTORY_FILE.exists():
        return []
    try:
        data = json.loads(config.HISTORY_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        # A corrupt history should cost one duplicate video, not the whole run.
        print("    [!] history.json padha nahi gaya, fresh start")
        return []


def _fresh(entries: list, days: int = None) -> list:
    days = config.HISTORY_DAYS if days is None else days
    cutoff = datetime.now() - timedelta(days=days)
    kept = []
    for entry in entries:
        try:
            if datetime.fromisoformat(entry["covered_at"]) >= cutoff:
                kept.append(entry)
        except (KeyError, ValueError):
            continue
    return kept


def subjects_of(script: dict) -> set:
    """What a script is actually ABOUT, as English words.

    Every beat carries a `keywords` string naming what the picture should show
    -- "planet venus spinning space cosmos", "ancient egyptian tomb honey jar".
    That is the only place the subject of a Hindi facts video is written down in
    a form two videos can be compared on: the title says
    "5 हैरान करने वाले तथ्य" and names nothing.
    """
    words = set()
    for key in ("long_beats", "shorts_beats"):
        for beat in script.get(key) or []:
            words |= viral.keywords(str(beat.get("keywords", "")))
    return words


def _overlap(a: set, b: set) -> float:
    """Share of the smaller set that also appears in the larger.

    Measured against the smaller side so a short follow-up still matches the
    longer original it repeats.
    """
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def is_duplicate(topic: dict, script: dict = None, threshold: float = 0.5) -> tuple:
    """(True, previous_title) if this has already been covered.

    Two independent signals, because either one alone lets repeats through:

      Title keywords catch a story arriving under a reworded headline. On the
      animation channel they catch very little -- the titles are generic by
      design -- so this used to be the whole check and passed everything.

      Subject keywords catch the case that actually matters here: a fresh
      title over yesterday's facts. Held to a higher bar and a minimum size
      because story beats describe scenes rather than subjects ("forest path",
      "curious girl"), and two genuinely different stories can share a few.
    """
    keys = viral.keywords(topic.get("title", ""))
    subjects = subjects_of(script) if script else set()

    for entry in _fresh(_load()):
        previous = set(entry.get("keywords", []))
        if len(keys) >= 3 and len(previous) >= 3 \
                and _overlap(keys, previous) >= threshold:
            return True, entry.get("title", "")

        seen = set(entry.get("subjects", []))
        if len(subjects) >= 6 and len(seen) >= 6 \
                and _overlap(subjects, seen) >= 0.6:
            return True, entry.get("video_title") or entry.get("title", "")
    return False, ""


def record(topic: dict, script: dict, folder, url: str = "") -> None:
    """Log a covered topic. Called after a video is built, uploaded or not."""
    entries = _fresh(_load())
    # Keywords from both the source headline and the final title: the script
    # model often rewrites the topic into words the original never used.
    keys = viral.keywords(topic.get("title", "")) | viral.keywords(script.get("title", ""))
    entries.append({
        "covered_at": datetime.now().isoformat(timespec="seconds"),
        "title": topic.get("title", ""),
        "video_title": script.get("title", ""),
        "category": topic.get("category", ""),
        "keywords": sorted(keys),
        # The subjects, not just the headline. history.json is the only thing
        # that survives a cloud runner -- output/ is gitignored and the machine
        # is deleted -- so anything the next run needs in order not to repeat
        # itself has to be written down here or it is gone.
        "subjects": sorted(subjects_of(script)),
        "beat_topics": [str(b.get("keywords", "")) for b in
                        (script.get("long_beats") or [])],
        "folder": str(folder),
        "url": url,
    })
    config.HISTORY_FILE.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def covered_topics(limit: int = 60) -> list:
    """Recent titles and beat subjects, newest first, for the writer's brief.

    This is the avoid-list that keeps a facts video off yesterday's facts. It
    reads history.json rather than the output folders because on a GitHub
    runner there are no output folders -- the checkout is fresh every morning,
    and output/ is gitignored. Left to the folders alone the cloud agent saw an
    empty avoid-list every single day and went back to Venus.
    """
    seen, out = set(), []
    for entry in reversed(_fresh(_load())):
        for text in [entry.get("video_title") or entry.get("title") or ""] \
                + list(entry.get("beat_topics") or []):
            text = text.strip()
            if text and text not in seen:
                seen.add(text)
                out.append(text)
    return out[:limit]


def filter_new(topics: list) -> list:
    """Drop already-covered stories, keeping order."""
    fresh = []
    for topic in topics:
        duplicate, previous = is_duplicate(topic)
        if duplicate:
            print(f"    [skip] pehle ho chuka: {topic['title'][:60]} "
                  f"(~ {previous[:40]})")
            continue
        fresh.append(topic)
    return fresh


def summary(limit: int = 10) -> str:
    entries = _fresh(_load())
    if not entries:
        return "History khaali hai."
    lines = [f"{len(entries)} topics pichhle {config.HISTORY_DAYS} din mein:"]
    for entry in entries[-limit:]:
        stamp = entry["covered_at"][:16].replace("T", " ")
        link = entry.get("url") or "(upload nahi hua)"
        lines.append(f"  {stamp}  {entry.get('video_title', '')[:55]}")
        lines.append(f"                    {link}")
    return "\n".join(lines)


if __name__ == "__main__":
    print(summary())
