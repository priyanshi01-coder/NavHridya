"""Distress / danger analysis.

Primary path: an OpenAI-compatible chat model in JSON mode with a strict schema.
Fallback path: a transparent lexicon scorer that runs with no key and no
network, so a demo never dies on stage wifi.

Whatever the source, the output is validated here before it reaches the
scoring engine: scores are clamped to 0-100, indicator flags are coerced to
booleans, and recommendations are filtered against the fixed list. A model
cannot invent a recommendation or push a score out of range.

Both paths must also return *reasons*: short evidence-bearing lines saying why
each axis scored what it scored. A number with no reason is not reviewable, and
a counsellor is the one who has to act on it.
"""
from __future__ import annotations

import json
import math
import re
from typing import Dict, List

from .svi import INDICATOR_KEYS, clamp

# The model may only ever choose from these, verbatim.
ALLOWED_RECOMMENDATIONS: List[str] = [
    "Immediate Counselling",
    "Legal Aid Support",
    "Police Intervention (if required)",
    "Medical Assistance",
    "Consider Witness Protection",
    "Follow-up within 24 hours",
]

RECOMMENDATION_BLURBS: Dict[str, str] = {
    "Immediate Counselling": "Connect with trained counsellor",
    "Legal Aid Support": "Provide information on legal options",
    "Police Intervention (if required)": "Escalate to local authorities",
    "Medical Assistance": "Share nearby healthcare resources",
    "Consider Witness Protection": "Evaluate need for anonymity support",
    "Follow-up within 24 hours": "Schedule automated check-in",
}

INDICATOR_LABELS: Dict[str, str] = {
    "fear": "Fear",
    "threat": "Threat",
    "high_stress": "High stress",
    "emotional_distress": "Emotional distress",
    "social_isolation": "Social isolation",
}

SYSTEM_PROMPT = """You are a clinical-style distress and risk triage assistant analyzing a transcript
of a helpline call from a victim who may be experiencing caste-based atrocity,
threats, or related distress. You do NOT give therapy - you only extract structured
signals for a human counsellor to review.

Given the transcript, return ONLY a JSON object with this exact shape:

{
  "distress_score": <integer 0-100>,
  "danger_score": <integer 0-100>,
  "distress_reasons": ["<short reason, quoting or paraphrasing the transcript>", ...],
  "danger_reasons": ["<short reason, quoting or paraphrasing the transcript>", ...],
  "indicators": {
    "fear": <true/false>,
    "threat": <true/false>,
    "high_stress": <true/false>,
    "emotional_distress": <true/false>,
    "social_isolation": <true/false>
  },
  "summary": "<2-3 sentence factual summary of what the caller reported>",
  "recommendations": ["<pick 1-4 from the fixed list provided>"]
}

Rules for the reason lists:
- 1 to 5 entries per axis, each under 20 words.
- Every entry must point at something actually said in the transcript. Quote the
  caller's own words where you can.
- If an axis scored low, say what was absent, e.g. "No threat of violence reported".
- Never write a reason that is not supported by the transcript.

Fixed recommendation list you must choose from (verbatim strings only):
["Immediate Counselling", "Legal Aid Support", "Police Intervention (if required)",
 "Medical Assistance", "Consider Witness Protection", "Follow-up within 24 hours"]

Be conservative and evidence-based - only mark an indicator true if the transcript
clearly supports it. Do not invent details not present in the transcript."""


# --------------------------------------------------------------------------- #
# validation
# --------------------------------------------------------------------------- #
def _clean_reasons(value, limit: int = 6) -> List[str]:
    """Coerce whatever arrived into a short list of clean one-line reasons."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    out: List[str] = []
    seen = set()
    for item in value:
        if isinstance(item, dict):
            item = item.get("reason") or item.get("text") or item.get("label") or ""
        text = " ".join(str(item).split()).strip(" -•")
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        out.append(text[:220])
        if len(out) >= limit:
            break
    return out


def validate_analysis(raw: Dict) -> Dict:
    """Coerce whatever came back into the exact shape the scorer expects."""
    indicators_raw = raw.get("indicators") or {}
    indicators = {k: bool(indicators_raw.get(k, False)) for k in INDICATOR_KEYS}

    recs_raw = raw.get("recommendations") or []
    if isinstance(recs_raw, str):
        recs_raw = [recs_raw]
    recommendations = [r for r in recs_raw if r in ALLOWED_RECOMMENDATIONS]
    # de-duplicate while preserving the model's ordering
    seen = set()
    recommendations = [r for r in recommendations if not (r in seen or seen.add(r))]

    summary = (raw.get("summary") or "").strip()
    if not summary:
        summary = "No summary was produced for this transcript."

    distress = int(round(clamp(_as_number(raw.get("distress_score")))))
    danger = int(round(clamp(_as_number(raw.get("danger_score")))))

    distress_reasons = _clean_reasons(raw.get("distress_reasons"))
    danger_reasons = _clean_reasons(raw.get("danger_reasons"))
    if not distress_reasons:
        distress_reasons = ["No specific distress cue was identified in the transcript."
                            if distress < 40 else
                            "Distress scored from the overall tone of the call."]
    if not danger_reasons:
        danger_reasons = ["No threat, weapon or violence was reported in the transcript."
                          if danger < 40 else
                          "Danger scored from the overall tone of the call."]

    return {
        "distress_score": distress,
        "danger_score": danger,
        "distress_reasons": distress_reasons,
        "danger_reasons": danger_reasons,
        "indicators": indicators,
        "summary": summary[:1200],
        "recommendations": recommendations[:4],
    }


def _as_number(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- #
# primary: OpenAI-compatible chat model
# --------------------------------------------------------------------------- #
def analyze_with_api(transcript: str, cfg: Dict) -> Dict:
    from . import providers

    data = providers.chat_json(SYSTEM_PROMPT, f"Transcript:\n\n{transcript}", cfg=cfg)
    out = validate_analysis(data)
    out["engine"] = f"{cfg['label']}:{cfg['nlp_model']}"
    return out


# --------------------------------------------------------------------------- #
# fallback: local lexicon scorer
# --------------------------------------------------------------------------- #
# (regex, weight, indicator flags raised, human label for the reason line)
_DISTRESS_CUES = [
    # --- direct emotional state -------------------------------------------
    (r"\b(scared|afraid|frightened|terrified|dar\s*lag|darr|dar\s*ga|ghabra)\w*", 20,
     ["fear"], "Caller states they are frightened"),
    (r"\b(crying|cry|cried|rone|ro\s*rah|ro\s*rahe|aansu|tears)\w*", 16,
     ["emotional_distress"], "Caller crying during the call"),
    (r"\b(can(?:no|\')?t sleep|sleepless|neend\s*nahi|insomnia)\w*", 14,
     ["high_stress"], "Sleep disturbance reported"),
    (r"\b(depress|anxiet|anxious|panic|ghabrahat|tension|tanav|tanaav)\w*", 16,
     ["high_stress", "emotional_distress"], "Anxiety or panic described"),
    (r"\b(stress|pareshan|bahut\s*dukh|takleef)\w*", 12,
     ["high_stress"], "Sustained stress or suffering described"),
    (r"\b(samajh\s*nahi\s*aa|don\'?t know what to do|kya\s*kar(?:oon|un))\b", 12,
     ["emotional_distress"], "Caller does not know what to do next"),

    # --- atrocity-specific: social boycott / untouchability ----------------
    (r"\b(boycott|bahishkar|social(?:ly)? excluded|outcast|shunned)\b", 22,
     ["social_isolation", "emotional_distress"], "Social boycott of the family reported"),
    (r"(baat\s*nahi\s*kart|koi\s*humse\s*baat|no one (?:talks|speaks) to us)", 20,
     ["social_isolation"], "Village has stopped speaking to the family"),
    (r"(alag\s*bitha|separate(?:ly)? seat|made to sit separately|chhua\s*chhut|untouchab)", 22,
     ["social_isolation", "emotional_distress"], "Untouchability practice or forced separation"),
    (r"(nal\s*pe\s*jaane\s*nahi|paani\s*nahi\s*(?:lene|bharne)|denied water|"
     r"dukaan\s*se\s*saman\s*nahi|refused to sell)", 20,
     ["social_isolation"], "Denied access to water or shops"),
    (r"(koi\s*(?:nahi\s*)?sunta\s*nahi|koi\s*nahi\s*sun|nobody (?:helps|listens)|"
     r"no one listens|helpless|hopeless)", 18,
     ["emotional_distress", "social_isolation"], "Caller feels no one is listening or helping"),
    (r"\b(alone|isolated|akela|akeli)\b", 14,
     ["social_isolation"], "Caller describes being alone"),
    (r"\b(humiliat|insult|abuse[ds]?|apmaan|beizzat|gaali|caste(?:ist)? slur|jaati\s*soochak)\w*",
     16, ["emotional_distress"], "Casteist abuse or humiliation reported"),
    (r"डर|रो\s*रह|अकेल|परेशान|तनाव|अपमान|बहिष्कार|छुआ\s*छूत", 18,
     ["fear", "emotional_distress"], "Distress expressed in Hindi (fear, crying, humiliation)"),
]

_DANGER_CUES = [
    # --- threat and intimidation ------------------------------------------
    (r"\b(threat(?:en|ened|ening)?|dhamki|dhamka|dhamkat)\w*", 26,
     ["threat", "fear"], "Explicit threats made against the caller"),
    (r"(dekh\s*lenge|anjaam\s*bhugat|you will regret|hum\s*chhodenge\s*nahi)", 22,
     ["threat", "fear"], "Veiled threat of consequences"),
    (r"(case\s*wapas|withdraw the (?:case|complaint)|complaint\s*wapas|"
     r"gawahi\s*(?:mat|nahi)|do not testify)", 24,
     ["threat"], "Pressure to withdraw the case or not testify"),
    (r"\b(follow(?:ing|ed) me|stalk|peecha\s*kar)\w*", 20,
     ["fear"], "Caller is being followed"),

    # --- violence ----------------------------------------------------------
    (r"\b(beat|beaten|assault|attack|hamla|peeta|peet\s*rah|maar\s*rah|maara|"
     r"khoon\s*nikal|blood)\w*", 30,
     ["threat"], "Physical assault reported"),
    (r"\b(burn|jala|set fire|aag\s*lag|acid)\w*", 32,
     ["threat"], "Arson or acid mentioned"),

    # --- land / livelihood coercion ----------------------------------------
    (r"(zameen|land\s*(?:grab|dispute)|plot|property|sign the papers|"
     r"kagaz\s*pe\s*sign|forcing (?:us|me)|majboor\s*kar)", 18,
     [], "Land or property coercion"),
    (r"(wages? (?:stopped|withheld)|majdoori\s*band|kaam\s*se\s*nikal|"
     r"stopped our (?:wages|pay)|nikal\s*diya\s*kaam)", 18,
     [], "Livelihood cut off as retaliation"),

    # --- institutional non-cooperation -------------------------------------
    (r"(fir\s*(?:nahi|abhi nahi|darj nahi)|police\s*(?:wale\s*)?(?:nahi|refus|won\'?t|"
     r"baad\s*mein)|did not (?:file|register) (?:the )?fir|complaint not registered)", 20,
     [], "FIR not registered or police not cooperating"),
    (r"(sarpanch\s*(?:nahi|will not)|panchayat\s*nahi\s*sun|will not listen)", 12,
     [], "Local authority refusing to act"),

    (r"धमक|हमला|मार|आग\s*लगा|पीछा|केस\s*वापस", 26,
     ["threat", "fear"], "Threat or violence described in Hindi"),
]


# Cue weights are additive, so a long transcript would otherwise run straight to
# 100. Saturating the total keeps the axis on a sane curve: a couple of strong
# cues land mid-range, and piling on more moves the needle less and less.
_DISTRESS_HALFPOINT = 58.0
_DANGER_HALFPOINT = 52.0


def _saturate(total: float, k: float) -> float:
    return 100.0 * (1.0 - math.exp(-total / k))


def _scan(lowered: str, cues, flags) -> tuple:
    total = 0
    reasons: List[str] = []
    for pattern, weight, marks, label in cues:
        match = re.search(pattern, lowered, re.IGNORECASE)
        if not match:
            continue
        total += weight
        for m in marks:
            flags[m] = True
        quote = " ".join(match.group(0).split())[:40]
        reasons.append(f'{label} (matched "{quote}", +{weight})')
    return total, reasons


def analyze_locally(transcript: str) -> Dict:
    text = transcript or ""
    lowered = text.lower()
    flags = {k: False for k in INDICATOR_KEYS}

    distress_raw, distress_reasons = _scan(lowered, _DISTRESS_CUES, flags)
    danger_raw, danger_reasons = _scan(lowered, _DANGER_CUES, flags)

    # length-aware floor: a long anguished call with no keyword hits still
    # carries some distress, but never enough to reach a high band on its own.
    if len(text.split()) > 40 and distress_raw < 18:
        distress_raw = 18
        distress_reasons.append("Long call with no specific cue - baseline distress applied (+18)")

    distress = clamp(_saturate(distress_raw, _DISTRESS_HALFPOINT))
    danger = clamp(_saturate(danger_raw, _DANGER_HALFPOINT))

    if distress_reasons:
        distress_reasons.append(
            f"Cue weight {distress_raw} scaled onto the 0-100 axis gives {round(distress)}")
    if danger_reasons:
        danger_reasons.append(
            f"Cue weight {danger_raw} scaled onto the 0-100 axis gives {round(danger)}")

    recs: List[str] = []
    if distress >= 40 or flags["emotional_distress"]:
        recs.append("Immediate Counselling")
    if danger >= 40 or flags["threat"]:
        recs.append("Police Intervention (if required)")
    if re.search(r"\b(fir|police|court|legal|kanoon|vakil|lawyer)\b", lowered):
        recs.append("Legal Aid Support")
    if re.search(r"\b(injur|hurt|wound|blood|hospital|chot|khoon)\w*", lowered):
        recs.append("Medical Assistance")
    if flags["social_isolation"] and len(recs) < 4:
        recs.append("Consider Witness Protection")
    if not recs or len(recs) < 4:
        recs.append("Follow-up within 24 hours")

    sentences = [s.strip() for s in re.split(r"(?<=[.!?।])\s+", text.strip()) if s.strip()]
    summary = " ".join(sentences[:2])[:400] or "Transcript too short to summarise."

    out = validate_analysis({
        "distress_score": distress,
        "danger_score": danger,
        "distress_reasons": distress_reasons,
        "danger_reasons": danger_reasons,
        "indicators": flags,
        "summary": summary,
        "recommendations": recs,
    })
    out["engine"] = "local-lexicon-fallback"
    return out


def analyze_transcript(transcript: str, cfg: Dict) -> Dict:
    """Use the model when a key is configured, otherwise the local scorer.

    A provider failure never kills the request - the case still gets scored, and
    the engine field says plainly that the model did not run.
    """
    if cfg.get("api_key"):
        try:
            return analyze_with_api(transcript, cfg)
        except Exception as exc:  # noqa: BLE001 - a demo must not die here
            reason = getattr(exc, "message", None) or type(exc).__name__
            out = analyze_locally(transcript)
            out["engine"] = "local-lexicon-fallback"
            out["engine_note"] = f"{cfg.get('label', 'api')} failed: {reason}"
            return out
    return analyze_locally(transcript)
