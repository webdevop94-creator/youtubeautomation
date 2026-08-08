"""One-time YouTube authorisation. Run once, then uploads happen automatically."""
import config
import youtube_upload

print("YouTube authorisation setup")
print("-" * 50)

if not config.YOUTUBE_CLIENT_ID or not config.YOUTUBE_CLIENT_SECRET:
    raise SystemExit(
        "\n[X] .env mein YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET nahi hai.\n\n"
        "Steps:\n"
        "  1. https://console.cloud.google.com -> naya project banao\n"
        "  2. APIs & Services -> Library -> 'YouTube Data API v3' -> Enable\n"
        "  3. OAuth consent screen -> External -> apna email 'Test users' mein add karo\n"
        "  4. Credentials -> Create Credentials -> OAuth client ID -> Desktop app\n"
        "  5. Client ID aur Client Secret .env mein paste karo\n"
        "  6. Ye script dobara chalao\n")

print("\nBrowser khulega. Apne YouTube channel wale Google account se login karo.")
print("'Google hasn't verified this app' aaye to -> Advanced -> Go to (unsafe).")
print("Ye normal hai, app aapka apna hai.\n")

youtube_upload.authorise(force=True)

print(f"\n[OK] Token save ho gaya: {config.TOKEN_FILE}")
print("Ab uploads automatic honge. Ye setup dobara karne ki zarurat nahi.")
