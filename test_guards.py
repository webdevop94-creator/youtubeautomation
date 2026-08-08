"""Tests for the two guards that stand between the agent and a bad upload.

No network, no API keys, runs in under a second:

    python test_guards.py

Both cases below came from real agent runs, not imagination. Add a case here
whenever the agent picks something it should not have, or refuses something it
should have allowed -- that is what keeps the word lists honest.
"""
import sys

import script_writer
import viral

# --- Safety filter ---------------------------------------------------------

SAFETY_CASES = [
    # (headline, should_be_blocked, note)
    ("Perez Hilton's family asks paparazzi to give children privacy as new "
     "details around crisis emerge", True, "agent actually picked this one"),
    ("Live updates: Teen gunman dead after killing teachers in Thailand school",
     True, "tragedy"),
    ("Republican Lisa Murkowski opposes Todd Blanche nomination", True, "politics"),
    ("Spokane Arson Suspect Said He'd Started Dozens of Fires, Prosecutors Say",
     True, "crime"),
    ("Madonna and Blur producer William Orbit dies aged 69", True, "death"),
    ("Trump targets birthright citizenship. And, Iran aims to ban U.S. from "
     "Strait of Hormuz", True, "agent ranked this #2 on a public run"),

    ("iPhone 18 Pro price: Here's how much more it could cost", False, "tech"),
    ("'Grand Theft Auto VI' Game To Debut Extended Look On Netflix This Month",
     False, "'theft' in a game title must not read as crime"),
    ("I tested the new Samsung Galaxy Watch9: the most exciting features",
     False, "review"),
    ("Trade Desk Stock Slumps After Revenue Misses Forecasts", False, "business"),
    ("Scientists discover new species of deep sea octopus", False, "science"),
    ("Bayern Munich beat Aston Villa 2-1 in Hong Kong friendly", False, "sport"),
    ("Lionel Richie announces world tour dates", False, "entertainment"),
]

# --- Invented figures ------------------------------------------------------

FACTS = {
    "topic": "Bayern Munich beat Aston Villa 2-1 in Hong Kong",
    "headlines": ["Bayern Munich win 2-1 in Hong Kong friendly"],
    "snippets": ["150 invited fans from across the region contributed to the atmosphere."],
    "articles": [{"url": "x", "text": (
        "Bayern Munich beat Aston Villa 2-1 on 7 August at Kai Tak Stadium. "
        "150 invited fans attended the Audi shoot. Luis Diaz scored a wondergoal. "
        "The club reported revenue of 1,200,000,000 euros last season. "
        "Around 45,000 spectators watched the game.")}],
}

NUMBER_CASES = [
    # (sentence, should_be_removed, note)
    ("Is match mein 38,000 fans ne participate kiya.", True,
     "the real hallucination: sources say 150"),
    ("Ismein 150 invited fans the.", False, "figure is in the sources"),
    ("Bayern ne 45,000 logon ke saamne khela.", False, "figure is in the sources"),
    ("Bayern ne Aston Villa ko 2-1 se haraya.", False, "under the 100 threshold"),
    ("Yeh match 7 August ko hua tha.", False, "dates are never checked"),
    ("Club ka revenue ek billion euro tha.", True, "sources say 1.2 billion"),
    ("Club ka revenue 1.2 billion euro tha.", False, "matches within tolerance"),
    ("Stadium mein do lakh log the.", True, "spelled-out 200,000 appears nowhere"),

    # Years are dates. A live run deleted six correct lines because
    # "do hazaar chhabbis" parsed as 2000 and 2000 was not in the sources.
    ("August do hazaar chhabbis me naya season aaya.", False, "2026 is a year"),
    ("Dono ki kahani saal do hazaar ikkis me shuru hui.", False, "2021 is a year"),
    ("Unhone saal do hazaar pandrah me kaam kiya.", False, "2015 is a year"),
    ("Yeh 2026 me hua tha.", False, "a year in digits"),
    ("Company ki value do hazaar crore rupees hai.", True,
     "20,000,000,000 is a quantity, not a year"),
]


def spelled_number_cases():
    """Hinglish compound numerals must parse to the right value."""
    return [
        ("do hazaar chhabbis", 2026.0),
        ("do hazaar ikkis", 2021.0),
        ("do hazaar", 2000.0),
        ("teen lakh", 300_000.0),
        ("paanch crore", 50_000_000.0),
        ("ek billion", 1_000_000_000.0),
    ]


# --- Perishable topics -----------------------------------------------------
# Stories that are dead content by the time a video finishes rendering.

PERISHABLE_CASES = [
    # (headline, should_be_dropped, note)
    ("\U0001F4FA FFCtv: Fulham FC v Crystal Palace", True,
     "agent ranked this #1 on a public run -- a TV listing, not a story"),
    ("Bayern Munich vs Aston Villa LIVE! Pre-season friendly commentary", True,
     "live blog"),
    ("Arsenal v Chelsea: team news and predicted line-ups", True, "fixture preview"),
    ("India vs Australia: how to watch, start time", True, "broadcast details"),

    ("Match Awards from Bayern Munich's 2-1 friendly win over Aston Villa", False,
     "a write-up that survives the match"),
    ("iPhone 18 Pro price: Here's how much more it could cost", False, "lasting"),
    ("Man City reject Barcelona's opening bid for Rodri", False, "transfer news"),
    ("Scientists discover new species of deep sea octopus", False, "lasting"),
]


def run() -> int:
    failures = 0

    print("SAFETY FILTER")
    for headline, should_block, note in SAFETY_CASES:
        flags = viral.safety_flags(headline)
        ok = bool(flags) == should_block
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'}  {'block' if flags else 'allow':<6} "
              f"{headline[:58]:<60} {','.join(flags) or note}")

    print("\nPERISHABLE TOPICS")
    for headline, should_drop, note in PERISHABLE_CASES:
        dropped = bool(viral.PERISHABLE.search(headline))
        ok = dropped == should_drop
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'}  {'drop ' if dropped else 'keep ':<6} "
              f"{headline[:58]:<60} {note}")

    print("\nSPELLED-OUT NUMBERS")
    for phrase, expected in spelled_number_cases():
        got = script_writer._numbers_in(phrase)
        ok = expected in got
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'}  {phrase:<22} -> "
              f"{expected:,.0f}   (parsed {sorted(got)})")

    print("\nINVENTED FIGURES")
    for sentence, should_remove, note in NUMBER_CASES:
        beats = [{"text": sentence + " Yeh baaki line hai jo rehni chahiye.",
                  "keywords": "x"}]
        # Quiet: the stripper narrates every removal, which drowns the report.
        removed = script_writer._strip_invented_numbers(beats, FACTS, "test")
        ok = (removed > 0) == should_remove
        failures += not ok
        print(f"  {'ok  ' if ok else 'FAIL'}  "
              f"{'removed' if removed else 'kept':<8} {sentence[:50]:<52} {note}")

    total = (len(SAFETY_CASES) + len(PERISHABLE_CASES)
             + len(spelled_number_cases()) + len(NUMBER_CASES))
    print(f"\n{total - failures}/{total} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run())
