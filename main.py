"""Hinglish viral-video factory: trend -> script -> voice -> video -> YouTube.

This is the hands-on entry point, with an approval gate before rendering and
another before upload. For the unattended daily version, see agent.py.

Usage:
  python main.py                       pick a topic, approve at each gate
  python main.py --auto                take the top topic, still ask before upload
  python main.py --topic "..."         use your own topic
  python main.py --source niche        AI/tech news only, instead of worldwide
  python main.py --format shorts       only build the vertical Shorts video
  python main.py --yes                 skip approval gates (fully unattended)
  python main.py --rebuild output/xyz  re-render after editing script.json
"""
import argparse
import json
import re
import subprocess
import sys
import zlib
from datetime import datetime
from pathlib import Path

import animate3d
import config
import research
import script_writer
import thumbnail as thumbnail_mod
import trends
import video as video_mod
import visuals
import voice


def slugify(text: str, limit: int = 45, fallback: str = "") -> str:
    """ASCII folder name. Devanagari titles leave nothing behind, so the
    English source headline is used instead -- otherwise every folder would be
    called "video" and the output directory becomes unreadable."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    if len(slug) < 4 and fallback:
        slug = re.sub(r"[^a-zA-Z0-9]+", "-", fallback.lower()).strip("-")
    return (slug[:limit].rstrip("-")) or "video"


def ask(question: str, default_yes: bool = True) -> bool:
    suffix = "[Y/n]" if default_yes else "[y/N]"
    answer = input(f"\n>>> {question} {suffix}: ").strip().lower()
    if not answer:
        return default_yes
    return answer in ("y", "yes", "haan", "ha", "h")


def open_in_explorer(path: Path) -> None:
    try:
        subprocess.Popen(["explorer", "/select,", str(path)])
    except Exception:
        pass


def build_description(script: dict, chapters: list) -> str:
    parts = [script.get("description", "").strip(), ""]
    if chapters:
        parts.append("Timestamps:")
        parts += chapters
        parts.append("")
    if script.get("sources"):
        parts.append("Sources:")
        parts += [f"- {s}" for s in script["sources"]]
        parts.append("")
    parts.append(" ".join(f"#{t.replace(' ', '')}" for t in script.get("tags", [])[:8]))
    return "\n".join(parts).strip()


def chapter_list(narration: dict) -> list:
    chapters, elapsed = [], 0.0
    for i, beat in enumerate(narration["beats"]):
        if i == 0 or elapsed > 30:
            label = " ".join(beat["text"].split()[:5]).rstrip(".,")
            chapters.append(f"{int(elapsed // 60):02d}:{int(elapsed % 60):02d} {label}")
        elapsed += beat["duration"]
    return chapters[:10]


def fetch_visuals(script: dict, narration: dict, work_dir: Path, vertical: bool,
                  label: str) -> list:
    """Pictures for the beats: 3D characters if asked for, else stock."""
    category = script.get("category", "general")
    if config.VISUAL_STYLE == "3d":
        # A stable seed per title, so a re-render reproduces the same cast and
        # room while the next video gets a different pair. Python's own hash()
        # is salted per process and would not.
        seed = zlib.crc32(script.get("title", label).encode("utf-8"))
        try:
            return animate3d.fetch_visuals(
                narration["beats"], work_dir, vertical, label, category,
                audio=narration["audio"], seed=seed)
        except Exception as exc:
            # Deliberately every exception, not a named few. The point of this
            # branch is that a stock video still publishes, and that argument
            # does not care what went wrong. It was a four-exception tuple
            # until a TypeError in the 3D module's own summary print -- raised
            # after every scene had rendered -- escaped it and destroyed a
            # finished video on a live scheduled run.
            print(f"    [!] 3D render nahi hua ({type(exc).__name__}: {exc}); "
                  f"stock par gir raha hoon")
    return visuals.fetch_visuals(narration["beats"], work_dir, vertical, label,
                                 category)


def make_video(script: dict, work_dir: Path, vertical: bool, label: str,
               burn_subs: bool) -> tuple:
    beats = script["shorts_beats"] if vertical else script["long_beats"]
    narration = voice.narrate(beats, work_dir, label)
    assets = fetch_visuals(script, narration, work_dir, vertical, label)
    path = video_mod.build(narration, assets, work_dir, vertical, label, burn_subs)
    return path, narration, assets


def run(args) -> None:
    config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ---------- pick a topic ----------
    if args.topic:
        topic = {"title": args.topic, "source": "manual", "related": [], "links": [],
                 "category": args.category or "general"}
        print(f"[1/7] Manual topic: {args.topic}")
    elif args.source == "niche":
        topic = trends.choose_topic(trends.fetch_trending(), auto=args.auto or args.yes)
        topic.setdefault("category", "tech")
    else:
        import viral
        topic = viral.choose_topic(viral.fetch_viral(limit=12),
                                   auto=args.auto or args.yes)

    facts = research.gather_facts(topic)
    # Thin sources -> fewer beats. Asking for length the facts can't fill
    # is what produces filler and repetition.
    script = script_writer.write_script(
        facts, n_long_beats=research.fact_depth(facts),
        category=args.category or topic.get("category", "general"))

    work_dir = config.OUTPUT_DIR / f"{datetime.now():%Y-%m-%d_%H%M}_{slugify(script['title'])}"
    work_dir.mkdir(parents=True, exist_ok=True)

    (work_dir / "script.json").write_text(
        json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")
    (work_dir / "script.txt").write_text(
        script_writer.script_as_text(script), encoding="utf-8")

    # ---------- APPROVAL GATE 1: the script ----------
    print("\n" + "=" * 70)
    print(script_writer.script_as_text(script))
    print("=" * 70)
    print(f"\nScript saved: {work_dir / 'script.txt'}")

    if not args.yes:
        print("\nOptions:  y = aage badho   e = script.json edit karke aage badho   n = cancel")
        choice = input(">>> Script theek hai? [Y/e/n]: ").strip().lower()
        if choice == "n":
            print("Cancel kar diya. Files yahan hain:", work_dir)
            return
        if choice == "e":
            open_in_explorer(work_dir / "script.json")
            input("script.json edit kar ke save karo, phir Enter dabao... ")
            script = json.loads((work_dir / "script.json").read_text(encoding="utf-8"))

    # ---------- render ----------
    outputs = {}
    if args.format in ("both", "long"):
        outputs["long"] = make_video(script, work_dir, False, "long", burn_subs=False)
    if args.format in ("both", "shorts"):
        outputs["shorts"] = make_video(script, work_dir, True, "shorts", burn_subs=True)

    primary_key = "long" if "long" in outputs else "shorts"
    primary_path, primary_narration, primary_assets = outputs[primary_key]

    thumb = thumbnail_mod.make_thumbnail(
        script.get("thumbnail_text", script["title"]), primary_assets,
        work_dir / "thumbnail.jpg")

    chapters = chapter_list(primary_narration) if primary_key == "long" else []
    description = build_description(script, chapters)
    (work_dir / "title_and_description.txt").write_text(
        f"{script['title']}\n\n{description}\n\nTAGS: {', '.join(script.get('tags', []))}",
        encoding="utf-8")

    print("\n" + "=" * 70)
    print("VIDEO READY")
    print("=" * 70)
    print(f"Folder    : {work_dir}")
    for key, (path, narration, _) in outputs.items():
        print(f"{key:<10}: {path.name}  ({narration['total'] / 60:.1f} min)")
    print(f"Thumbnail : {thumb.name}")
    print(f"\nTitle     : {script['title']}")
    print(f"Tags      : {', '.join(script.get('tags', [])[:10])}")

    # ---------- APPROVAL GATE 2: upload ----------
    if args.no_upload:
        print("\n--no-upload diya tha, upload skip. Manually upload kar sakte ho.")
        open_in_explorer(primary_path)
        return

    if not args.yes:
        open_in_explorer(primary_path)
        print("\nVideo folder khul gaya hai. Dekh lo, phir batao.")
        if not ask(f"YouTube par upload karein? (privacy: {config.UPLOAD_PRIVACY})",
                   default_yes=False):
            print("Upload skip kiya. Files folder mein hain.")
            return

    import youtube_upload
    url = youtube_upload.upload(
        primary_path, script["title"], description,
        script.get("tags", []), thumb)
    (work_dir / "uploaded.txt").write_text(url, encoding="utf-8")

    if "shorts" in outputs and primary_key == "long":
        if args.yes or ask("Shorts version bhi upload karein?", default_yes=True):
            shorts_path = outputs["shorts"][0]
            shorts_title = (script["title"][:85] + " #shorts")
            youtube_upload.upload(shorts_path, shorts_title, description,
                                  script.get("tags", []) + ["shorts"], thumb)

    print("\nHo gaya.")


def rebuild(folder: Path, args) -> None:
    """Re-render from an edited script.json without re-running research."""
    script = json.loads((folder / "script.json").read_text(encoding="utf-8"))
    print(f"[rebuild] {script['title']}")
    if args.format in ("both", "long"):
        make_video(script, folder, False, "long", burn_subs=False)
    if args.format in ("both", "shorts"):
        make_video(script, folder, True, "shorts", burn_subs=True)
    print(f"\nRebuild done: {folder}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hinglish viral-video factory (roz auto chalane ke liye: agent.py)")
    parser.add_argument("--auto", action="store_true", help="top trending topic auto-pick")
    parser.add_argument("--topic", help="apna topic do")
    parser.add_argument("--source", choices=["viral", "niche"], default="viral",
                        help="viral = duniya bhar ke trending topics (default), "
                             "niche = sirf AI/tech news")
    parser.add_argument("--category", choices=sorted(script_writer.CATEGORY_ANGLES),
                        help="script ka tone force karo (warna auto-detect)")
    parser.add_argument("--format", choices=["both", "long", "shorts"], default="both")
    parser.add_argument("--yes", action="store_true",
                        help="koi approval mat maango (fully unattended)")
    parser.add_argument("--no-upload", action="store_true", help="sirf video banao")
    parser.add_argument("--rebuild", help="output folder se dobara render karo")
    args = parser.parse_args()

    try:
        if args.rebuild:
            rebuild(Path(args.rebuild).resolve(), args)
        else:
            run(args)
    except KeyboardInterrupt:
        print("\nRoka gaya.")
        sys.exit(1)
    except RuntimeError as exc:
        # Expected failures (API rate limits, unusable model output) report
        # themselves; a traceback here would only bury the message.
        print(f"\n[X] {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
