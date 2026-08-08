"""One visual per narration beat: a generated image first, stock footage second.

Stock libraries cannot illustrate a specific story. Asked for "man standing at
podium press conference" for a beat about FIFA's president facing revolt,
Pexels returned a man wading in the sea -- and no amount of keyword tuning
fixes that, because no stock library has that press conference in it.

A generated image is drawn from what the beat actually says, so it matches by
construction. Pexels stays as the fallback: if generation is slow or down, a
loosely related clip still beats a blank screen.

The generator is free and needs no key, which is the only reason this is the
default rather than an option.
"""
import os
import random
import re
import urllib.parse
from pathlib import Path

import requests

import config

VIDEO_API = "https://api.pexels.com/videos/search"
PHOTO_API = "https://api.pexels.com/v1/search"
IMAGE_GEN_API = "https://image.pollinations.ai/prompt/"
TIMEOUT = 30
# Generation takes ~45s per beat on this connection. Nobody is waiting during
# the scheduled run, and a matching visual is worth the wall clock.
GEN_TIMEOUT = int(os.getenv("IMAGE_GEN_TIMEOUT", "180"))

# When a beat's own keywords find nothing, the replacement has to at least
# belong to the same world as the story. This file used to hold one tech-only
# list, left over from when the channel was AI news -- so a football video fell
# back to circuit boards and server rooms.
FALLBACKS = {
    "sports": ["football stadium crowd", "athlete training gym",
               "empty stadium seats", "sports trophy closeup",
               "football pitch aerial", "locker room"],
    "tech": ["data center servers", "circuit board macro", "computer code screen",
             "hands holding smartphone", "electronics factory", "laptop keyboard"],
    "science": ["laboratory microscope", "telescope night sky", "rocket launch",
                "scientist working lab", "dna animation", "earth from space"],
    "business": ["stock chart screen", "trading floor", "shipping containers port",
                 "business people meeting", "shopping mall crowd", "office towers"],
    "entertainment": ["cinema seats", "film camera set", "concert crowd hands",
                      "red carpet lights", "recording studio microphone",
                      "theatre stage lights"],
    "health": ["hospital corridor", "doctor stethoscope", "medical laboratory",
               "person jogging park", "fresh vegetables market", "pharmacy shelves"],
    "world": ["city skyline aerial", "crowded street market", "airport terminal",
              "cargo ship ocean", "world map closeup", "flags waving"],
    "general": ["city skyline sunset", "crowded street people", "people walking",
                "sunrise landscape", "busy intersection", "crowd of people"],
}

# Paired with a lone concrete keyword to make the search specific enough. This
# used to be the hardcoded word "technology" for every category, which turned
# a football beat's search into "araujo technology".
COMPANION = {
    "sports": "stadium", "tech": "technology", "science": "laboratory",
    "business": "office", "entertainment": "stage", "health": "hospital",
    "world": "city", "general": "people",
}


def _fallbacks(category: str) -> list:
    return FALLBACKS.get(category, FALLBACKS["general"])


def _headers():
    config.require_key("PEXELS_API_KEY", config.PEXELS_API_KEY,
                       "https://www.pexels.com/api/")
    return {"Authorization": config.PEXELS_API_KEY}


# Stock search is literal: "cloud" returns sky, "india" returns village scenery.
# These rewrites keep abstract script keywords from producing irrelevant footage.
AMBIGUOUS = {
    "cloud": "server rack datacenter",
    "clouds": "server rack datacenter",
    "growth": "business chart office",
    "race": "business people running office",
    "adoption": "team using computers",
    "ecosystem": "modern office workspace",
    "future": "futuristic technology interface",
    "security": "network cables server",
    "privacy": "laptop lock screen",
    "india": "mumbai city skyline",
    "indian": "mumbai city skyline",
    "investment": "financial charts screen",
    "funding": "financial charts screen",
    "power": "electrical substation cables",
    "energy": "power plant turbines",
    "intelligence": "computer server lights",
    "innovation": "engineer laboratory equipment",
    "demand": "busy office workers",
    "performance": "computer screen code",
    "workload": "server room technician",
    "zone": "data center corridor",
    "zones": "data center corridor",
    "region": "world map screen",
    "asset": "modern building exterior",
    "opportunity": "business people meeting",
    "customer": "people using smartphones",
    "customers": "people using smartphones",
    "enterprise": "corporate office building",
    "enterprises": "corporate office building",
    "ai": "artificial intelligence computer",
}

# Words a stock library has never heard of: people, clubs, teams, products.
# Searching them returns nothing, and the fallback then decides the shot -- so
# they are swapped for the scene the beat is really describing.
SUBJECT_SCENES = {
    "sports": {
        "injury": "physiotherapist treating athlete", "injured": "athlete on ground injury",
        "contract": "signing document pen", "salary": "counting money cash",
        "wages": "counting money cash", "fee": "counting money cash",
        "transfer": "airport departure board", "loan": "signing document pen",
        "captain": "team huddle", "manager": "coach on touchline",
        "coach": "coach on touchline", "fans": "stadium crowd cheering",
        "goals": "football hitting net", "goal": "football hitting net",
        "record": "sports trophy closeup", "career": "football boots pitch",
        "season": "empty stadium seats", "training": "athlete training gym",
        "defence": "football players tackling", "defense": "football players tackling",
        "squad": "team huddle", "club": "stadium exterior",
    },
    "business": {
        "shares": "stock chart screen", "stock": "stock chart screen",
        "revenue": "financial charts screen", "profit": "counting money cash",
        "salary": "counting money cash", "ceo": "executive in boardroom",
        "investors": "business people meeting", "market": "trading floor",
    },
    "entertainment": {
        "trailer": "cinema projector", "release": "cinema seats audience",
        "casting": "film audition", "director": "film director chair",
        "boxoffice": "cinema ticket counter", "album": "recording studio",
    },
}


def _subject_scene(word: str, category: str) -> str:
    return SUBJECT_SCENES.get(category, {}).get(word, "")

# Words that describe the video itself or carry no visual meaning at all.
DROP = {"the", "and", "for", "with", "new", "big", "best", "special", "more",
        "aapke", "liye", "video", "like", "share", "next", "full", "story",
        "subscribe", "channel", "services", "service", "thing", "stuff"}


def _clean_query(keywords: str, category: str = "general") -> str:
    words = [w.lower() for w in re.findall(r"[a-zA-Z]{2,}", keywords)]
    words = [w for w in words if w not in DROP]
    if not words:
        return random.choice(_fallbacks(category))

    # A subject word the library cannot show ("injury", "salary") is worth more
    # as the scene it implies than as a literal search term.
    scene = next((s for w in words if (s := _subject_scene(w, category))), "")
    if scene:
        return scene

    concrete = [w for w in words if w not in AMBIGUOUS]
    mapped = next((AMBIGUOUS[w] for w in words if w in AMBIGUOUS), "")

    # One concrete word on its own is too vague to search well — pair it with
    # the mapped scene, or with a companion word from this story's world.
    if len(concrete) >= 2:
        return " ".join(concrete[:3])
    if concrete and mapped:
        return f"{concrete[0]} {mapped}".strip()
    if concrete:
        return f"{concrete[0]} {COMPANION.get(category, 'people')}"
    return mapped or random.choice(_fallbacks(category))


# Style suffix per category. Without it the generator drifts between photo,
# painting and 3D render from beat to beat, which reads as a mismatched
# slideshow even when every individual image is fine.
GEN_STYLE = {
    "sports": "photorealistic sports photography, dramatic stadium lighting",
    "tech": "photorealistic product and technology photography, clean lighting",
    "science": "photorealistic science photography, documentary lighting",
    "business": "photorealistic corporate photography, natural office light",
    "entertainment": "photorealistic film still, cinematic lighting",
    "health": "photorealistic medical documentary photography",
    "world": "photorealistic photojournalism, natural light",
    "general": "photorealistic editorial photography, natural light",
}

# The generator is literal about people. Naming a real person produces a
# stranger who looks nothing like them, which is worse than not trying, so
# beats are described by role and setting instead.
GEN_NEGATIVE = "no text, no watermark, no letters, no logos, no captions"


def _gen_prompt(keywords: str, category: str) -> str:
    """Full scene description, unlike the stock query.

    _clean_query truncates to three words because search APIs do better with
    short queries -- "man standing at podium press conference" becomes "man
    standing at". A generator wants the opposite: every word of the scene.
    """
    scene = " ".join(w for w in re.findall(r"[a-zA-Z]{2,}", keywords)
                     if w.lower() not in DROP)
    if not scene:
        scene = random.choice(_fallbacks(category))
    style = GEN_STYLE.get(category, GEN_STYLE["general"])
    return f"{scene}, {style}, {GEN_NEGATIVE}"


def _generate_image(keywords: str, category: str, vertical: bool, dest: Path,
                    seed: int) -> bool:
    """Draw this beat's scene. Returns False so the caller can fall back."""
    width, height = (720, 1280) if vertical else (1280, 720)
    url = (IMAGE_GEN_API + urllib.parse.quote(_gen_prompt(keywords, category))
           + f"?width={width}&height={height}&seed={seed}&nologo=true&model=flux")
    try:
        resp = requests.get(url, timeout=GEN_TIMEOUT)
        if resp.status_code != 200 or len(resp.content) < 5000:
            return False
        dest.write_bytes(resp.content)
        return dest.stat().st_size > 5000
    except Exception:
        dest.unlink(missing_ok=True)
        return False


def _search_video(query: str, vertical: bool, used: set):
    params = {"query": query, "per_page": 15,
              "orientation": "portrait" if vertical else "landscape"}
    try:
        resp = requests.get(VIDEO_API, headers=_headers(), params=params, timeout=TIMEOUT)
        if resp.status_code != 200:
            return None
        videos = resp.json().get("videos", [])
    except Exception:
        return None

    random.shuffle(videos)
    for video in videos:
        if video["id"] in used:
            continue
        # Prefer ~HD files: big enough to look sharp, small enough to download fast.
        files = sorted(
            (f for f in video.get("video_files", []) if f.get("width")),
            key=lambda f: abs(f["width"] - (1080 if vertical else 1920)))
        if files:
            used.add(video["id"])
            return {"url": files[0]["link"], "ext": ".mp4", "is_image": False,
                    "credit": video.get("user", {}).get("name", "Pexels")}
    return None


def _search_photo(query: str, vertical: bool, used: set):
    params = {"query": query, "per_page": 15,
              "orientation": "portrait" if vertical else "landscape"}
    try:
        resp = requests.get(PHOTO_API, headers=_headers(), params=params, timeout=TIMEOUT)
        if resp.status_code != 200:
            return None
        photos = resp.json().get("photos", [])
    except Exception:
        return None

    random.shuffle(photos)
    for photo in photos:
        if photo["id"] in used:
            continue
        used.add(photo["id"])
        return {"url": photo["src"]["large2x"], "ext": ".jpg", "is_image": True,
                "credit": photo.get("photographer", "Pexels")}
    return None


def _download(url: str, dest: Path) -> bool:
    try:
        with requests.get(url, stream=True, timeout=90) as resp:
            resp.raise_for_status()
            with open(dest, "wb") as fh:
                for chunk in resp.iter_content(1 << 16):
                    fh.write(chunk)
        return dest.stat().st_size > 10_000
    except Exception:
        dest.unlink(missing_ok=True)
        return False


def fetch_visuals(beats: list, work_dir: Path, vertical: bool, label: str,
                  category: str = "general") -> list:
    """Return one asset dict per beat. Entries may be None -> caller draws a text card."""
    print(f"[5/7] Visuals download kar raha hoon ({label}, {category})...")
    media_dir = work_dir / f"media_{label}"
    media_dir.mkdir(parents=True, exist_ok=True)

    used, assets = set(), []
    for i, beat in enumerate(beats):
        query = _clean_query(beat["keywords"], category)

        if config.USE_AI_VISUALS:
            dest = media_dir / f"beat_{i:02d}.jpg"
            # Distinct seed per beat: one seed for the whole video makes every
            # scene a variation of the same picture.
            if _generate_image(beat["keywords"], category, vertical, dest,
                               seed=1000 + i * 17):
                assets.append({"path": dest, "ext": ".jpg", "is_image": True,
                               "url": "", "credit": "AI generated"})
                print(f"    beat {i + 1}/{len(beats)}  '{query}' -> AI image")
                continue
            print(f"    beat {i + 1}/{len(beats)}  AI fail, stock try kar raha hoon")

        asset = _search_video(query, vertical, used)
        if not asset:  # narrower query failed — try the first keyword alone
            asset = _search_video(query.split()[0], vertical, used)
        if not asset:
            asset = _search_photo(query, vertical, used)
        if not asset:
            asset = _search_video(random.choice(_fallbacks(category)), vertical, used)

        if asset:
            dest = media_dir / f"beat_{i:02d}{asset['ext']}"
            if _download(asset["url"], dest):
                assets.append({**asset, "path": dest})
                print(f"    beat {i + 1}/{len(beats)}  '{query}' -> "
                      f"{'photo' if asset['is_image'] else 'video'} (stock)")
                continue

        assets.append(None)
        print(f"    beat {i + 1}/{len(beats)}  '{query}' -> koi clip nahi, text card lagega")

    found = sum(1 for a in assets if a)
    print(f"    {found}/{len(beats)} clips mile")
    return assets
