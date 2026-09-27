"""Live call sessions.

A call that is still in progress is held in memory: the transcript so far, the
latest scores, and the snapshots taken along the way. Nothing here re-implements
the scoring - it calls the same safety-rule engine, the same analysis prompt and
the same SVI arithmetic the batch pipeline uses, so a live score and an uploaded
score mean exactly the same thing.

Two cadences, on purpose:

  * The deterministic safety rules run on **every** segment the moment it
    arrives. They are regex over text, they cost nothing, and an explicit threat
    should raise the floor immediately - not up to ten seconds later.

  * The language-model analysis runs at most every ANALYSIS_INTERVAL seconds,
    and only when new words have arrived. Re-analysing on every word would be
    slow, expensive and jittery, and would not make the number any truer.

When the call ends, the full transcript goes through the ordinary pipeline once
more and that result - not the last live snapshot - is what gets saved. The live
numbers are a running estimate; the saved case is the considered answer.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .ai import nlp
from .ai.safety_rules import check_safety_floor
from .ai.svi import compute_svi

# How often the model may be asked to re-read the call so far. Twelve seconds
# keeps the cost and the jitter down while still feeling live; a demo can
# tighten it with NAVHRIDYA_LIVE_INTERVAL.
ANALYSIS_INTERVAL = float(os.environ.get("NAVHRIDYA_LIVE_INTERVAL", "12"))
# ...unless this much new speech has arrived, which usually means something
# happened and waiting out the rest of the interval would be the wrong call.
ANALYSIS_ON_NEW_CHARS = 220
# ...and the very first pass waits only for one real sentence.
FIRST_ANALYSIS_CHARS = 25
# A session nobody has touched for this long is abandoned; drop it.
SESSION_TTL = 60 * 60


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LiveSession:
    """One call in progress."""

    def __init__(self, session_id: str, user_id: Optional[int], *,
                 channel: str = "Live Call", language: str = "Hindi"):
        self.id = session_id
        self.user_id = user_id
        self.channel = channel
        self.language = language
        self.started_at = _now()
        self.started_mono = time.monotonic()
        self.ended = False

        self.segments: List[Dict[str, Any]] = []
        self.transcript = ""
        self.asr_engine = ""
        self.nlp_engine = ""
        self.engine_note: Optional[str] = None

        self.analysis: Dict[str, Any] = {
            "distress_score": 0, "danger_score": 0,
            "distress_reasons": [], "danger_reasons": [],
            "indicators": {}, "summary": "", "recommendations": [],
        }
        self.scored: Dict[str, Any] = compute_svi(0, 0, {}, False)
        self.safety: Dict[str, Any] = {"triggered": False, "matches": [], "rules_fired": []}
        self.snapshots: List[Dict[str, Any]] = []

        self._lock = threading.Lock()
        self._last_analysis_at = 0.0
        self._chars_at_last_analysis = 0
        self._analysing = False

    # ------------------------------------------------------------ transcript
    def add_segment(self, text: str, *, language: str = "", translated: bool = False,
                    engine: str = "") -> Dict[str, Any]:
        """Append one transcribed clip and re-run the cheap, instant checks."""
        text = " ".join((text or "").split())
        with self._lock:
            if engine:
                self.asr_engine = engine
            if text:
                seg = {
                    "text": text,
                    "language": language,
                    "translated": translated,
                    "at": round(self.elapsed(), 1),
                    "clock": _now(),
                }
                self.segments.append(seg)
                self.transcript = (self.transcript + " " + text).strip()
            else:
                seg = None

            # Deterministic rules, every single time. This is the part that must
            # not wait for the model.
            self.safety = check_safety_floor(self.transcript)
            self._rescore()
        return seg or {}

    def _rescore(self) -> None:
        """Recompute the SVI from whatever the model last said plus the rules."""
        self.scored = compute_svi(
            distress_score=self.analysis.get("distress_score", 0),
            danger_score=self.analysis.get("danger_score", 0),
            indicators=self.analysis.get("indicators", {}),
            safety_floor_triggered=self.safety.get("triggered", False),
        )

    # -------------------------------------------------------------- analysis
    def analysis_is_due(self) -> bool:
        if self.ended or self._analysing or not self.transcript:
            return False
        grown = len(self.transcript) - self._chars_at_last_analysis
        if grown <= 0:
            return False
        if self._last_analysis_at == 0.0:
            # The first pass should happen as soon as there is a real sentence to
            # read - a caller who says one frightening line and stops must still
            # be scored - but not on a two-word fragment.
            return grown >= FIRST_ANALYSIS_CHARS or self.elapsed() >= ANALYSIS_INTERVAL
        elapsed = time.monotonic() - self._last_analysis_at
        return elapsed >= ANALYSIS_INTERVAL or grown >= ANALYSIS_ON_NEW_CHARS

    def elapsed(self) -> float:
        return time.monotonic() - self.started_mono

    def run_analysis(self, cfg: Dict[str, Any]) -> bool:
        """Ask the model to re-read the call so far. Returns True if it ran."""
        with self._lock:
            if not self.analysis_is_due():
                return False
            self._analysing = True
            transcript = self.transcript
        try:
            out = nlp.analyze_transcript(transcript, cfg)
        except Exception as exc:                 # noqa: BLE001 - a live call must not die
            with self._lock:
                self._analysing = False
                self.engine_note = f"analysis failed: {exc}"
            return False

        with self._lock:
            self.analysis = out
            self.nlp_engine = out.get("engine", "")
            self.engine_note = out.get("engine_note")
            self._last_analysis_at = time.monotonic()
            self._chars_at_last_analysis = len(transcript)
            self._analysing = False
            self._rescore()
            self.snapshots.append({
                "at": round(time.monotonic() - self.started_mono, 1),
                "clock": _now(),
                "distress_score": self.scored["distress_score"],
                "danger_score": self.scored["danger_score"],
                "safety_floor_triggered": self.scored["safety_floor_triggered"],
                "svi_score": self.scored["svi_score"],
                "svi_category": self.scored["svi_category"],
            })
        return True

    # ----------------------------------------------------------------- state
    def state(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "session_id": self.id,
                "started_at": self.started_at,
                "elapsed_seconds": round(self.elapsed(), 1),
                "ended": self.ended,
                "channel": self.channel,
                "language": self.language,
                "transcript": self.transcript,
                "segments": self.segments[-80:],
                "asr_engine": self.asr_engine,
                "nlp_engine": self.nlp_engine,
                "engine_note": self.engine_note,
                "summary": self.analysis.get("summary", ""),
                "recommendations": self.analysis.get("recommendations", []),
                "distress_reasons": self.analysis.get("distress_reasons", []),
                "danger_reasons": self.analysis.get("danger_reasons", []),
                "indicators": self.analysis.get("indicators", {}),
                "safety_matches": self.safety.get("matches", []),
                "safety_rules_fired": self.safety.get("rules_fired", []),
                "snapshots": self.snapshots,
                "analysed_once": self._last_analysis_at > 0,
                **self.scored,
            }


class SessionStore:
    """In-memory, per-process. A live call is short and does not outlive a run."""

    def __init__(self) -> None:
        self._sessions: Dict[str, LiveSession] = {}
        self._lock = threading.Lock()

    def create(self, user_id: Optional[int], **kw) -> LiveSession:
        self._sweep()
        session = LiveSession(uuid.uuid4().hex, user_id, **kw)
        with self._lock:
            self._sessions[session.id] = session
        return session

    def get(self, session_id: str, user_id: Optional[int] = None) -> Optional[LiveSession]:
        with self._lock:
            session = self._sessions.get(session_id)
        if not session:
            return None
        if user_id is not None and session.user_id not in (None, user_id):
            return None                      # somebody else's call
        return session

    def drop(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def _sweep(self) -> None:
        cutoff = time.monotonic() - SESSION_TTL
        with self._lock:
            for sid in [s.id for s in self._sessions.values() if s.started_mono < cutoff]:
                self._sessions.pop(sid, None)


STORE = SessionStore()
