"""Shared configuration + tool discovery for the video pipeline."""
import glob
import os
import shutil
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

# --- API keys -------------------------------------------------------------
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()

# Script writers are tried in order: Gemini, then Groq, then NVIDIA.
#
# Gemini leads on the one thing that decides whether a video is usable at all:
# it holds Hinglish. In a head-to-head on the same prompt, every Gemini flash
# model kept all beats in Hinglish, while NVIDIA's gpt-oss-20b wrote beats 4
# to 9 in plain English -- unreadable for a Hindi TTS voice.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash").strip()

# Groq's free tier is 100,000 tokens/day, roughly five videos. NVIDIA NIM
# backs it up so a dry quota never costs the whole day.
NVIDIA_API_KEY = os.getenv("NVIDIA_API_KEY", "").strip()
NVIDIA_MODEL = os.getenv("NVIDIA_MODEL", "openai/gpt-oss-20b").strip()
YOUTUBE_CLIENT_ID = os.getenv("YOUTUBE_CLIENT_ID", "").strip()
YOUTUBE_CLIENT_SECRET = os.getenv("YOUTUBE_CLIENT_SECRET", "").strip()
UPLOAD_PRIVACY = os.getenv("UPLOAD_PRIVACY", "private").strip().lower()

# --- Voice ----------------------------------------------------------------
# "edge"   Microsoft cloud, free, unlimited, production-quality Hindi (default)
# "kokoro" local Kokoro-82M, runs offline on CPU, Hindi graded C by its authors
TTS_ENGINE = os.getenv("TTS_ENGINE", "edge").strip().lower()

# hi-IN-MadhurNeural (male) / hi-IN-SwaraNeural (female) handle Hinglish well.
VOICE = os.getenv("VOICE", "hi-IN-MadhurNeural").strip()
VOICE_RATE = os.getenv("VOICE_RATE", "+8%").strip()

# Kokoro Hindi voices: hm_omega, hm_psi (male) | hf_alpha, hf_beta (female)
KOKORO_VOICE = os.getenv("KOKORO_VOICE", "hm_omega").strip()
KOKORO_SPEED = float(os.getenv("KOKORO_SPEED", "1.0"))

# --- Video ----------------------------------------------------------------
FPS = int(os.getenv("FPS", "30"))
LANDSCAPE = (1920, 1080)
VERTICAL = (1080, 1920)
MUSIC_VOLUME_DB = float(os.getenv("MUSIC_VOLUME_DB", "-22"))

# --- Paths ----------------------------------------------------------------
_out = Path(os.getenv("OUTPUT_DIRECTORY", str(ROOT / "output"))).expanduser()
# Always absolute — relative output paths leak into ffmpeg concat lists.
OUTPUT_DIR = _out if _out.is_absolute() else (ROOT / _out).resolve()
MUSIC_DIR = ROOT / "music"
TOKEN_FILE = ROOT / ".youtube_token.json"

# Topic niche used when searching for trends (trends.py, --source niche).
NICHE_QUERIES = [
    "artificial intelligence",
    "OpenAI OR Anthropic OR Google DeepMind",
    "AI model launch",
    "India technology AI",
]


def _csv(name: str, default: str) -> list:
    return [p.strip() for p in os.getenv(name, default).split(",") if p.strip()]


# --- Worldwide viral discovery (viral.py, --source viral) -----------------
# Countries whose Google Trends lists are read. A story trending in many of
# these at once is the signal we actually rank on, so breadth matters more
# than any single country -- but every geo is one more HTTP request.
VIRAL_GEOS = _csv("VIRAL_GEOS", "US,IN,GB,CA,AU,DE,BR,JP,ZA,NG")

# Google News sections pulled for editorial corroboration.
NEWS_SECTIONS_ENABLED = _csv(
    "NEWS_SECTIONS", "WORLD,BUSINESS,TECHNOLOGY,ENTERTAINMENT,SPORTS,SCIENCE")

# Off by default: an unattended channel should not publish explainers on
# shootings, court cases or elections. See BLOCKED in viral.py.
ALLOW_SENSITIVE = os.getenv("ALLOW_SENSITIVE", "false").strip().lower() == "true"

# Categories the agent is allowed to make videos about. Empty list = all.
ALLOWED_CATEGORIES = _csv("ALLOWED_CATEGORIES", "")

# --- Visuals ----------------------------------------------------------------
# Generate each beat's visual instead of searching stock. Stock cannot
# illustrate a specific story -- a beat about FIFA's president facing revolt
# returned footage of a man wading in the sea. Set false to go back to Pexels.
USE_AI_VISUALS = os.getenv("USE_AI_VISUALS", "true").strip().lower() == "true"

# --- Length -----------------------------------------------------------------
# Longer is not better: a padded four-minute video loses viewers a tight
# three-minute one keeps. The narration runs at roughly 145 words per minute
# and each beat is written at 55-80 words, so the beat cap follows from the
# minute cap rather than being guessed separately.
MAX_VIDEO_MINUTES = float(os.getenv("MAX_VIDEO_MINUTES", "3"))
WORDS_PER_MINUTE = 145
WORDS_PER_BEAT = 65
MAX_LONG_BEATS = max(4, int(MAX_VIDEO_MINUTES * WORDS_PER_MINUTE / WORDS_PER_BEAT))

# --- Autonomous agent (agent.py) ------------------------------------------
# How many videos one scheduled run may publish.
VIDEOS_PER_RUN = int(os.getenv("VIDEOS_PER_RUN", "1"))
# Candidates to try before giving up when topics fail research or dedupe.
MAX_TOPIC_ATTEMPTS = int(os.getenv("MAX_TOPIC_ATTEMPTS", "4"))
# Days a covered topic stays in the duplicate guard.
HISTORY_DAYS = int(os.getenv("HISTORY_DAYS", "45"))
HISTORY_FILE = ROOT / "history.json"
LOG_FILE = ROOT / "agent.log"

# Housekeeping. A daily job that never deletes anything eventually fills the
# disk -- slowly on AI visuals (~23 MB a video), fast on stock clips (~530 MB).
# Intermediates go as soon as a run finishes; whole folders age out.
KEEP_OUTPUT_DAYS = int(os.getenv("KEEP_OUTPUT_DAYS", "30"))
DELETE_INTERMEDIATES = os.getenv("DELETE_INTERMEDIATES", "true").strip().lower() == "true"


def _find_tool(name: str) -> str:
    """Locate ffmpeg/ffprobe even when PATH has not been refreshed after install."""
    found = shutil.which(name)
    if found:
        return found

    local = os.environ.get("LOCALAPPDATA", "")
    candidates = [Path(local) / "Microsoft" / "WinGet" / "Links" / f"{name}.exe"]
    pattern = str(Path(local) / "Microsoft" / "WinGet" / "Packages" / "Gyan.FFmpeg*" / "**" / f"{name}.exe")
    candidates += [Path(p) for p in glob.glob(pattern, recursive=True)]
    candidates += [
        Path(r"C:\ffmpeg\bin") / f"{name}.exe",
        Path(r"C:\Program Files\ffmpeg\bin") / f"{name}.exe",
    ]

    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    raise RuntimeError(
        f"'{name}' nahi mila. FFmpeg install karo ya PATH mein add karo:\n"
        f"  winget install --id Gyan.FFmpeg -e"
    )


FFMPEG = _find_tool("ffmpeg")
FFPROBE = _find_tool("ffprobe")


def require_key(name: str, value: str, url: str) -> str:
    if not value:
        raise SystemExit(
            f"\n[X] {name} missing.\n"
            f"    Free key yahan se lo: {url}\n"
            f"    Phir .env file mein daalo (.env.example dekho).\n"
        )
    return value
