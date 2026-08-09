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
# Pitch shift, e.g. "+25Hz". edge-tts has no cartoon voice for Hindi -- there
# are only Madhur and Swara -- so a lighter, faster read is how you get one.
VOICE_PITCH = os.getenv("VOICE_PITCH", "+0Hz").strip()

# The second character. Two people on screen sharing one voice never reads as a
# conversation no matter how good the animation is, and edge-tts offers exactly
# two Hindi voices -- which is exactly how many a two-hander needs.
VOICE_B = os.getenv("VOICE_B", "hi-IN-SwaraNeural").strip()
VOICE_B_RATE = os.getenv("VOICE_B_RATE", VOICE_RATE).strip()
VOICE_B_PITCH = os.getenv("VOICE_B_PITCH", "+0Hz").strip()

# Kokoro Hindi voices: hm_omega, hm_psi (male) | hf_alpha, hf_beta (female)
KOKORO_VOICE = os.getenv("KOKORO_VOICE", "hm_omega").strip()
KOKORO_SPEED = float(os.getenv("KOKORO_SPEED", "1.0"))

# --- ElevenLabs ------------------------------------------------------------
# Best Hindi of anything tried here, but billed per character: the free tier
# is 10,000 a month, about five videos. voice.py falls back to edge-tts the
# moment the credits run out, so a dry account slows the channel down rather
# than stopping it.
ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY", "").strip()
ELEVEN_VOICE = os.getenv("ELEVEN_VOICE", "EXAVITQu4vr4xnSDxMaL").strip()      # Sarah
ELEVEN_VOICE_SHORTS = os.getenv("ELEVEN_VOICE_SHORTS",
                                "TX3LPaxmHKxFdv7VOQHJ").strip()               # Liam
# The second character, when a script is written as dialogue. Distinct from
# ELEVEN_VOICE_SHORTS, which picks a voice by video format rather than by who
# is speaking -- the two questions are unrelated and were answered separately.
ELEVEN_VOICE_B = os.getenv("ELEVEN_VOICE_B", "TX3LPaxmHKxFdv7VOQHJ").strip()  # Liam
# Low stability + high style = performance rather than narration.
ELEVEN_STABILITY = float(os.getenv("ELEVEN_STABILITY", "0.35"))
ELEVEN_STYLE = float(os.getenv("ELEVEN_STYLE", "0.70"))

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
# Generated stills instead of stock video. OFF by default and it should stay
# off: a still with a slow pan is not a video, and the channel owner has said
# so twice. The earlier argument for turning it on -- that stock never matched
# the narration -- turned out to be a truncation bug in visuals._clean_query,
# not a limit of the stock library.
#
# Only worth enabling for a subject stock genuinely does not cover.
USE_AI_VISUALS = os.getenv("USE_AI_VISUALS", "false").strip().lower() == "true"

# "photo"     generated stills that look like photography (default)
# "animation" illustrated frames in one consistent style
# "3d"        real 3D cartoon characters acting the beats out (scene3d/)
#
# Animation only works for subjects whose scenes do not need a recurring
# character. Holding a character across scenes was tested twice and failed
# both times -- the same frozen description and seed produced a different
# character every scene. Style, unlike character, holds fine.
#
# "3d" is the one that does hold a character, because it is the same model
# every frame rather than a fresh guess. It costs about two minutes of
# rendering per minute of video and needs node plus Chrome.
VISUAL_STYLE = os.getenv("VISUAL_STYLE", "photo").strip().lower()

# --- Length -----------------------------------------------------------------
# Longer is not better: a padded four-minute video loses viewers a tight
# three-minute one keeps. The narration runs at roughly 145 words per minute
# and each beat is written at 55-80 words, so the beat cap follows from the
# minute cap rather than being guessed separately.
MAX_VIDEO_MINUTES = float(os.getenv("MAX_VIDEO_MINUTES", "3"))
WORDS_PER_MINUTE = 145

# Everything about length comes from the target runtime, including how long a
# beat may be. Fixing beat length separately is what made a 1-minute target
# still produce a 1.8-minute video: the beat floor times the fixed 65-word
# beat overshot the total before the total was ever consulted.
TARGET_WORDS = int(MAX_VIDEO_MINUTES * WORDS_PER_MINUTE)
MAX_LONG_BEATS = max(3, min(12, round(TARGET_WORDS / 60)))
WORDS_PER_BEAT = max(25, round(TARGET_WORDS / MAX_LONG_BEATS))

# --- Dialogue ---------------------------------------------------------------
# Two characters talking to each other instead of one narrator reading at the
# camera. Everything else about the 3D scene already assumed two people; only
# the script never did, so both mouths were fed the same monologue and the
# speaker alternated on a counter.
#
# It also changes the arithmetic of length. A narrated beat is ~55 words
# because it is a whole thought; a spoken line is 8 to 16 because that is how
# people talk. The same runtime therefore holds four to five times as many
# beats -- and since the assembler cuts once per beat, four to five times as
# many cuts. A 23-second unbroken shot was its own argument for this.
DIALOGUE = os.getenv("DIALOGUE", "true").strip().lower() == "true"
WORDS_PER_LINE = int(os.getenv("WORDS_PER_LINE", "12"))
MAX_DIALOGUE_LINES = max(4, min(40, round(TARGET_WORDS / WORDS_PER_LINE)))

# What a character is doing while a line is said. One vocabulary, three
# consumers: the script writer may only emit these, the voice reads the line
# with that action's delivery, and the 3D scene plays that action's animation.
# Keeping it to one list is the point -- an action the writer can name but the
# renderer cannot play is a character who says "hahaha" while standing still.
ACTIONS = ("talk", "ask", "laugh", "surprise", "think", "run", "fight", "jump")
DEFAULT_ACTION = "talk"

# --- Content mode -----------------------------------------------------------
# "news"      trending topic -> researched, fact-checked script
# "animation" original jokes / facts / riddles / stories, no research
CONTENT_MODE = os.getenv("CONTENT_MODE", "news").strip().lower()

# Which kinds the animation mode cycles through when --kind is not given.
ANIMATION_KINDS = _csv("ANIMATION_KINDS", "jokes,facts,riddles,stories")

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
