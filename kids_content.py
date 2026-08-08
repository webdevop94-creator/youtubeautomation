"""Traditional Hindi nursery rhymes and simple learning content.

ONLY folk/traditional verses go in this file. Film songs are copyrighted even
when everyone remembers them as nursery rhymes -- "Lakdi ki kathi" (Masoom,
1983), "Nani teri morni" (Masoom, 1960), "Chanda mama door ke" (Vachan, 1955)
and "Aao bachchon tumhein dikhayein" (Jagriti, 1954) all have living
copyright in the lyrics and composition. Uploading them earns a Content ID
claim or a strike, so they are deliberately absent.

Each entry carries its own colour palette and sprite set so every rhyme looks
different without any manual design work.
"""

RHYMES = {
    "machhli": {
        "title": "मछली जल की रानी है",
        "title_roman": "Machhli Jal Ki Rani Hai",
        "lines": [
            "मछली जल की रानी है",
            "जीवन उसका पानी है",
            "हाथ लगाओ डर जाएगी",
            "बाहर निकालो मर जाएगी",
        ],
        "palette": ["#0b3d91", "#1e88c7", "#4fc3f7"],
        "sprites": ["fish", "fish", "bubble", "star"],
        "tags": ["machhli jal ki rani", "hindi rhymes", "nursery rhymes hindi",
                 "hindi balgeet", "kids song hindi", "bachon ki kavita"],
    },
    "aloo_kachaloo": {
        "title": "आलू कचालू बेटा कहाँ गए थे",
        "title_roman": "Aloo Kachaloo Beta Kahan Gaye The",
        "lines": [
            "आलू कचालू बेटा कहाँ गए थे",
            "बंदर की झोपड़ी में सो रहे थे",
            "बंदर ने लात मारी रो रहे थे",
            "अम्मा ने पैसे दिए हँस रहे थे",
        ],
        "palette": ["#7b3f00", "#c97b28", "#f2b544"],
        "sprites": ["balloon", "star", "flower", "balloon"],
        "tags": ["aloo kachaloo", "hindi rhymes", "nursery rhymes hindi",
                 "hindi balgeet", "kids song hindi"],
    },
    "hathi_raja": {
        "title": "हाथी राजा कहाँ चले",
        "title_roman": "Hathi Raja Kahan Chale",
        "lines": [
            "हाथी राजा कहाँ चले",
            "सूँड़ हिलाते कहाँ चले",
            "मेरे घर पर आ जाओ",
            "हलवा पूरी खा जाओ",
        ],
        "palette": ["#1b5e20", "#43a047", "#a5d6a7"],
        "sprites": ["elephant", "flower", "star", "flower"],
        "tags": ["hathi raja kahan chale", "hindi rhymes", "nursery rhymes hindi",
                 "hindi balgeet", "kids song hindi"],
    },
    "chidiya": {
        "title": "चूँ चूँ करती आई चिड़िया",
        "title_roman": "Chun Chun Karti Aayi Chidiya",
        "lines": [
            "चूँ चूँ करती आई चिड़िया",
            "दाल का दाना लाई चिड़िया",
            "मोर ने पूछा कहाँ से आई",
            "चिड़िया बोली बहुत दूर से",
        ],
        "palette": ["#4a148c", "#7e57c2", "#b39ddb"],
        "sprites": ["bird", "cloud", "star", "bird"],
        "tags": ["chun chun karti aayi chidiya", "hindi rhymes",
                 "nursery rhymes hindi", "hindi balgeet", "kids song hindi"],
    },
    "ginti": {
        "title": "एक दो तीन चार गिनती सीखें",
        "title_roman": "Ek Do Teen Char - Hindi Ginti",
        "lines": [
            "एक दो तीन चार",
            "पाँच छह सात आठ",
            "नौ दस ग्यारह बारह",
            "चलो सब मिलकर गिनें",
        ],
        "palette": ["#b71c1c", "#e53935", "#ffab91"],
        "sprites": ["star", "balloon", "flower", "star"],
        "tags": ["hindi ginti", "counting in hindi", "hindi numbers for kids",
                 "hindi rhymes", "learn hindi numbers"],
    },
    "rang": {
        "title": "रंग सीखें लाल पीला नीला",
        "title_roman": "Rang Seekhein - Hindi Colours",
        "lines": [
            "लाल रंग है सेब का",
            "पीला रंग है सूरज का",
            "नीला रंग है आसमान का",
            "हरा रंग है पत्ते का",
        ],
        "palette": ["#00695c", "#26a69a", "#80cbc4"],
        "sprites": ["flower", "balloon", "star", "cloud"],
        "tags": ["hindi colours", "rang seekhein", "hindi rhymes for kids",
                 "learn colours in hindi", "hindi balgeet"],
    },
}

DESCRIPTION_TEMPLATE = """{title} - बच्चों के लिए मज़ेदार हिंदी बालगीत।

छोटे बच्चों के लिए रंग-बिरंगा एनिमेशन और आसान हिंदी शब्द।
यह एक पारंपरिक लोक कविता है।

अगर आपके बच्चे को यह पसंद आया तो चैनल को subscribe ज़रूर करें।

{hashtags}
"""


def get_rhyme(key: str) -> dict:
    if key not in RHYMES:
        raise SystemExit(
            f"[X] '{key}' nahi mila. Available: {', '.join(RHYMES)}")
    return {**RHYMES[key], "key": key}


def list_rhymes() -> None:
    print("\nAvailable rhymes (sab traditional / public domain):\n")
    for key, rhyme in RHYMES.items():
        print(f"  {key:<16} {rhyme['title']}")
    print()


def build_beats(rhyme: dict, repeats: int = 3) -> list:
    """One beat per line. Nursery rhymes repeat -- that is how toddlers learn."""
    beats = []
    for _ in range(repeats):
        for line in rhyme["lines"]:
            beats.append({"text": line, "keywords": rhyme["key"]})
    return beats


def metadata(rhyme: dict) -> dict:
    hashtags = " ".join(f"#{t.replace(' ', '')}" for t in rhyme["tags"][:6])
    return {
        "title": f"{rhyme['title']} | {rhyme['title_roman']} | Hindi Rhymes for Kids"[:95],
        "description": DESCRIPTION_TEMPLATE.format(
            title=rhyme["title"], hashtags=hashtags),
        "tags": rhyme["tags"],
    }
