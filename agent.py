"""Unattended daily runner: find a viral story, build the video, publish it.

This is `main.py` with every human gate removed and the failure handling that
absence demands. Nobody is watching at 6 AM, so the rules are different:

  - Never repeat a story (history.py).
  - Never publish a story the safety filter flagged (viral.py).
  - If a candidate cannot be researched or rendered, drop it and try the next
    one rather than failing the run. Trending stories routinely turn out to
    have no readable sources behind them.
  - Write everything to agent.log, because the scheduler discards stdout.

Run it by hand first:  python agent.py --dry-run
Then schedule it:      powershell -File setup_schedule.ps1
"""
import argparse
import json
import socket
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

import config
import history
import main as pipeline
import research
import script_writer
import thumbnail as thumbnail_mod
import viral

# Below this, the sources were too thin to write anything factual from and the
# script model would have to invent filler. research.fact_depth returns 5 in
# that case, which is not enough for a watchable long-form video.
MIN_ARTICLES = 1
MIN_FACT_DEPTH = 7


class NetworkDown(Exception):
    """The internet went away. Not the topic's fault, so it must not count."""


def online(host: str = "news.google.com") -> bool:
    try:
        socket.getaddrinfo(host, 443)
        return True
    except OSError:
        return False


def wait_for_network(max_wait: int = 900, step: int = 30) -> bool:
    """Block until DNS answers again.

    A home connection dropping for a few minutes should cost the run a few
    minutes, not the whole day. Without this a single outage burns every topic
    attempt in seconds -- each one reported as 'thin sources', which is the
    wrong diagnosis entirely.
    """
    waited = 0
    while waited < max_wait:
        time.sleep(step)
        waited += step
        if online():
            log(f"  network wapas aa gaya ({waited}s baad)")
            return True
        log(f"  network abhi bhi down ({waited}s)...")
    return False


def is_network_error(exc: Exception) -> bool:
    names = {"ConnectionError", "ConnectTimeout", "ReadTimeout", "Timeout",
             "ConnectionResetError", "gaierror", "NameResolutionError",
             "MaxRetryError", "SSLError", "ChunkedEncodingError"}
    seen, current = set(), exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if type(current).__name__ in names:
            return True
        current = getattr(current, "__cause__", None) or getattr(current, "__context__", None)
    return False


def log(message: str, echo: bool = True) -> None:
    stamped = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {message}"
    if echo:
        print(message, flush=True)
    try:
        with open(config.LOG_FILE, "a", encoding="utf-8") as handle:
            handle.write(stamped + "\n")
    except OSError:
        pass


def build_one(topic: dict, args) -> dict:
    """Research, write, render and upload a single topic.

    Returns a result dict. Raises only on genuinely unexpected errors; the
    predictable ways a topic fails are reported as {"ok": False}.
    """
    log(f"  topic     : {topic['title']}")
    log(f"  signal    : {viral.describe(topic)}")

    facts = research.gather_facts(topic)
    depth = research.fact_depth(facts)
    if len(facts["articles"]) < MIN_ARTICLES or depth < MIN_FACT_DEPTH:
        # research.py swallows fetch errors by design, so an outage arrives here
        # disguised as an empty result. Check before blaming the sources.
        if not online():
            raise NetworkDown("research ke dauraan internet chala gaya")
        return {"ok": False,
                "reason": f"sources patle hain ({len(facts['articles'])} articles, "
                          f"depth {depth}) — is topic par factual script nahi banegi"}

    script = script_writer.write_script(facts, n_long_beats=depth,
                                        category=topic.get("category", "general"))

    work_dir = config.OUTPUT_DIR / (
        f"{datetime.now():%Y-%m-%d_%H%M}_{pipeline.slugify(script['title'])}")
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "script.json").write_text(
        json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    (work_dir / "script.txt").write_text(
        script_writer.script_as_text(script), encoding="utf-8")
    (work_dir / "topic.json").write_text(
        json.dumps({k: v for k, v in topic.items() if k != "keys"},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    log(f"  title     : {script['title']}")
    log(f"  folder    : {work_dir.name}")

    outputs = {}
    if args.format in ("both", "long"):
        outputs["long"] = pipeline.make_video(script, work_dir, False, "long",
                                              burn_subs=False)
    if args.format in ("both", "shorts"):
        outputs["shorts"] = pipeline.make_video(script, work_dir, True, "shorts",
                                                burn_subs=True)

    primary_key = "long" if "long" in outputs else "shorts"
    primary_path, primary_narration, primary_assets = outputs[primary_key]

    thumb = thumbnail_mod.make_thumbnail(
        script.get("thumbnail_text", script["title"]), primary_assets,
        work_dir / "thumbnail.jpg")

    chapters = pipeline.chapter_list(primary_narration) if primary_key == "long" else []
    description = pipeline.build_description(script, chapters)
    (work_dir / "title_and_description.txt").write_text(
        f"{script['title']}\n\n{description}\n\nTAGS: {', '.join(script.get('tags', []))}",
        encoding="utf-8")

    log(f"  rendered  : " + ", ".join(
        f"{k} {v[1]['total'] / 60:.1f}min" for k, v in outputs.items()))

    url = ""
    if args.no_upload:
        log("  upload    : skipped (--no-upload)")
    else:
        import youtube_upload
        privacy = args.privacy or config.UPLOAD_PRIVACY
        url = youtube_upload.upload(
            primary_path, script["title"], description, script.get("tags", []),
            thumb, privacy=privacy,
            category=youtube_upload.category_id(topic.get("category", "")))
        (work_dir / "uploaded.txt").write_text(url, encoding="utf-8")
        log(f"  uploaded  : {url}  ({privacy})")

        if "shorts" in outputs and primary_key == "long":
            try:
                shorts_url = youtube_upload.upload(
                    outputs["shorts"][0], script["title"][:85] + " #shorts",
                    description, script.get("tags", []) + ["shorts"], thumb,
                    privacy=privacy,
                    category=youtube_upload.category_id(topic.get("category", "")))
                log(f"  shorts    : {shorts_url}")
            except Exception as exc:
                # The long-form video is already live; losing the Short is not
                # a reason to mark the whole run failed.
                log(f"  [!] shorts upload fail: {type(exc).__name__}: {exc}")

    # Recorded even when upload was skipped -- the work was done and the topic
    # should not come back around tomorrow.
    history.record(topic, script, work_dir, url)
    return {"ok": True, "title": script["title"], "folder": work_dir, "url": url}


def run(args) -> int:
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    log("=" * 68, echo=False)
    log(f"AGENT RUN start  (privacy={args.privacy or config.UPLOAD_PRIVACY}, "
        f"format={args.format}, upload={not args.no_upload})")

    topics = viral.fetch_viral(limit=25)
    if not topics:
        log("[X] Koi viral topic nahi mila. Network ya feeds down.")
        return 1

    topics = history.filter_new(topics)
    if not topics:
        log("[X] Sab topics pehle cover ho chuke. Aaj kuch naya nahi.")
        return 1

    log(f"  {len(topics)} naye candidates. Top 5:")
    for i, topic in enumerate(topics[:5], 1):
        log(f"    {i}. [{topic['category']:<13}] {topic['title'][:70]}")

    if args.dry_run:
        log("\n--dry-run: yahin ruk raha hoon, koi video nahi banegi.")
        return 0

    published, attempts = [], 0
    for topic in topics:
        if len(published) >= args.count or attempts >= config.MAX_TOPIC_ATTEMPTS:
            break
        attempts += 1
        log(f"\n[attempt {attempts}/{config.MAX_TOPIC_ATTEMPTS}]")

        result = None
        # A dropped connection is not this topic's fault. Wait it out and try
        # the same topic again rather than spending the remaining attempts on
        # topics that will fail identically.
        for retry in range(2):
            try:
                result = build_one(topic, args)
                break
            except Exception as exc:
                if isinstance(exc, NetworkDown) or is_network_error(exc):
                    log(f"  [!] network problem: {type(exc).__name__}: "
                        f"{str(exc)[:120]}")
                    if retry == 0 and wait_for_network():
                        log("  wahi topic dobara try kar raha hoon")
                        continue
                    log("  [X] network wapas nahi aaya, run rok raha hoon")
                    log("\n" + "-" * 68)
                    log("FAIL: internet down tha. Baad mein dobara chalao.")
                    return 1
                log(f"  [X] {type(exc).__name__}: {exc}")
                log(traceback.format_exc(), echo=False)
                break

        if result is None:
            continue
        if result["ok"]:
            published.append(result)
        else:
            log(f"  [skip] {result['reason']}")

    log("\n" + "-" * 68)
    if published:
        log(f"DONE: {len(published)} video(s) publish/render hui")
        for result in published:
            log(f"  {result['title']}")
            log(f"    {result['url'] or result['folder']}")
        return 0

    log("FAIL: aaj koi video nahi bani. agent.log dekho.")
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Autonomous viral-video agent (scheduler ke liye)")
    parser.add_argument("--dry-run", action="store_true",
                        help="sirf topics dikhao, video mat banao")
    parser.add_argument("--count", type=int, default=config.VIDEOS_PER_RUN,
                        help="ek run mein kitni videos")
    parser.add_argument("--format", choices=["both", "long", "shorts"], default="both")
    parser.add_argument("--no-upload", action="store_true",
                        help="video banao par upload mat karo")
    parser.add_argument("--privacy", choices=["private", "unlisted", "public"],
                        help="sirf is run ke liye privacy override karo; "
                             ".env ka UPLOAD_PRIVACY waise ka waisa rehta hai")
    parser.add_argument("--history", action="store_true",
                        help="ab tak kya cover hua, wo dikhao aur exit")
    args = parser.parse_args()

    if args.history:
        print(history.summary())
        return

    try:
        sys.exit(run(args))
    except KeyboardInterrupt:
        log("\nRoka gaya.")
        sys.exit(1)


if __name__ == "__main__":
    main()
