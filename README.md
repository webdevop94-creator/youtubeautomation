# Hinglish Viral Video Agent

Duniya mein jo viral hai wo dhoondho → fact-check → Hinglish script → voice →
video → YouTube upload.

Do tarah se chalta hai:

| | Command | Kaun chalata hai |
|---|---|---|
| **Manual** | `python main.py` | Aap. Do jagah approve karte ho. |
| **Agent** | `python agent.py` | Windows Task Scheduler, roz. Koi approval nahi. |

Cost: **₹0/month**. Sab free tiers par chalta hai.

---

## Setup (ek baar)

### 1. Keys `.env` mein daalo

```
copy .env.example .env
```

Phir `.env` khol kar bharo:

| Key | Kahan se | Time |
|-----|----------|------|
| `GROQ_API_KEY` | https://console.groq.com → API Keys → Create | 2 min |
| `PEXELS_API_KEY` | https://www.pexels.com/api/ → signup | 2 min |
| `YOUTUBE_CLIENT_ID` + `SECRET` | neeche dekho | 10 min |

### 2. YouTube OAuth

1. https://console.cloud.google.com → naya project
2. **APIs & Services → Library** → "YouTube Data API v3" → **Enable**
3. **OAuth consent screen** → External → apna email **Test users** mein add karo
4. **Credentials → Create Credentials → OAuth client ID → Desktop app**
5. Client ID + Secret `.env` mein paste karo
6. Chalao:

```
python setup_youtube.py
```

Browser khulega → apne channel wale account se login → done.
"Google hasn't verified this app" aaye to **Advanced → Go to (unsafe)** — app aapka apna hai.

Token `.youtube_token.json` mein save ho jayega. Dobara karne ki zarurat nahi.

### 3. Background music (optional)

`music/` folder banao aur usme koi royalty-free mp3 daal do. Apne aap
voice ke neeche -22 dB par mix ho jayega. Folder khaali ho to music skip.

---

### 4. Virtualenv

```
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

Aage har command `.\.venv\Scripts\python.exe` se chalao (scheduler bhi yahi
use karta hai).

---

## Chalana (manual)

```bash
python main.py                    # topic choose karo, dono gates par approve
python main.py --auto             # top viral topic khud le lega
python main.py --source niche     # sirf AI/tech news (purana behaviour)
python main.py --topic "OpenAI ka naya model"
python main.py --category sports  # script ka tone force karo
python main.py --format shorts    # sirf vertical Shorts
python main.py --no-upload        # sirf video banao, upload mat karo
python main.py --yes              # kuch mat poocho, sab khud karo
python main.py --rebuild output/2026-08-07_1430_topic-name
```

### Flow

```
[1] Viral topics             Google Trends (10 desh) + Google News sections + Reddit
[2] Facts verify             asli articles padh kar, taaki AI jhooth na bole
[3] Script                   Groq, Hinglish, category ke hisaab se tone
     |
     +-- APPROVAL 1: script dikhega -> y / e (edit) / n
     |
[4] Voice                    edge-tts, per-beat timing
[5] Visuals                  Pexels stock footage
[6] Video assemble           FFmpeg, subtitles burn, music mix
     |
     +-- APPROVAL 2: folder khulega, video dekh lo -> upload y/n
     |
[7] YouTube upload           thumbnail + description + tags ke saath
```

---

## Roz apne aap (agent)

`agent.py` wahi pipeline hai, bina kisi approval ke, plus wo cheezein jo tab
zaroori ho jaati hain jab koi dekh nahi raha.

```bash
python agent.py --dry-run     # sirf topics dikhao, video mat banao  <- pehle ye
python agent.py --no-upload   # poori video banao, upload mat karo
python agent.py               # sab kuch: topic, video, upload
python agent.py --history     # ab tak kya cover hua
python agent.py --count 2     # ek run mein 2 videos
```

Schedule karna:

```powershell
powershell -ExecutionPolicy Bypass -File setup_schedule.ps1            # roz 7:00 AM
powershell -ExecutionPolicy Bypass -File setup_schedule.ps1 -Time 06:30
powershell -ExecutionPolicy Bypass -File setup_schedule.ps1 -Remove
```

```powershell
Start-ScheduledTask -TaskName ViralVideoAgent      # abhi test karo
Get-ScheduledTaskInfo -TaskName ViralVideoAgent    # last run kab, result kya
```

Sab kuch `agent.log` mein likha jata hai — scheduler console output phenk deta
hai, isliye problem dhoondhne ki wahi ek jagah hai.

### Agent kya khud sambhalta hai

| | |
|---|---|
| **Duplicate** | `history.json` mein 45 din ka record. Bada topic hafte bhar trend karta hai; ye usse roz dobara banne se rokta hai. |
| **Safety** | Shooting, court case, war, election — ye topics apne aap hat jaate hain. `ALLOW_SENSITIVE=true` se hatega, par tab har script khud padhna. |
| **Perishable** | "LIVE", "vs", "highlights", "score" wale topics drop — video ban'ne tak wo bekaar ho chuke hote hain. |
| **Patle sources** | Agar articles nahi khule to wo topic chhod kar agla try karta hai (4 tak). |
| **Chhoti script** | Model aksar 25-word beats likh deta hai. Word count check hota hai aur chhoti script wapas expand karwai jaati hai. |
| **Banaye hue numbers** | Script ka har figure (100 se bada) source text se match kiya jata hai — digits aur "do lakh"/"ek billion" dono. Na mile to poori line hat jati hai. |
| **Groq rate limit** | Free tier 12,000 tokens/minute deta hai, jo do script calls se kam hai. 429 aane par Groq jitna time bolta hai utna ruk kar retry hota hai. Daily quota khatam ho to NVIDIA par switch. |
| **Internet chala jaye** | Connection error pakad kar 15 min tak network ka wait karta hai, phir **wahi topic** dobara try karta hai. Warna ek outage seconds mein chaaron attempts jala deta tha — aur har fail "sources patle hain" bata kar galat diagnosis deta tha. |

### Topic kaise chunta hai

Teen alag signals, aur bharosa unke **overlap** par:

1. **Google Trends** — 10 deshon ki daily trending list, har trend ke saath 3 asli
   publisher URLs (ye seedha padhe ja sakte hain, Google News links ke ulat)
2. **Google News sections** — World, Business, Tech, Entertainment, Sports, Science
3. **Reddit `r/all`** — log actually kis par click kar rahe hain

Ek desh ki trending list akeli lagbhag bekaar hai — usme local sports aur
celebrity naam bhare hote hain. **Jo cheez ek saath kai deshon mein trend kar
rahi hai, wahi asli global viral hai**, isliye geo-spread ko search volume se
kahin zyada weight milta hai.

Khud dekhna ho:

```bash
python viral.py
```

### Guards test karna

```bash
python test_guards.py
```

Safety filter aur invented-number guard ke tests — network nahi chahiye, ek
second mein chalte hain. Dono guards ke cases asli agent runs se aaye hain.
Agent kabhi aisa topic uthaye jo nahi uthana chahiye tha (ya sahi topic mana kar
de), to `test_guards.py` mein ek case add karo, phir `viral.py` ki word list
theek karo.

---

## Output

```
output/2026-08-07_1430_topic-name/
├── video_16x9.mp4                long-form
├── video_9x16.mp4                Shorts (subtitles burned in)
├── voice_long.mp3
├── subtitles_long.srt            YouTube par alag se upload kar sakte ho
├── script.json                   edit kar ke --rebuild chalao
├── script.txt                    padhne ke liye
├── title_and_description.txt
├── thumbnail.jpg
├── topic.json                    topic kahan se aaya, kaunse signals the
└── uploaded.txt                  upload hone par video ka link
```

Project folder mein:

```
history.json      45 din ka covered-topics record (duplicate guard)
agent.log         har scheduled run ka poora record
```

---

## Zaroori baatein

**Privacy default `private` hai.** Agent ke saath ise **private hi rakho** jab tak
kam se kam ek hafta output dekh na lo. Roz subah folder khol kar video dekho, achhi
lage to YouTube Studio se public kar do. Jab bharosa ho jaye tab `.env` mein
`UPLOAD_PRIVACY=public`.

**Script padh lo.** Fact-checking step laga hua hai par 100% guarantee nahi hai.
Manual mode mein Approval 1 par 30 second mein padh lena. Agent mode mein har
video ke folder ka `script.txt` padhna — agent ke paas koi judgement nahi hai,
sirf filters hain.

Numbers ab apne aap verify hote hain (source mein na mile to line hat jati hai),
par **naam, quotes aur dawe verify nahi hote**. Wahi cheez padhni hai.

**Safety filter kyun on hai.** Bina dekhe chalne wala channel warna khushi-khushi
kisi school shooting par Hinglish explainer bana dega. Taste ke alawa: YouTube ki
advertiser-friendly guidelines violent tragedy ko demonetise karti hain, aur
election/medical content par strike ka risk hai. `ALLOW_SENSITIVE=false` rehne do.

**`your_take` field.** Har script mein ek line hoti hai jahan aap apni raay
add kar sakte ho. Ye karo — purely AI content ko YouTube "inauthentic" maan
sakta hai aur monetization reject ho sakti hai. Apni 2 line analysis usse
original commentary bana deti hai.

---

## Voice

Do engine hain, `.env` mein `TTS_ENGINE` se choose karo.

### `edge` (default) — Microsoft cloud

Free, unlimited, koi install nahi, compute Microsoft ke server par — isliye
purane laptop par bhi 2-3 second mein ban jati hai. Hindi voices production
neural voices hain.

```
TTS_ENGINE=edge
VOICE=hi-IN-MadhurNeural
```

Indian voices jo edge-tts deta hai — **poori list yahi hai**, isse zyada nahi:

| Voice | |
|---|---|
| `hi-IN-MadhurNeural` | Hindi, male (default) |
| `hi-IN-SwaraNeural` | Hindi, female |
| `en-IN-PrabhatNeural` | Indian English, male |
| `en-IN-NeerjaNeural` | Indian English, female |
| `en-IN-NeerjaExpressiveNeural` | Indian English, female, zyada expressive |

Sab languages: `python -m edge_tts --list-voices`

### `kokoro` — local, offline

[Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M), Apache 2.0, 82M
parameters, CPU par chalta hai. Internet ki zarurat nahi (pehli baar ~330 MB
weights download hote hain). Fayda: Microsoft par dependency khatam.

```
TTS_ENGINE=kokoro
KOKORO_VOICE=hm_omega
```

Hindi voices: `hm_omega`, `hm_psi` (male), `hf_alpha`, `hf_beta` (female).

**Trade-off jaan lo:** Kokoro ke apne docs Hindi voices ko **grade C** dete
hain (American English ko A). Aur ye word-level timings nahi deta, isliye
subtitles proportional timing par bante hain — edge jitne accurate nahi.

Install (spacy jaan-boojh kar skip kiya hai — uske Python 3.14 wheels nahi
hain aur Hindi ko wo chahiye bhi nahi, wo sirf English G2P ke liye hai):

```powershell
.\.venv\Scripts\pip install torch --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\pip install transformers soundfile huggingface_hub loguru num2words espeakng-loader phonemizer-fork
.\.venv\Scripts\pip install --no-deps kokoro misaki
```

### Jo repos Hindi ke liye kaam nahi karte

| Repo | Kyun nahi |
|---|---|
| **MeloTTS** | Hindi hai hi nahi — sirf EN, EN_V2, FR, JP, ES, ZH, KR (`melo/download_utils.py` mein confirm karo) |
| **Indic Parler-TTS** | Hindi achhi hai par 2.2B params — bina GPU ke is laptop par nahi chalega |
| **XTTS-v2** | Hindi + voice cloning, par licence **non-commercial** — monetized channel par use mat karo |
| **MMS-TTS-hin** | Halka hai par licence CC-BY-**NC**, aur awaaz robotic |

---

## Free tier limits

| Service | Limit | Ek video mein |
|---------|-------|---------------|
| Groq | **100,000 tokens/day**, 12,000/minute | 15,000-20,000 (retries ke saath) |
| Pexels | 200 req/hour | ~15 req |
| edge-tts | unlimited | — |
| Google Trends RSS | key nahi, koi documented limit nahi | 10 req (har desh 1) |
| Google News RSS | key nahi | 7 req |
| Reddit RSS | sakht rate limit | 1 req |
| YouTube upload | 10,000 units/day | 1600 units (~6 video/din) |

Reddit ek run mein sirf ek baar hit hota hai. Thodi der mein kai baar chalao to
`HTTP 429` aayega — us run mein Reddit signal chhoot jayega, baaki sab chalta
rahega.

**Groq ka daily limit sabse pehle khatam hota hai.** `llama-3.3-70b-versatile`
par free tier 100,000 tokens/day deta hai, aur ek video 15,000-20,000 leti hai
(repetition aur length retries milakar). Matlab **roz ~5 video**.

### Fallback: NVIDIA NIM

Groq khatam ho jaye to agent apne aap NVIDIA par chala jata hai — din bachta hai.

```
NVIDIA_API_KEY=nvapi-...
NVIDIA_MODEL=openai/gpt-oss-20b
```

Key: https://build.nvidia.com/settings/api-keys → Generate Key. Sign-up par
1000 free credits.

Switch karne ka logic (`script_writer.py` mein `_call_llm`):

```
Groq try karo
  ├─ 429 "tokens per day"  → turant NVIDIA (rukna bekaar, quota kal hi aayega)
  ├─ 429 per-minute        → Groq jitna time bole utna ruko, phir retry
  └─ 3 baar fail           → NVIDIA
```

Model choose karte waqt jo mila (7 Aug 2026 ko test kiya):

| Model | Result |
|---|---|
| `openai/gpt-oss-20b` | **chalta hai**, ~12s, JSON saaf — yahi default hai |
| `meta/llama-3.3-70b-instruct` | chalta hai, aur Groq wale model ka same hai — par test mein timeout hua |
| `deepseek-ai/deepseek-v4-flash` / `v4-pro` | **HTTP 410 Gone** — 7 Aug 2026 ko end-of-life ho gaye |
| `deepseek-ai/deepseek-coder-6.7b` | 404, aur waise bhi code model hai |

Catalog page purane models dikhata rehta hai. Naya model set karne se pehle
`python -c "import script_writer"` wala test nahi, seedha API se list nikalo:

```powershell
.\.venv\Scripts\python.exe -c "import requests,config;print([m['id'] for m in requests.get('https://integrate.api.nvidia.com/v1/models',headers={'Authorization':'Bearer '+config.NVIDIA_API_KEY}).json()['data']])"
```

Reasoning models (`gpt-oss`, DeepSeek R1) apna chain-of-thought bhejte hain —
`_extract_json` `<think>` blocks strip kar deta hai, isliye ye kaam karte hain.

Sirf Groq chahiye to `NVIDIA_API_KEY` khaali chhod do. Dono na ho to agent
saaf error deta hai.

**`.env` edit karte waqt BOM se bachna.** PowerShell ka
`Set-Content -Encoding utf8` UTF-8 **with BOM** likhta hai, aur BOM pehli line
ki key ka naam kharab kar deta hai (`GROQ_API_KEY` → `﻿GROQ_API_KEY`) —
key chup-chaap gayab ho jati hai. Notepad/VS Code se edit karo, ya
`[System.IO.File]::WriteAllText($path, $text, (New-Object System.Text.UTF8Encoding($false)))`.

---

## Troubleshooting

**`ffmpeg nahi mila`** → `winget install --id Gyan.FFmpeg -e`, phir naya terminal kholo.

**`Groq API error 429`** → daily limit khatam. Kal chalao ya `.env` mein
`GROQ_MODEL=llama-3.1-8b-instant` kar do.

**Pexels par clip nahi milta** → gradient card lag jayega, video fir bhi banega.
Script ke `keywords` zyada abstract honge to aisa hota hai.

**Upload 403 `quotaExceeded`** → YouTube ka daily quota. 24 ghante baad reset.

**Thumbnail set nahi hui** → custom thumbnail ke liye channel verify hona chahiye
(phone number se). Video fir bhi upload ho jata hai.

### Agent-specific

**Scheduled task chali par kuch nahi hua** → `agent.log` sabse pehle dekho. Wahan
kuch nahi hai to matlab Python start hi nahi hua: `Get-ScheduledTaskInfo -TaskName
ViralVideoAgent` ka `LastTaskResult` dekho. `0` = theek.

**"Sab topics pehle cover ho chuke"** → duplicate guard ne sab hata diye. Ye tab
hota hai jab din mein kai baar chalao. `python agent.py --history` se dekho kya
cover hua hai; `history.json` delete karne se guard reset ho jata hai.

**"sources patle hain" bar-bar** → trending topic hai par uske articles nahi khul
rahe (paywall ya bot-block). Agent apne aap agla topic try karta hai. Har baar aisa
ho to `.env` mein `MAX_TOPIC_ATTEMPTS` badha do.

**Reddit `HTTP 429`** → normal hai agar thodi der mein kai run kiye. Us run mein
Reddit signal chhoot jayega, trends aur news se kaam chal jayega.

**Video bahut chhoti ban rahi hai** → script model chhote beats likhta hai. Length
check apne aap expand karwata hai; log mein `Expand ho gaya` dikhega. `Expand fail`
aaye to source material hi patla tha.

**Laptop band tha jis waqt task chalni thi** → `StartWhenAvailable` on hai, laptop
on hote hi chal jayegi. Poore din band raha to us din ka run miss.
