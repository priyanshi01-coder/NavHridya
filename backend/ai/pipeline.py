"""The one core flow, in the order the spec fixes it.

    audio -> transcript -> safety rules -> model analysis -> SVI -> stored case

The safety-rule step deliberately runs *before* the model and its result is
applied *after* the model, so no model output can talk the floor down.
"""
from __future__ import annotations

import time
from typing import Dict, Optional

from . import asr, nlp, providers
from .safety_rules import check_safety_floor
from .svi import compute_svi


def run_pipeline(
    *,
    audio_path: Optional[str],
    transcript_text: Optional[str],
    use_local_whisper: bool = False,
    local_whisper_model: str = "medium",
    cfg: Optional[Dict] = None,
) -> Dict:
    started = time.time()
    cfg = cfg or providers.resolve()

    # 1 + 2. transcript, from audio or pasted directly
    if transcript_text and transcript_text.strip():
        transcript = transcript_text.strip()
        asr_engine = "pasted-transcript"
    elif audio_path:
        got = asr.transcribe(audio_path, cfg, use_local_whisper, local_whisper_model)
        transcript = got["transcript"]
        asr_engine = got["engine"]
    else:
        raise ValueError("Provide either an audio file or a transcript.")

    if not transcript:
        raise ValueError("Transcription produced no text - the audio may be silent or unreadable.")

    # 3. deterministic safety floor, computed independently of the model
    safety = check_safety_floor(transcript)

    # 4. model analysis
    analysis = nlp.analyze_transcript(transcript, cfg)

    # 5. SVI arithmetic, in plain Python
    scored = compute_svi(
        distress_score=analysis["distress_score"],
        danger_score=analysis["danger_score"],
        indicators=analysis["indicators"],
        safety_floor_triggered=safety["triggered"],
    )

    # evidence the counsellor can check: indicator flags + every rule match
    evidence_spans = [
        {"type": "safety_rule", "label": m["label"], "text": m["matched_text"],
         "start": m["start"], "end": m["end"]}
        for m in safety["matches"]
    ]
    for key, on in analysis["indicators"].items():
        if on:
            evidence_spans.append({"type": "indicator", "label": key, "text": None,
                                   "start": None, "end": None})

    return {
        "transcript": transcript,
        "asr_engine": asr_engine,
        "nlp_engine": analysis["engine"],
        "engine_note": analysis.get("engine_note"),
        "summary": analysis["summary"],
        "distress_reasons": analysis["distress_reasons"],
        "danger_reasons": analysis["danger_reasons"],
        "recommendations": analysis["recommendations"],
        "indicators": analysis["indicators"],
        "safety_matches": safety["matches"],
        "safety_rules_fired": safety["rules_fired"],
        "evidence_spans": evidence_spans,
        "processing_seconds": round(time.time() - started, 3),
        **scored,
    }
