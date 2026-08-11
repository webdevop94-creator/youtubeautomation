"""Upload the finished video to YouTube using a saved OAuth refresh token."""
import json
from pathlib import Path

import config

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CATEGORY_SCIENCE_TECH = "28"
CATEGORY_EDUCATION = "27"

# Our internal topic categories -> YouTube categoryId. Filing a football
# signing under Science & Technology suppresses it in browse and suggested,
# which is where a new channel gets nearly all of its views.
YT_CATEGORY = {
    "tech": "28",
    "science": "28",
    "sports": "17",
    "entertainment": "24",
    "world": "25",
    "business": "27",
    "health": "27",
    "general": "27",
    "education": "27",
}


def category_id(topic_category: str) -> str:
    return YT_CATEGORY.get((topic_category or "").lower(), CATEGORY_SCIENCE_TECH)


def _client_config() -> dict:
    return {
        "installed": {
            "client_id": config.YOUTUBE_CLIENT_ID,
            "client_secret": config.YOUTUBE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }


def authorise(force: bool = False):
    """Run the browser consent flow once and cache the refresh token."""
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow

    config.require_key("YOUTUBE_CLIENT_ID", config.YOUTUBE_CLIENT_ID,
                       "https://console.cloud.google.com")
    config.require_key("YOUTUBE_CLIENT_SECRET", config.YOUTUBE_CLIENT_SECRET,
                       "https://console.cloud.google.com")

    creds = None
    if config.TOKEN_FILE.exists() and not force:
        creds = Credentials.from_authorized_user_info(
            json.loads(config.TOKEN_FILE.read_text()), SCOPES)

    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_config(_client_config(), SCOPES)
        # Keep {url} in the message: if the wrong Chrome profile opens, the user
        # needs the link to paste into the profile that has the channel account.
        creds = flow.run_local_server(
            port=0, prompt="consent",
            authorization_prompt_message=(
                "\nBrowser khul raha hai. Apne YouTube channel wale Google account "
                "se login karo.\n"
                "Agar galat account/profile khule, to ye link us Chrome profile mein "
                "paste karo:\n\n{url}\n"),
            success_message=(
                "Ho gaya! Ye tab band kar sakte ho, terminal par wapas jao."))

    config.TOKEN_FILE.write_text(creds.to_json(), encoding="utf-8")
    return creds


def upload(video_path: Path, title: str, description: str, tags: list,
           thumbnail: Path = None, privacy: str = None,
           made_for_kids: bool = False, category: str = None) -> str:
    """Upload one video. Returns the watch URL."""
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    privacy = (privacy or config.UPLOAD_PRIVACY or "private").lower()
    if privacy not in ("private", "unlisted", "public"):
        privacy = "private"

    youtube = build("youtube", "v3", credentials=authorise(), cache_discovery=False)

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:4900],
            "tags": [t for t in tags if t][:15],
            "categoryId": category or CATEGORY_SCIENCE_TECH,
            "defaultLanguage": "hi",
        },
        "status": {
            "privacyStatus": privacy,
            # COPPA requires this to be accurate. Content aimed at children
            # must be declared, and mis-declaring it is a legal problem,
            # not just a policy one.
            "selfDeclaredMadeForKids": bool(made_for_kids),
        },
    }

    media = MediaFileUpload(str(video_path), chunksize=8 * 1024 * 1024,
                            resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    print(f"[7/7] YouTube par upload ho raha hai ({privacy})...")
    response, last_pct = None, -1
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            if pct >= last_pct + 10:
                print(f"    {pct}%")
                last_pct = pct

    video_id = response["id"]
    url = f"https://www.youtube.com/watch?v={video_id}"
    print(f"    Upload done: {url}")

    if thumbnail and Path(thumbnail).exists():
        try:
            youtube.thumbnails().set(
                videoId=video_id, media_body=MediaFileUpload(str(thumbnail))).execute()
            print("    Thumbnail set")
        except Exception as exc:
            # Custom thumbnails need a verified channel; not fatal.
            print(f"    [!] Thumbnail set nahi hui: {exc}")

    return url
