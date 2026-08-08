"""Find what is genuinely going viral worldwide, across all categories.

`trends.py` answers "what is the latest AI news in India". This module answers a
different question: "what is the whole planet talking about right now, on any
subject". It reads three independent signals and trusts the overlap between
them rather than any single one:

  1. Google Trends daily searches, per country. Each trend carries an approximate
     search volume and, crucially, two or three real publisher URLs -- unlike
     Google News RSS links, these are directly readable by research.py.
  2. Google News section feeds (World, Business, Sport, Entertainment, Sci/Tech).
     Editorial judgement: how many newsrooms think this matters.
  3. Reddit's front page. Social judgement: what people actually clicked.

Why the overlap and not the raw scores: a single country's trending list is
dominated by local sport and celebrity names. A probe of the US list returned
"tre johnson" (a basketball injury note, 200 searches) alongside genuinely
global stories. One country trending on its own means almost nothing; the same
story trending in six countries at once is the real signal. So geo spread is
weighted far above raw search volume.

Reddit's JSON API returns 403 to server traffic and its per-subreddit RSS
rate-limits aggressively, so only the single r/all feed is requested.
"""
import html
import os
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests

import config

TRENDS_RSS = "https://trends.google.com/trending/rss?geo={geo}"
NEWS_SECTION = ("https://news.google.com/rss/headlines/section/topic/{topic}"
                "?hl=en-US&gl=US&ceid=US:en")
NEWS_TOP = "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en"
REDDIT_RSS = "https://www.reddit.com/r/all/top/.rss?t=day"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
ATOM = {"a": "http://www.w3.org/2005/Atom"}

# Words too common to identify a story. Matching on these creates false clusters
# ("Trump says X" and "Trump says Y" are different stories).
STOP = set("""the a an of in on for to and or is are was were with from at by as this
that it its it's new news his her their they them has have had will would can could
how why what when who where says said say after before over under against about
into out up down more most first last year years day days time today live update
updates report reports amid ahead top best worst full video watch photos you your we
our us my me not no yes just now then than only also very much many one two three
be been being do does did get got make made take took come came go went know knew
think thought see saw look looked want wanted give gave use used find found tell
told ask asked work worked seem seemed feel felt try tried leave left call called""".split())

# --- Category routing ------------------------------------------------------
# Google News section topics -> our internal category label.
NEWS_SECTIONS = {
    "WORLD": "world",
    "BUSINESS": "business",
    "TECHNOLOGY": "tech",
    "ENTERTAINMENT": "entertainment",
    "SPORTS": "sports",
    "SCIENCE": "science",
    "HEALTH": "health",
}

# Fallback classifier for signals that arrive without a section label
# (Google Trends and Reddit). First match wins, so order matters.
CATEGORY_HINTS = [
    # Matching is whole-word, so every inflection has to be listed. A live run
    # filed "Liverpool set to sign Barcelona's Araujo on loan" as general --
    # the list had "signing" but not "sign", and no club or position names.
    ("sports", """match matches cup league leagues goal goals striker strikers
        midfielder midfielders defender defenders goalkeeper coach manager
        nba nfl mlb nhl ufc fifa uefa ipl bcci atp wta
        cricket football soccer basketball tennis badminton hockey golf rugby
        olympics olympic f1 formula motogp wicket wickets innings runs
        touchdown playoff playoffs transfer transfers sign signs signed signing
        loan squad squads tournament athlete athletes quarterback boxing
        wrestling marathon premier liga bundesliga serie fc united utd city
        madrid barcelona liverpool arsenal chelsea bayern juventus psg
        striker sprint champion champions championship season fixture debut
        injury injured comeback retire retires retirement medal"""),
    ("entertainment", """film movie trailer teaser box office netflix disney hbo prime
        series season episode actor actress singer album song concert tour grammy
        oscar emmy celebrity premiere cast director bollywood hollywood streaming
        rapper band festival anime"""),
    ("tech", """ai model chip gpu app software iphone android google apple microsoft
        openai anthropic meta nvidia tesla startup launch update release beta
        cyber hack data server cloud robot chatgpt gemini
        semiconductor battery ev satellite"""),
    # No bare "price" here: it is a common surname and misfiled a celebrity
    # story as business on the first live run.
    ("business", """stock shares market ipo earnings revenue profit merger acquisition
        billion funding investors ceo layoffs economy inflation tariff bank crypto
        bitcoin trade prices pricing fed quarterly"""),
    ("science", """study researchers scientists discovery space nasa telescope planet
        asteroid mars moon rocket climate species fossil dna vaccine trial galaxy
        physics quantum experiment"""),
    ("health", """virus outbreak disease cases symptoms hospital doctors patients
        treatment drug fda cdc who diet obesity cancer diabetes mental"""),
]

# --- Safety ----------------------------------------------------------------
# A fully unattended channel will otherwise happily publish a Hinglish explainer
# on a school shooting. Beyond the obvious taste problem, YouTube's
# advertiser-friendly guidelines demonetise violent tragedy, and its elections
# and medical-misinformation policies carry strike risk -- neither is something
# to discover after an automated 3 AM upload.
BLOCKED = {
    "tragedy": """shooting shooter gunman killed kills killing murder murdered dead
        death dies died fatal massacre stabbing stabbed bomb bombing blast explosion
        attack attacker terror terrorist crash collapse quake earthquake tsunami
        flood wildfire hurricane casualties victims injured wounded funeral obituary
        suicide overdose missing abduction kidnap hostage""",
    "crime": """arrest arrested charged charges indicted indictment trial verdict guilty
        convicted conviction lawsuit sues sued rape assault abuse trafficking
        scandal allegations alleged accuser accused prison jail sentenced fraud
        scam police raid investigation probe suspect suspects prosecutor
        prosecutors prosecution defendant court judge jury plea felony arson
        burglary robbery stolen smuggling extortion bribery corruption
        laundering warrant manhunt fugitive gang cartel""",
    # "theft" is deliberately absent: it blocked "Grand Theft Auto VI", which is
    # a games story, not a crime story. Generic crime nouns that appear in
    # entertainment titles cost more than they catch.
    "politics": """election vote voter ballot poll campaign senate congress parliament
        president presidential prime minister governor impeach protest protests riot
        war strike military troops missile invasion sanctions ceasefire treaty
        immigration deportation border republican democrat citizenship birthright
        visa asylum refugee diplomat diplomatic embassy summit coup regime
        sovereignty nuclear tariff tariffs geopolitical nomination nominee
        administration lawmakers policy bill legislation federal""",
    # Someone's private misfortune is not channel material. The first live agent
    # run picked a story about a family's crisis and their children asking
    # photographers for privacy -- none of the buckets above contained a single
    # word from that headline.
    "private": """paparazzi privacy private intrusion harassment stalker leaked nude
        custody divorce split breakup separated affair cheating feud rehab
        hospitalised hospitalized diagnosis diagnosed illness ill treatment
        condition emergency mourning grieving grief tribute condolences memorial
        remembers heartbreak heartbroken children kids son daughter family crisis
        struggle battle apologise apologises apology backlash slammed blasted"""
}
BLOCKED_SETS = {name: set(words.split()) for name, words in BLOCKED.items()}

# Junk that shows up in trending lists: typos, adult terms, single letters.
GARBAGE = re.compile(r"^(?:[a-z]{1,2}|\d+|[^a-z]*)$", re.I)

# Stories that are worthless by the time a video finishes rendering. A live
# match blog trends hard for ninety minutes and is dead content afterwards --
# the first live test ranked a Bayern pre-season friendly above an iPhone
# pricing story purely on search volume.
PERISHABLE = re.compile(
    r"\b(live|liveblog|live blog|vs|versus|v|highlights|full time|half time|"
    r"line ?ups?|starting xi|how to watch|where to watch|watch live|stream(ing)?"
    r"|score(s|card)?|scoreboard|preview|prediction[s]?|odds|betting|"
    r"play by play|minute by minute|recap|final score|what time|kick ?off|"
    r"tip ?off|weather forecast|traffic|horoscope|lottery|jackpot|results?|"
    # Broadcast and fixture listings. A live run ranked "FFCtv: Fulham FC v
    # Crystal Palace" first -- a TV schedule entry, not a story, and the
    # single-letter "v" between club names slipped past "vs|versus".
    r"tv|telecast|broadcast|coverage|channel|fixtures?|match ?day|"
    r"team news|squad news|build ?up|as it happened|latest updates)\b",
    re.I)

# Formats that make good explainer videos regardless of category.
EXPLAINABLE = re.compile(
    r"\b(launch(es|ed)?|unveil(s|ed)?|announce(s|d|ment)?|reveal(s|ed)?|"
    r"price|pricing|cost|specs?|features?|release date|first look|"
    r"record|fastest|biggest|largest|world's|history|breakthrough|discovery|"
    r"study|research|scientists?|why|how|what is|explained|guide|"
    r"ban(s|ned)?|rule[s]?|deal|acquire[sd]?|merger|funding|raises?|"
    r"quit[s]?|steps down|resigns?|returns?|comeback|trailer|teaser|"
    r"box office|review|update|new)\b",
    re.I)


# Generous on purpose. A home connection was measured taking 22 seconds for a
# single trends feed, so a 20-second timeout killed requests that were about to
# succeed -- and then retried them, doubling the wall clock for nothing.
FEED_TIMEOUT = int(os.getenv("FEED_TIMEOUT", "45"))


def _get(url: str, tries: int = 2) -> bytes:
    """Fetch with one polite retry. A dead feed must not kill the whole run."""
    for attempt in range(tries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=FEED_TIMEOUT)
            if resp.status_code == 200:
                return resp.content
            if resp.status_code == 429 and attempt + 1 < tries:
                time.sleep(3)
                continue
            print(f"    [!] HTTP {resp.status_code}: {url[:70]}")
            return b""
        except Exception as exc:
            if attempt + 1 < tries:
                continue
            print(f"    [!] {type(exc).__name__}: {url[:70]}")
    return b""


def _strip(raw: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", raw or ""))).strip()


def _tag(node) -> str:
    return node.tag.split("}")[-1]


def keywords(text: str) -> set:
    """Content words used for clustering and duplicate detection."""
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9'\-]{2,}", text.lower())
    return {w.strip("'-") for w in words if w not in STOP and len(w) > 2}


def classify(text: str, given: str = "") -> str:
    if given:
        return given
    low = text.lower()
    words = set(re.findall(r"[a-z]+", low))
    for label, hints in CATEGORY_HINTS:
        if words & set(hints.split()):
            return label
    return "general"


def safety_flags(text: str) -> list:
    """Which blocked buckets this headline touches. Empty means safe to publish."""
    words = set(re.findall(r"[a-z]+", text.lower()))
    return [name for name, bad in BLOCKED_SETS.items() if words & bad]


# --- Signal 1: Google Trends ----------------------------------------------

def _traffic_number(raw: str) -> int:
    digits = re.sub(r"[^\d]", "", raw or "")
    return int(digits) if digits else 0


def fetch_google_trends(geos: list) -> list:
    """One trending list per country, flattened into individual signals."""
    signals = []
    for geo in geos:
        body = _get(TRENDS_RSS.format(geo=geo))
        if not body:
            continue
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            continue

        for item in root.iter("item"):
            title = _strip(item.findtext("title") or "")
            if not title or GARBAGE.match(title):
                continue
            # Non-Latin trends (Hindi/Bengali/Japanese) cannot be searched for
            # English source articles, so they are unusable downstream.
            if not re.search(r"[a-zA-Z]{3}", title):
                continue

            traffic, articles = 0, []
            for child in item:
                name = _tag(child)
                if name == "approx_traffic":
                    traffic = _traffic_number(child.text or "")
                elif name == "news_item":
                    parts = {_tag(gc): (gc.text or "") for gc in child}
                    url = parts.get("news_item_url", "").strip()
                    if url:
                        articles.append({
                            "title": _strip(parts.get("news_item_title", "")),
                            "url": url,
                            "source": _strip(parts.get("news_item_source", "")),
                        })

            headline = articles[0]["title"] if articles else title
            signals.append({
                "source": "trends",
                "geo": geo,
                "term": title,
                "title": headline,
                # Cluster on the term AND the article headline: the bare search
                # term ("basketball") is too thin to match anything on its own.
                "text": f"{title} {' '.join(a['title'] for a in articles)}",
                "traffic": traffic,
                "articles": articles,
                "category": "",
            })
    return signals


# --- Signal 2: Google News sections ---------------------------------------

def _news_items(body: bytes, category: str) -> list:
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []

    now = datetime.now(timezone.utc)
    items = []
    for node in root.iter("item"):
        title = _strip(node.findtext("title") or "")
        if not title:
            continue
        # Google appends " - Publisher" to every headline.
        publisher = _strip(node.findtext("source") or "")
        clean = re.sub(r"\s+-\s+[^-]{2,40}$", "", title).strip() if publisher else title

        published = now
        raw_date = (node.findtext("pubDate") or "").strip()
        for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z"):
            try:
                parsed = datetime.strptime(raw_date, fmt)
                published = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
                break
            except ValueError:
                continue

        items.append({
            "source": "news",
            "geo": "",
            "term": "",
            "title": clean,
            "text": clean,
            "traffic": 0,
            # Google News links are JS redirect shells; research.py resolves
            # readable URLs separately, so nothing is passed through here.
            "articles": [],
            "category": category,
            "publisher": publisher,
            "age_hours": (now - published).total_seconds() / 3600,
        })
    return items


def fetch_news_sections(sections: list, per_section: int = 25) -> list:
    signals = []
    for topic in sections:
        category = NEWS_SECTIONS.get(topic, "general")
        body = _get(NEWS_SECTION.format(topic=topic))
        if body:
            signals.extend(_news_items(body, category)[:per_section])
    body = _get(NEWS_TOP)
    if body:
        signals.extend(_news_items(body, "")[:per_section])
    return signals


# --- Signal 3: Reddit ------------------------------------------------------

def fetch_reddit(limit: int = 40) -> list:
    body = _get(REDDIT_RSS)
    if not body:
        return []
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return []

    signals = []
    for entry in root.findall("a:entry", ATOM)[:limit]:
        title = _strip(entry.findtext("a:title", "", ATOM))
        if len(title) < 20:
            continue
        signals.append({
            "source": "reddit",
            "geo": "",
            "term": "",
            "title": title,
            "text": title,
            "traffic": 0,
            "articles": [],
            "category": "",
        })
    return signals


# --- Clustering + scoring --------------------------------------------------

def _cluster(signals: list, threshold: float = 0.34) -> list:
    """Group signals describing the same story.

    Overlap is measured against the smaller keyword set, so a two-word search
    term still matches a long headline that contains it. The threshold is lower
    than trends.py's 0.5 because signals here come from unrelated feeds with no
    shared vocabulary conventions.
    """
    clusters = []
    for signal in signals:
        keys = keywords(signal["text"])
        if len(keys) < 2:
            continue
        for cluster in clusters:
            shared = keys & cluster["keys"]
            if len(shared) / max(1, min(len(keys), len(cluster["keys"]))) >= threshold:
                cluster["signals"].append(signal)
                cluster["keys"] |= keys
                break
        else:
            clusters.append({"keys": set(keys), "signals": [signal]})
    return clusters


def _pick_headline(signals: list) -> str:
    """The most descriptive title in a cluster.

    News headlines are written to be self-contained, so they beat a Reddit joke
    title or a bare two-word search term as the topic we hand to research.
    """
    news = [s for s in signals if s["source"] == "news"]
    pool = news or signals
    # A cluster often holds both a live-blog title and a proper write-up of the
    # same event. Prefer the write-up -- it is what survives to publication.
    lasting = [s for s in pool if not PERISHABLE.search(s["title"])]
    return max(lasting or pool, key=lambda s: len(s["title"]))["title"]


def score_cluster(cluster: dict) -> dict:
    signals = cluster["signals"]
    geos = {s["geo"] for s in signals if s["geo"]}
    sources = {s["source"] for s in signals}
    headline = _pick_headline(signals)
    text = " ".join(s["title"] for s in signals)

    # Geo spread is the strongest evidence of genuine global virality, so it is
    # weighted an order of magnitude above raw search volume.
    geo_points = len(geos) * 22
    # Cross-signal agreement: trends AND news AND reddit is a much stronger
    # claim than three hits inside one feed.
    source_points = (len(sources) - 1) * 30
    news_points = min(sum(1 for s in signals if s["source"] == "news"), 8) * 7
    reddit_points = min(sum(1 for s in signals if s["source"] == "reddit"), 3) * 12

    traffic = max((s["traffic"] for s in signals), default=0)
    traffic_points = min(traffic / 1000.0, 20) * 2

    ages = [s["age_hours"] for s in signals if "age_hours" in s]
    freshness = max(0.0, 36 - min(ages)) * 0.8 if ages else 12.0

    # Readable article URLs decide whether a script can be written at all, so a
    # cluster that arrives with them is worth more than one that does not.
    articles = [a for s in signals for a in s["articles"]]
    article_points = min(len(articles), 6) * 5

    # A perishable story scores near zero however hard it is trending; an
    # explainable one gets a modest nudge. Judged on the chosen headline only,
    # since cluster-wide text picks up stray words from loosely related items.
    perishable = bool(PERISHABLE.search(headline))
    shape_points = -90 if perishable else (14 if EXPLAINABLE.search(headline) else 0)

    flags = safety_flags(text)
    category = classify(text, next((s["category"] for s in signals if s["category"]), ""))

    return {
        "title": headline,
        "category": category,
        "score": round(geo_points + source_points + news_points + reddit_points
                       + traffic_points + freshness + article_points + shape_points, 1),
        "perishable": perishable,
        "signal_count": len(signals),
        "geos": sorted(geos),
        "signal_sources": sorted(sources),
        "traffic": traffic,
        "safety_flags": flags,
        "terms": sorted({s["term"] for s in signals if s["term"]}),
        "related": list(dict.fromkeys(s["title"] for s in signals))[:8],
        "links": list(dict.fromkeys(a["url"] for a in articles))[:6],
        "articles": articles[:6],
        "keys": cluster["keys"],
        "source": ", ".join(sorted(sources)),
    }


def fetch_viral(geos: list = None, sections: list = None, limit: int = 8,
                allow_flagged: bool = None, categories: list = None) -> list:
    """Rank what the world is talking about right now."""
    geos = geos or config.VIRAL_GEOS
    sections = sections or config.NEWS_SECTIONS_ENABLED
    allow_flagged = config.ALLOW_SENSITIVE if allow_flagged is None else allow_flagged
    categories = set(categories or config.ALLOWED_CATEGORIES)

    print("[1/7] Duniya bhar ke viral topics dhoondh raha hoon...")
    signals = []
    signals += fetch_google_trends(geos)
    trends_count = len(signals)
    signals += fetch_news_sections(sections)
    news_count = len(signals) - trends_count
    signals += fetch_reddit()
    reddit_count = len(signals) - trends_count - news_count
    print(f"    trends {trends_count} | news {news_count} | reddit {reddit_count} "
          f"({len(geos)} countries)")

    if not signals:
        return []

    ranked = [score_cluster(c) for c in _cluster(signals)]
    total = len(ranked)

    if not allow_flagged:
        blocked = sum(1 for t in ranked if t["safety_flags"])
        ranked = [t for t in ranked if not t["safety_flags"]]

        # Chasing individual words through world news is a losing game: a live
        # run let through "Trump targets birthright citizenship" because none
        # of those words were listed. The whole category is politics and
        # conflict, so it goes as a category.
        political = sum(1 for t in ranked if t["category"] == "world")
        ranked = [t for t in ranked if t["category"] != "world"]

        if blocked or political:
            print(f"    {blocked + political} topics safety filter se hate "
                  f"(tragedy/crime/politics/private)")

    perished = sum(1 for t in ranked if t["perishable"])
    ranked = [t for t in ranked if not t["perishable"]]

    # A single headline from a single feed is one newsroom's choice, not a
    # trend. Two independent signals, or a country's trending list, is the
    # minimum evidence worth building a video on.
    ranked = [t for t in ranked if t["signal_count"] >= 2 or t["geos"]]

    if categories:
        ranked = [t for t in ranked if t["category"] in categories]

    print(f"    {total} stories -> {len(ranked)} usable "
          f"({perished} perishable/live hate)")

    ranked.sort(key=lambda t: t["score"], reverse=True)
    return ranked[:limit]


def describe(topic: dict) -> str:
    bits = [f"score {topic['score']}", topic["category"]]
    if topic["geos"]:
        bits.append(f"{len(topic['geos'])} countries: {','.join(topic['geos'][:5])}")
    bits.append("+".join(topic["signal_sources"]))
    if topic["traffic"]:
        bits.append(f"{topic['traffic']:,}+ searches")
    if topic["links"]:
        bits.append(f"{len(topic['links'])} readable links")
    if topic["safety_flags"]:
        bits.append(f"FLAGGED: {','.join(topic['safety_flags'])}")
    return " | ".join(bits)


def choose_topic(topics: list, auto: bool) -> dict:
    if not topics:
        raise SystemExit("[X] Koi viral topic nahi mila. Internet check karo.")

    print()
    for i, topic in enumerate(topics, 1):
        print(f"  {i}. {topic['title']}")
        print(f"     {describe(topic)}")
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


if __name__ == "__main__":
    for i, t in enumerate(fetch_viral(), 1):
        print(f"\n{i}. {t['title']}")
        print(f"   {describe(t)}")
        for link in t["links"][:3]:
            print(f"   - {link[:100]}")
