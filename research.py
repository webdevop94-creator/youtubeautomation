"""Gather verifiable facts about a topic before any script is written.

The script model only ever sees text pulled from real articles, which is what
keeps invented numbers and fake quotes out of the final video.

Google News RSS is great for spotting trends but its article links are
JavaScript redirect shells with no usable URL inside, so the actual reading is
done through Bing News RSS, whose links carry the publisher URL as a query
parameter.
"""
import html
import re
import urllib.parse
import xml.etree.ElementTree as ET

import requests

BING_RSS = "https://www.bing.com/news/search?q={q}&format=RSS"
GOOGLE_RSS = "https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"}
MAX_ARTICLE_CHARS = 3000


def _strip_html(raw: str) -> str:
    raw = re.sub(r"(?is)<(script|style|nav|footer|header|aside|form)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?is)<br\s*/?>|</p>|</div>|</h\d>", "\n", raw)
    text = re.sub(r"(?s)<[^>]+>", " ", raw)
    text = html.unescape(text)
    return re.sub(r"[ \t]+", " ", text).strip()


def _real_url(bing_link: str) -> str:
    """Bing wraps links as .../apiclick.aspx?...&url=<encoded real url>."""
    if "bing.com/news/apiclick" not in bing_link:
        return bing_link
    query = urllib.parse.urlparse(bing_link).query
    target = urllib.parse.parse_qs(query).get("url", [""])[0]
    return urllib.parse.unquote(target) if target else ""


def _readable_body(url: str) -> str:
    """Best-effort article text. Paywalls and bot blocks are expected."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=18, allow_redirects=True)
        if resp.status_code != 200 or "html" not in resp.headers.get("content-type", ""):
            return ""
        text = _strip_html(resp.text)
    except Exception:
        return ""

    # Keep substantial sentences only — drops nav chrome and cookie banners.
    lines = [ln.strip() for ln in text.split("\n")]
    good = [ln for ln in lines if len(ln) > 80 and ln.count(" ") > 11]

    seen, unique = set(), []
    for line in good:
        key = line[:60]
        if key not in seen:
            seen.add(key)
            unique.append(line)
    return "\n".join(unique)[:MAX_ARTICLE_CHARS]


def _feed_items(url: str) -> list:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=25)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as exc:
        print(f"    [!] feed fail: {exc}")
        return []

    items = []
    for node in root.iter("item"):
        items.append({
            "title": (node.findtext("title") or "").strip(),
            "link": (node.findtext("link") or "").strip(),
            "description": _strip_html(node.findtext("description") or ""),
        })
    return items


def gather_facts(topic: dict, max_articles: int = 5) -> dict:
    """Return headlines + real article text for the topic."""
    print("[2/7] Facts verify kar raha hoon (hallucination se bachne ke liye)...")

    query = re.sub(r"[^\w\s]", " ", topic["title"])[:130].strip()
    encoded = urllib.parse.quote(query)

    headlines = [h for h in topic.get("related", []) if h]
    snippets = []

    bing_items = _feed_items(BING_RSS.format(q=encoded))
    google_items = _feed_items(GOOGLE_RSS.format(q=encoded + "+when:7d"))

    for item in bing_items + google_items:
        if item["title"] and item["title"] not in headlines:
            headlines.append(item["title"])
        if len(item["description"]) > 80:
            snippets.append(item["description"][:400])

    articles, sources = [], []

    # Google Trends hands over real publisher URLs with each trend. They are
    # already about this exact story and need no redirect unwrapping, so they
    # are read before falling back to a fresh Bing search.
    known = []
    for article in topic.get("articles", []):
        url = (article.get("url") or "").strip()
        if url:
            known.append(url)
            if article.get("title") and article["title"] not in headlines:
                headlines.append(article["title"])

    for url in known + [_real_url(i["link"]) for i in bing_items]:
        if len(articles) >= max_articles:
            break
        if not url or url in sources:
            continue
        body = _readable_body(url)
        if len(body) > 400:
            articles.append({"url": url, "text": body})
            sources.append(url)

    print(f"    {len(headlines)} headlines, {len(articles)} full articles padhe")
    if not articles:
        print("    [!] Koi article nahi khula — script sirf headlines par banegi, "
              "numbers use nahi honge")

    return {
        "topic": topic["title"],
        "source_name": topic.get("source", ""),
        "headlines": headlines[:16],
        "links": sources[:5] or [l for l in topic.get("links", [])[:3] if l],
        "snippets": snippets[:10],
        "articles": articles,
    }


def facts_prompt_block(facts: dict) -> str:
    """Flatten the research into the block handed to the script model.

    Deliberately no standalone list of extracted numbers: handing the model
    context-free figures makes it attach them to the wrong claim.
    """
    parts = [f"TOPIC: {facts['topic']}", "", "HEADLINES FROM REAL NEWS SOURCES:"]
    parts += [f"- {h}" for h in facts["headlines"]]

    if facts["snippets"]:
        parts += ["", "SUMMARIES:"] + [f"- {s}" for s in facts["snippets"]]

    for i, article in enumerate(facts["articles"], 1):
        parts += ["", f"ARTICLE {i} ({article['url']}):", article["text"][:2200]]

    return "\n".join(parts)


def source_richness(facts: dict) -> int:
    """How many beats the source material could support without filler.

    Deliberately uncapped: this measures the SOURCES, and is what decides
    whether a topic is worth covering at all. Keeping it separate from the
    runtime cap matters -- capping this number instead made every topic look
    too thin to use, because the floor for "good enough" sat above the cap.
    """
    words = sum(len(a["text"].split()) for a in facts["articles"])
    words += sum(len(s.split()) for s in facts["snippets"])
    if words > 1400:
        return 12
    if words > 700:
        return 9
    if words > 250:
        return 7
    return 5


def fact_depth(facts: dict) -> int:
    """How many beats to actually write: source-limited, then runtime-limited.

    Rich sources are a reason to be accurate, not a reason to run long.
    """
    import config

    return min(source_richness(facts), config.MAX_LONG_BEATS)
