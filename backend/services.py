"""Business logic, framework independent.

Every route in app.py is a thin wrapper over one function here, so the same
logic runs whether the server is FastAPI or Starlette.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import secrets

from . import database as db
from . import security
from .ai import providers
from .ai.nlp import RECOMMENDATION_BLURBS
from .ai.pipeline import run_pipeline

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_DIR = os.path.join(ROOT, "data", "uploads")
ALLOWED_AUDIO = {".mp3", ".wav", ".m4a", ".ogg", ".webm", ".mp4", ".mpeg", ".mpga"}
ALLOWED_STATUS = {"Pending", "In Progress", "Resolved", "Escalated"}
ALLOWED_CHANNEL = {"Call", "Chat", "Portal", "Live Call"}

SEED_USERNAME = os.environ.get("SEED_ADMIN_USERNAME", "admin")
SEED_PASSWORD = os.environ.get("SEED_ADMIN_PASSWORD", "admin123")


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


# ------------------------------------------------------------------ settings
def config() -> Dict[str, Any]:
    """Resolve the provider plus the local-whisper switch into one dict."""
    cfg = providers.resolve()
    use_local = os.environ.get("USE_LOCAL_WHISPER", "false").lower() == "true"

    if cfg["api_key"]:
        mode = f"{cfg['label']} ({cfg['asr_model']} + {cfg['nlp_model']})"
    elif use_local:
        mode = "local whisper + local analyser"
    else:
        mode = "offline demo (transcript + local analyser)"

    cfg.update({
        "use_local_whisper": use_local,
        "local_whisper_model": os.environ.get("LOCAL_WHISPER_MODEL", "medium"),
        "ai_mode": mode,
    })
    return cfg


def ensure_seed_user() -> None:
    if db.count_users() == 0:
        db.create_user(SEED_USERNAME, security.hash_password(SEED_PASSWORD), "admin",
                       full_name="Helpline Supervisor",
                       email="supervisor@nhaa.gov.in")


def ensure_demo_cases() -> int:
    """Optionally score the bundled sample transcripts on a brand-new database.

    Off by default, and deliberately so: a counsellor opening this for the first
    time should see an empty console, not somebody else's cases. Nothing exists
    until they upload a call or load a sample themselves.

    Set SEED_DEMO_CASES=true in .env to pre-fill it before a demo. Even then the
    rows are not hardcoded - each transcript goes through the real pipeline, so
    the SVI, the reasons and the safety matches are genuinely computed.
    """
    if os.environ.get("SEED_DEMO_CASES", "false").strip().lower() not in {"1", "true", "yes"}:
        return 0
    user = db.get_user(SEED_USERNAME)
    if db.count_cases(user["id"] if user else None) > 0:
        return 0
    samples = sample_transcripts()
    if not samples:
        return 0
    user_id = user["id"] if user else None
    statuses = ["Pending", "In Progress", "Pending", "Pending", "Resolved"]
    made = 0
    for offset, sample in enumerate(samples):
        try:
            case = create_case(
                user_id=user_id,
                channel="Call",
                language="Hindi",
                transcript_text=sample["text"],
                audio_bytes=None,
                audio_name=None,
            )
        except ApiError:
            continue
        when = datetime.now(timezone.utc) - timedelta(days=offset, hours=2 * offset + 1)
        db.backdate_case(case["id"], when.isoformat())
        status = statuses[offset % len(statuses)]
        if status != "Pending":
            db.set_status(case["id"], status)
        made += 1
    return made


# ---------------------------------------------------------------------- auth
def login(username: str, password: str) -> Dict[str, Any]:
    user = db.get_user((username or "").strip())
    if not user or not security.verify_password(password or "", user["password_hash"]):
        raise ApiError("Invalid username or password", 401)
    return {"token": security.create_token(user["username"]),
            "user": _public_user(user)}


def _public_user(user) -> Dict[str, Any]:
    return {
        "id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "full_name": user["full_name"] or user["username"].title(),
        "email": user["email"] or "",
        "centre": user["centre"] or db.DEFAULT_CENTRE,
        "theme": user["theme"] or "light",
        "created_at": user["created_at"],
    }


def open_session() -> Dict[str, Any]:
    """Sign the caller straight in as the helpline's counsellor account.

    The deployed link opens the console rather than a sign-in wall, so anybody
    arriving without a session is put into the shared counsellor account. There
    are no throwaway guest accounts any more: one workspace, one case list, the
    same view for everyone who opens the link.

    This means the deployment is open - anyone with the URL can read and change
    the cases in it. That is a deliberate choice for a demo, and the reason the
    seeded password should be changed before the link is shared widely.
    """
    ensure_seed_user()
    user = db.get_user(SEED_USERNAME)
    if not user:
        raise ApiError("No counsellor account exists on this deployment.", 500)
    return {"token": security.create_token(user["username"]), "user": _public_user(user)}


def register(username: str, password: str, full_name: str = "",
             email: str = "") -> Dict[str, Any]:
    username = (username or "").strip().lower()
    if len(username) < 3:
        raise ApiError("Username must be at least 3 characters.")
    if not username.replace("_", "").replace(".", "").isalnum():
        raise ApiError("Username may contain letters, numbers, dots and underscores only.")
    if len(password or "") < 8:
        raise ApiError("Password must be at least 8 characters.")
    if db.get_user(username):
        raise ApiError("That username is already taken.", 409)
    email = (email or "").strip()
    if email and ("@" not in email or "." not in email.split("@")[-1]):
        raise ApiError("Enter a valid email address, or leave it blank.")

    db.create_user(username, security.hash_password(password), "counsellor",
                   full_name=(full_name or "").strip(), email=email)
    user = db.get_user(username)
    return {"token": security.create_token(username), "user": _public_user(user)}


def update_profile(user_id: int, **fields) -> Dict[str, Any]:
    if fields.get("theme") and fields["theme"] not in {"light", "dark"}:
        raise ApiError("Theme must be 'light' or 'dark'.")
    new_password = fields.pop("new_password", None)
    if new_password:
        if len(new_password) < 8:
            raise ApiError("New password must be at least 8 characters.")
        fields["password_hash"] = security.hash_password(new_password)
    db.update_user(user_id, **fields)
    return _public_user(db.get_user_by_id(user_id))


def delete_account(user_id: int, password: str) -> Dict[str, Any]:
    user = db.get_user_by_id(user_id)
    if not user:
        raise ApiError("Not authenticated", 401)
    if not security.verify_password(password or "", user["password_hash"]):
        raise ApiError("Enter your current password to delete the account.", 403)
    removed = db.delete_user(user_id)
    for name in removed["files"]:
        try:
            os.remove(os.path.join(UPLOAD_DIR, os.path.basename(str(name))))
        except OSError:
            pass
    return {"deleted": True, "cases_removed": removed["cases"],
            "recordings_removed": len(removed["files"])}


def current_user(auth_header: Optional[str]) -> Dict[str, Any]:
    token = ""
    if auth_header and auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    username = security.read_token(token)
    if not username:
        raise ApiError("Not authenticated", 401)
    user = db.get_user(username)
    if not user:
        raise ApiError("Not authenticated", 401)
    out = _public_user(user)
    out["ai_mode"] = config()["ai_mode"]
    return out


# --------------------------------------------------------------------- cases
def create_case(
    *,
    user_id: Optional[int],
    channel: str,
    language: str,
    transcript_text: Optional[str],
    audio_bytes: Optional[bytes],
    audio_name: Optional[str],
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not audio_bytes and not (transcript_text or "").strip():
        raise ApiError("Provide an audio file or a transcript.")

    saved_name = None
    saved_path = None
    if audio_bytes:
        suffix = os.path.splitext(audio_name or "")[1].lower()
        if suffix not in ALLOWED_AUDIO:
            raise ApiError(f"Unsupported audio type '{suffix or 'unknown'}'. "
                           f"Allowed: {', '.join(sorted(ALLOWED_AUDIO))}")
        os.makedirs(UPLOAD_DIR, exist_ok=True)
        saved_name = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f") + suffix
        saved_path = os.path.join(UPLOAD_DIR, saved_name)
        with open(saved_path, "wb") as fh:
            fh.write(audio_bytes)

    cfg = config()
    try:
        result = run_pipeline(
            audio_path=saved_path,
            transcript_text=transcript_text,
            use_local_whisper=cfg["use_local_whisper"],
            local_whisper_model=cfg["local_whisper_model"],
            cfg=cfg,
        )
    except (RuntimeError, ValueError) as exc:
        # A missing key, an unreadable file or a silent recording is the
        # caller's problem to fix, not a server fault - say so with a 400 and
        # the actual reason, rather than a 500 and a stack trace.
        raise ApiError(str(exc), 400) from exc
    except Exception as exc:  # surface the real reason, do not swallow it
        raise ApiError(f"Pipeline failed: {exc}", 500) from exc

    row = {
        "case_id": db.next_case_id(),
        "uploaded_by": user_id,
        "audio_filename": saved_name,
        "channel": channel or "Call",
        "language": language or "Hindi",
        "transcript": result["transcript"],
        "asr_engine": result["asr_engine"],
        "nlp_engine": result["nlp_engine"],
        "distress_score": result["distress_score"],
        "danger_score": result["danger_score"],
        "base_score": result["base_score"],
        "indicator_bonus": result["indicator_bonus"],
        "safety_floor_triggered": result["safety_floor_triggered"],
        "safety_floor_applied": result["safety_floor_applied"],
        "svi_score": result["svi_score"],
        "svi_category": result["svi_category"],
        "indicators": result["indicators"],
        "safety_matches": result["safety_matches"],
        "evidence_spans": result["evidence_spans"],
        "recommendations": result["recommendations"],
        "summary": result["summary"],
        "distress_reasons": result["distress_reasons"],
        "danger_reasons": result["danger_reasons"],
        "score_explanation": result["score_explanation"],
        "audio_original_name": audio_name,
        "audio_bytes": len(audio_bytes or b""),
        "audio_duration_seconds": audio_duration(saved_path),
        "status": "Pending",
        "processing_seconds": result["processing_seconds"],
        "engine_note": result.get("engine_note"),
    }
    row.update(extra or {})
    return db.insert_case(row)


def audio_duration(path: Optional[str]) -> float:
    """Seconds of audio, when it can be read without extra packages.

    WAV is read with the stdlib. Compressed formats return 0 and the browser's
    own audio element reports the length instead - no ffmpeg dependency.
    """
    if not path or not os.path.exists(path):
        return 0.0
    if path.lower().endswith(".wav"):
        try:
            import wave
            with wave.open(path, "rb") as fh:
                rate = fh.getframerate() or 1
                return round(fh.getnframes() / float(rate), 2)
        except Exception:
            return 0.0
    return 0.0


def audio_path_for(case: Dict[str, Any]) -> str:
    name = case.get("audio_filename")
    if not name:
        raise ApiError("This case has no audio attached.", 404)
    # never let a stored name escape the upload directory
    path = os.path.join(UPLOAD_DIR, os.path.basename(str(name)))
    if not os.path.exists(path):
        raise ApiError("The audio file for this case is no longer on disk.", 404)
    return path


def fetch_case(case_pk: int, user_id: Optional[int] = None) -> Dict[str, Any]:
    case = db.get_case(case_pk)
    if not case:
        raise ApiError("Case not found", 404)
    if user_id is not None and case["uploaded_by"] not in (None, user_id):
        # somebody else's call - indistinguishable from one that does not exist
        raise ApiError("Case not found", 404)
    if case.get("is_live_call"):
        case["snapshots"] = db.snapshots_for(case_pk)
    return case


# ----------------------------------------------------------------- live calls
def live_config() -> Dict[str, Any]:
    """What live transcription can actually do right now, stated plainly."""
    from .ai import live_asr

    from .ai import deepgram_stream

    cfg = config()
    engine = live_asr.engine_label(cfg)
    return {
        "available": bool(engine),
        # the engine name is internal detail - kept for our logs, not for the UI
        "engine_internal": engine,
        "streaming_possible": deepgram_stream.streaming_possible(),
        "note": (
            "The call is transcribed in short slices, so a line appears a couple of "
            "seconds after it is spoken."
            if engine else
            "Live transcription is not configured on this deployment, so a call "
            "cannot be transcribed right now."
        ),
    }


def start_live_call(user_id: Optional[int], channel: str = "Live Call",
                    language: str = "Hindi") -> Dict[str, Any]:
    from . import live

    if not live_config()["available"]:
        raise ApiError(live_config()["note"], 400)
    session = live.STORE.create(user_id, channel=channel or "Live Call",
                                language=language or "Hindi")
    out = session.state()
    out["live"] = live_config()
    return out


def push_live_audio(session_id: str, user_id: Optional[int], audio: bytes, *,
                    content_type: str, filename: str) -> Dict[str, Any]:
    """One clip in: transcribe it, apply the rules now, re-analyse if it is due."""
    from . import live
    from .ai import live_asr

    session = live.STORE.get(session_id, user_id)
    if not session:
        raise ApiError("That live call is not running any more.", 404)
    if session.ended:
        raise ApiError("That live call has already ended.", 400)

    cfg = config()
    try:
        got = live_asr.transcribe_chunk(audio, content_type=content_type,
                                        filename=filename, cfg=cfg)
    except Exception as exc:                    # noqa: BLE001
        message = getattr(exc, "message", None) or str(exc)
        raise ApiError(f"Live transcription failed: {message}", 502) from exc

    segment = session.add_segment(got["text"], language=got["language"],
                                  translated=got["translated"], engine=got["engine"])
    # the model only re-reads the call when it is worth re-reading
    session.run_analysis(cfg)

    out = session.state()
    out["segment"] = segment
    return out


def live_state(session_id: str, user_id: Optional[int]) -> Dict[str, Any]:
    from . import live

    session = live.STORE.get(session_id, user_id)
    if not session:
        raise ApiError("That live call is not running any more.", 404)
    return session.state()


def end_live_call(session_id: str, user_id: Optional[int]) -> Dict[str, Any]:
    """Stop the call and run the ordinary pipeline once over the whole thing.

    The live numbers were a running estimate. What gets saved is a full pass over
    the complete transcript - the same code path an uploaded recording takes - so
    a live case and an uploaded case mean the same thing.
    """
    from . import live

    session = live.STORE.get(session_id, user_id)
    if not session:
        raise ApiError("That live call is not running any more.", 404)

    transcript = session.transcript.strip()
    session.ended = True
    duration = round(time.monotonic() - session.started_mono, 1)
    if not transcript:
        live.STORE.drop(session_id)
        raise ApiError("Nothing was transcribed during that call, so there is no case "
                       "to save. Check the microphone and try again.", 400)

    case = create_case(
        user_id=session.user_id,
        channel=session.channel,
        language=session.language,
        transcript_text=transcript,
        audio_bytes=None,
        audio_name=None,
        extra={"is_live_call": True, "live_duration_seconds": duration},
    )
    db.add_snapshots(case["id"], session.snapshots)
    case["snapshots"] = db.snapshots_for(case["id"])
    live.STORE.drop(session_id)
    return case


def update_status(case_pk: int, status: str, user_id: Optional[int] = None) -> Dict[str, Any]:
    if status not in ALLOWED_STATUS:
        raise ApiError(f"status must be one of {', '.join(sorted(ALLOWED_STATUS))}")
    fetch_case(case_pk, user_id)          # 404s if it is not theirs
    case = db.set_status(case_pk, status)
    if not case:
        raise ApiError("Case not found", 404)
    return case


def dashboard_stats(user_id: Optional[int] = None) -> Dict[str, Any]:
    out = db.stats(user_id)
    out["ai_mode"] = config()["ai_mode"]
    return out


def recommendation_catalog():
    return [{"title": k, "blurb": v} for k, v in RECOMMENDATION_BLURBS.items()]


def sample_transcripts():
    folder = os.path.join(ROOT, "samples")
    if not os.path.isdir(folder):
        return []
    out = []
    for name in sorted(os.listdir(folder)):
        if name.endswith(".txt"):
            with open(os.path.join(folder, name), encoding="utf-8") as fh:
                out.append({"name": name, "text": fh.read().strip()})
    return out
