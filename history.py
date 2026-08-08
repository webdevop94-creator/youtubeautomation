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


def is_duplicate(topic: dict, threshold: float = 0.5) -> tuple:
    """(True, previous_title) if this story has already been covered.

    Overlap is measured against the smaller keyword set so that a short
    follow-up headline still matches the longer original it repeats.
    """
    keys = viral.keywords(topic["title"])
    if len(keys) < 3:
        return False, ""

    for entry in _fresh(_load()):
        previous = set(entry.get("keywords", []))
        if len(previous) < 3:
            continue
        overlap = len(keys & previous) / max(1, min(len(keys), len(previous)))
        if overlap >= threshold:
            return True, entry.get("title", "")
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
        "folder": str(folder),
        "url": url,
    })
    config.HISTORY_FILE.write_text(
        json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


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
