"""Deterministic safety-floor rule engine.

This runs *outside* the language model, on purpose. The model can be calm,
wrong, or talked around; these rules cannot. If any pattern here matches the
transcript, the case is forced to at least the Critical floor no matter what
the model returned. This is the "explicit-risk rules run outside the model"
design claim, implemented literally.

Every rule carries a human-readable label so the dashboard can show *why* the
floor fired, and each match records its character span so the counsellor can
jump to that part of the transcript.

To extend: add an entry to RULES. Keep patterns narrow and specific - a false
floor trigger wastes a counsellor's time, so precision matters more than
recall here.
"""
from __future__ import annotations

import re
from typing import Dict, List, Tuple

# (rule_id, human label, regex) - patterns cover English, Hindi (Devanagari)
# and romanised Hindi, because helpline callers code-mix constantly.
RULES: List[Tuple[str, str, str]] = [
    (
        "threat_to_life",
        "Explicit threat to life",
        r"\b(jaan\s*se\s*maar|jaan\s*le\s*l[eo]|kill (?:me|you|us|him|her)|"
        r"murder|maar\s*d(?:al)?unga|maar\s*denge|kaat\s*d(?:al)?unga)\b"
        r"|जान\s*से\s*मार|मार\s*दूंगा|मार\s*देंगे|क़त्ल|कत्ल",
    ),
    (
        "weapon",
        "Weapon mentioned",
        r"\b(gun|pistol|revolver|rifle|knife|blade|acid|kerosene|petrol|"
        r"bandook|chaku|chhura|tezaab)\b"
        r"|बंदूक|चाकू|छुरा|तेज़ाब|तेजाब|पिस्तौल",
    ),
    (
        "self_harm",
        "Self-harm or suicide mentioned",
        r"\b(suicide|kill myself|end my life|hang myself|jaan\s*de\s*d(?:un|ung)a|"
        r"aatmahatya|atmahatya|khudkushi)\b"
        r"|आत्महत्या|ख़ुदकुशी|खुदकुशी|जान\s*दे\s*दूंगा",
    ),
    (
        "imminent_danger",
        "Imminent danger right now",
        r"\b(right now (?:they|he|she|we) (?:are|is) (?:coming|outside|here)|"
        r"they are (?:coming|breaking in)|abhi\s*aa\s*rahe\s*hain|ghar\s*ke\s*bahar\s*khade|"
        r"darwaza\s*tod)\b"
        r"|अभी\s*आ\s*रहे\s*हैं|दरवाज़ा\s*तोड़|दरवाजा\s*तोड़",
    ),
    (
        "sexual_violence",
        "Sexual violence disclosed",
        r"\b(rape|gang\s*rape|molest(?:ed|ation)?|sexual(?:ly)? assault(?:ed)?|balatkar|"
        r"chhedchhad|chedchad)\b"
        r"|बलात्कार|छेड़छाड़|यौन\s*हिंसा",
    ),
    (
        "violence_in_progress",
        "Physical violence reported",
        r"\b(beating (?:me|us|him|her)|they beat|peet\s*rahe|maar\s*rahe|"
        r"laathi|lathi charge|hamla)\b"
        r"|पीट\s*रहे|मार\s*रहे|हमला",
    ),
    (
        "child_at_risk",
        "Child at risk",
        r"\b(my (?:child|son|daughter|kids?) (?:is|are) (?:in danger|not safe|missing)|"
        r"bachche?\s*ko\s*(?:utha|maar))\b"
        r"|बच्चे\s*को\s*उठा|बच्चा\s*ख़तरे|बच्चा\s*खतरे",
    ),
]

_COMPILED = [(rid, label, re.compile(pat, re.IGNORECASE)) for rid, label, pat in RULES]


def check_safety_floor(transcript: str) -> Dict[str, object]:
    """Scan a transcript for explicit high-risk language.

    Returns the trigger flag plus every match with its span, so the UI can show
    the evidence rather than asking anyone to trust the flag.
    """
    text = transcript or ""
    matches: List[Dict[str, object]] = []

    for rule_id, label, pattern in _COMPILED:
        for m in pattern.finditer(text):
            matches.append(
                {
                    "rule_id": rule_id,
                    "label": label,
                    "matched_text": m.group(0).strip(),
                    "start": m.start(),
                    "end": m.end(),
                }
            )

    matches.sort(key=lambda x: x["start"])
    return {
        "triggered": bool(matches),
        "matches": matches,
        "rules_fired": sorted({m["rule_id"] for m in matches}),
    }
