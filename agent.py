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
import random
import shutil
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


def story_writer_kinds() -> list:
    """Imported lazily so --help works even if a provider key is missing."""
    import story_writer

    return list(story_writer.KINDS)


class NetworkDown(Exception):
    """The internet went away. Not the topic's fault, so it must not count."""


def is_upload_limit(exc: Exception) -> bool:
    """YouTube's per-channel daily video cap, distinct from the API quota.

    Retrying cannot help: the cap is on the channel for the whole day, so a
    fresh video would only burn another ten minutes of rendering and fail at
    the same line. The run stops instead, leaving finished files on disk.
    """
    text = f"{type(exc).__name__} {exc}"
    return ("uploadLimitExceeded" in text
            or "exceeded the number of videos" in text)


class UploadLimit(Exception):
    """Channel cannot accept more uploads today."""


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


def tidy(work_dir: Path) -> None:
    """Drop what a finished run no longer needs.

    The silent renders and per-beat parts exist only to be concatenated; once
    the final mp4s are written they are dead weight, and on a daily schedule
    dead weight is the thing that fills a disk.
    """
    if not config.DELETE_INTERMEDIATES:
        return

    freed = 0
    for name in ("silent_long.mp4", "silent_shorts.mp4"):
        part = work_dir / name
        if part.exists():
            freed += part.stat().st_size
            part.unlink(missing_ok=True)

    for folder in ("clips_long", "clips_shorts", "audio_long", "audio_shorts",
                   "scene3d_long", "scene3d_shorts"):
        target = work_dir / folder
        if target.is_dir():
            freed += sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
            shutil.rmtree(target, ignore_errors=True)

    if freed:
        log(f"  cleanup   : {freed / 1024 / 1024:.0f} MB intermediates hataye")


def prune_old_outputs() -> None:
    """Age out whole run folders, keeping the script and the upload record."""
    days = config.KEEP_OUTPUT_DAYS
    if days <= 0 or not config.OUTPUT_DIR.exists():
        return

    cutoff = time.time() - days * 86400
    removed, freed = 0, 0
    for folder in config.OUTPUT_DIR.iterdir():
        if not folder.is_dir() or folder.stat().st_mtime >= cutoff:
            continue
        freed += sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())
        shutil.rmtree(folder, ignore_errors=True)
        removed += 1
    if removed:
        log(f"  {removed} folders {days} din se purane the, hata diye "
            f"({freed / 1024 / 1024:.0f} MB)")


def log(message: str, echo: bool = True) -> None:
    stamped = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {message}"
    if echo:
        print(message, flush=True)
    try:
        with open(config.LOG_FILE, "a", encoding="utf-8") as handle:
            handle.write(stamped + "\n")
    except OSError:
        pass


def build_animation(args, kind: str) -> dict:
    """Original content -- jokes, facts, riddles, a short story -- then video.

    Half the news pipeline is skipped because there is nothing to research:
    the content is written, not reported. What survives is everything that
    decides whether the video is watchable: Devanagari, length, visuals, voice.
    """
    import story_writer

    script = story_writer.write_story(kind)

    # A joke set is only fresh if it is not the joke set from yesterday.
    fake_topic = {"title": script["title"], "category": script["category"],
                  "related": [], "links": []}
    duplicate, previous = history.is_duplicate(fake_topic)
    if duplicate:
        return {"ok": False, "reason": f"bahut milta-julta pehle bana tha: {previous[:50]}"}

    work_dir = config.OUTPUT_DIR / (
        f"{datetime.now():%Y-%m-%d_%H%M}_{kind}_"
        f"{pipeline.slugify(script['title'], fallback=kind)}")
    work_dir.mkdir(parents=True, exist_ok=True)
    (work_dir / "script.json").write_text(
        json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    (work_dir / "script.txt").write_text(
        story_writer.story_as_text(script), encoding="utf-8")
    log(f"  title     : {script['title']}")
    log(f"  folder    : {work_dir.name}")

    return _render_and_upload(script, fake_topic, work_dir, args)


def build_one(topic: dict, args) -> dict:
    """Research, write, render and upload a single topic.

    Returns a result dict. Raises only on genuinely unexpected errors; the
    predictable ways a topic fails are reported as {"ok": False}.
    """
    log(f"  topic     : {topic['title']}")
    log(f"  signal    : {viral.describe(topic)}")

    facts = research.gather_facts(topic)
    # Richness judges the topic; depth decides the script length. They are
    # measured separately so the runtime cap cannot reject good topics.
    richness = research.source_richness(facts)
    depth = research.fact_depth(facts)
    if len(facts["articles"]) < MIN_ARTICLES or richness < MIN_FACT_DEPTH:
        # research.py swallows fetch errors by design, so an outage arrives here
        # disguised as an empty result. Check before blaming the sources.
        if not online():
            raise NetworkDown("research ke dauraan internet chala gaya")
        return {"ok": False,
                "reason": f"sources patle hain ({len(facts['articles'])} articles, "
                          f"richness {richness}) â€” is topic par factual script nahi banegi"}

    script = script_writer.write_script(facts, n_long_beats=depth,
                                        category=topic.get("category", "general"))

    work_dir = config.OUTPUT_DIR / (
        f"{datetime.now():%Y-%m-%d_%H%M}_"
        f"{pipeline.slugify(script['title'], fallback=topic.get('title', ''))}")
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

    return _render_and_upload(script, topic, work_dir, args)


def _render_and_upload(script: dict, topic: dict, work_dir, args) -> dict:
    """Voice, visuals, video, thumbnail, upload, history. Shared by both modes:
    once a script exists, nothing downstream cares where it came from."""
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
        try:
            url = youtube_upload.upload(
                primary_path, script["title"], description, script.get("tags", []),
                thumb, privacy=privacy,
                category=youtube_upload.category_id(topic.get("category", "")))
        except Exception as exc:
            if is_upload_limit(exc):
                log("  [X] YouTube ki daily upload limit lag gayi. Video bani "
                    f"hui hai: {work_dir}")
                raise UploadLimit(str(exc)[:160]) from exc
            raise
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
    tidy(work_dir)
    return {"ok": True, "title": script["title"], "folder": work_dir, "url": url}


def run_animation(args) -> int:
    """Make `args.count` original videos. No trending discovery at all.

    Kinds rotate rather than repeat: five joke videos in one morning would be
    five videos of the same thing, and the duplicate guard would reject most
    of them anyway.
    """
    published, attempts = [], 0
    budget = args.count + config.MAX_TOPIC_ATTEMPTS
    kinds = list(config.ANIMATION_KINDS)

    while len(published) < args.count and attempts < budget:
        kind = args.kind or kinds[len(published) % len(kinds)]
        attempts += 1
        log(f"\n[video {len(published) + 1}/{args.count}  "
            f"attempt {attempts}/{budget}  kind={kind}]")
        try:
            result = build_animation(args, kind)
        except UploadLimit as exc:
            log(f"  [X] {exc}")
            log("  Baaki videos nahi banaunga — wo bhi isi limit par rukengi.")
            log("  Limit roz reset hoti hai. Kal ka run normal chalega.")
            return _report(published)
        except Exception as exc:
            if isinstance(exc, NetworkDown) or is_network_error(exc):
                log(f"  [!] network problem: {type(exc).__name__}")
                if wait_for_network():
                    continue
                log("\n" + "-" * 68)
                log("FAIL: internet down tha.")
                return _report(published)
            log(f"  [X] {type(exc).__name__}: {exc}")
            log(traceback.format_exc(), echo=False)
            continue

        if result["ok"]:
            published.append(result)
        else:
            log(f"  [skip] {result['reason']}")

    return _report(published)


def run(args) -> int:
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    prune_old_outputs()

    if config.CONTENT_MODE == "animation":
        log(f"AGENT RUN start  (animation, {args.count} videos, "
            f"privacy={args.privacy or config.UPLOAD_PRIVACY})")
        return run_animation(args)
    log("=" * 68, echo=False)
    log(f"AGENT RUN start  (privacy={args.privacy or config.UPLOAD_PRIVACY}, "
        f"format={args.format}, upload={not args.no_upload})")

    if args.topic:
        # A named topic still goes through research and every guard; only the
        # discovery step is replaced.
        topics = [{"title": args.topic, "source": "manual", "related": [],
                   "links": [], "articles": [],
                   "category": args.category or "general"}]
        log(f"  manual topic: {args.topic}")
    else:
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
            except UploadLimit as exc:
                log(f"  [X] {exc}")
                log("  Aage ke topics nahi banaunga — wo bhi isi limit par rukenge.")
                return _report(published)
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

    return _report(published)


def _report(published: list) -> int:
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
    parser.add_argument("--topic", help="apna topic do, trending discovery skip karo")
    parser.add_argument("--kind", choices=sorted(story_writer_kinds()),
                        help="animation mode: jokes / facts / riddles / stories "
                             "(na do to roz badal-badal kar chunega)")
    parser.add_argument("--category", help="topic ki category (script tone + "
                                           "visuals ismein se chunte hain)")
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
