"""Find and rank trending topics from Google News RSS (no API key needed)."""
import re
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests

import config

RSS = "https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# Words that signal a story people actually click on.
HOT_WORDS = [
    "launch", "launches", "unveil", "breakthrough", "first", "beats", "shuts",
    "bans", "record", "billion", "million", "open source", "free", "leak",
    "quits", "sues", "warns", "solves", "outperforms", "India", "layoff",
]

STOP = set("""the a an of in on for to and or is are was were with from at by as
this that it its new his her their they has have will can how why what""".split())


def _parse_date(raw: str):
    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
        try:
            dt = datetime.strptime(raw, fmt)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.now(timezone.utc)


def _keywords(title: str) -> set:
    words = re.findall(r"[a-zA-Z0-9]{3,}", title.lower())
    return {w for w in words if w not in STOP}


def _fetch(query: str, within_days: int) -> list:
    url = RSS.format(q=urllib.parse.quote(f"{query} when:{within_days}d"))
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as exc:  # network hiccup on one query shouldn't kill the run
        print(f"    [!] '{query}' feed fail: {exc}")
        return []

    items = []
    for node in root.iter("item"):
        title = (node.findtext("title") or "").strip()
        if not title:
            continue
        # Google News appends " - Publisher" to every headline.
        source = node.findtext("source") or ""
        clean = re.sub(r"\s+-\s+[^-]+$", "", title).strip() if source else title
        items.append({
            "title": clean,
            "raw_title": title,
            "link": (node.findtext("link") or "").strip(),
            "source": source.strip(),
            "published": _parse_date((node.findtext("pubDate") or "").strip()),
            "description": re.sub(r"<[^>]+>", " ", node.findtext("description") or ""),
        })
    return items


def fetch_trending(within_days: int = 2, limit: int = 5) -> list:
    """Return the top `limit` stories, ranked by freshness + coverage + hook value."""
    print("[1/7] Trending topics dhoondh raha hoon...")
    pool = []
    for query in config.NICHE_QUERIES:
        pool.extend(_fetch(query, within_days))
    print(f"    {len(pool)} headlines mile")

    if not pool:
        return []

    now = datetime.now(timezone.utc)
    clusters = []  # group near-duplicate headlines; a big cluster == a big story

    for item in pool:
        keys = _keywords(item["title"])
        if len(keys) < 3:
            continue
        for cluster in clusters:
            overlap = len(keys & cluster["keys"]) / max(1, min(len(keys), len(cluster["keys"])))
            if overlap > 0.5:
                cluster["items"].append(item)
                cluster["keys"] |= keys
                break
        else:
            clusters.append({"keys": keys, "items": [item]})

    ranked = []
    for cluster in clusters:
        best = min(cluster["items"], key=lambda i: now - i["published"])
        age_hours = (now - best["published"]).total_seconds() / 3600

        coverage = min(len(cluster["items"]), 8) * 6          # many outlets = big story
        freshness = max(0, 48 - age_hours) * 1.2              # decays over 2 days
        hook = sum(4 for w in HOT_WORDS if w.lower() in best["title"].lower())
        numbers = 5 if re.search(r"\d", best["title"]) else 0

        ranked.append({
            **best,
            "score": round(coverage + freshness + hook + numbers, 1),
            "coverage": len(cluster["items"]),
            "age_hours": round(age_hours, 1),
            "related": [i["title"] for i in cluster["items"][:6]],
            "links": [i["link"] for i in cluster["items"][:6]],
        })

    ranked.sort(key=lambda x: x["score"], reverse=True)
    return ranked[:limit]


def choose_topic(topics: list, auto: bool) -> dict:
    if not topics:
        raise SystemExit("[X] Koi trending topic nahi mila. Internet check karo.")

    print()
    for i, topic in enumerate(topics, 1):
        print(f"  {i}. {topic['title']}")
        print(f"     score {topic['score']} | {topic['coverage']} sources | "
              f"{topic['age_hours']}h purana | {topic['source']}")
    print()

    if auto:
        print(f"[auto] Chuna gaya: {topics[0]['title']}\n")
        return topics[0]

    while True:
        raw = input(f"Kaunsa topic? [1-{len(topics)}, ya Enter = 1]: ").strip()
        if not raw:
            return topics[0]
        if raw.isdigit() and 1 <= int(raw) <= len(topics):
            return topics[int(raw) - 1]
        print("  Galat input, dobara try karo.")
