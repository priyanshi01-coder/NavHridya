"""Speech to text for a call that is still happening.

Two transports, because they answer different questions:

  * `transcribe_chunk` - the browser records a few seconds at a time and POSTs
    each clip. The clip goes to Deepgram's pre-recorded endpoint when a Deepgram
    key is set, otherwise to the same Whisper endpoint the batch pipeline uses.
    Ordinary HTTPS, no extra packages, works on any host. Latency is the length
    of the clip plus one round trip - a couple of seconds, which reads as live.

  * `deepgram_stream` (in deepgram_stream.py) - a real WebSocket to Deepgram,
    audio in and partial transcripts out continuously, sub-second. Needs the
    `websockets` package and a Deepgram key.

The chunk path is what runs by default, because it needs nothing that is not
already installed. Both return the same shape, so nothing downstream cares which
one produced the text.

A real deployment would not use a microphone at all: the telephony layer
(Exotel, Twilio Media Streams, or the NHAA IVR itself) would feed call audio
into exactly this interface.
"""
from __future__ import annotations

import json
import os
import uuid
from typing import Any, Dict, Optional
from urllib import error, request

from . import providers

DEEPGRAM_REST = "https://api.deepgram.com/v1/listen"
DEEPGRAM_KEY_ENV = "DEEPGRAM_API_KEY"

# Deepgram's model for this work. nova-2 handles Hindi and code-mixed speech,
# which is what a 14566 caller actually speaks.
DEEPGRAM_MODEL = os.environ.get("DEEPGRAM_MODEL", "nova-2")


def deepgram_key() -> str:
    key = (os.environ.get(DEEPGRAM_KEY_ENV) or "").strip()
    return "" if key.lower() in providers.__dict__.get("PLACEHOLDERS", set()) else key


def engine_label(cfg: Dict[str, Any]) -> str:
    """What is actually going to transcribe, in words a person can check."""
    if deepgram_key():
        return f"deepgram:{DEEPGRAM_MODEL}"
    if cfg.get("api_key"):
        return f"{cfg['label']}:{cfg['asr_model']}"
    return ""


def available(cfg: Dict[str, Any]) -> bool:
    return bool(engine_label(cfg))


# --------------------------------------------------------------------------- #
# Deepgram, pre-recorded endpoint
# --------------------------------------------------------------------------- #
def _deepgram_chunk(audio: bytes, content_type: str) -> Dict[str, Any]:
    params = (f"model={DEEPGRAM_MODEL}&smart_format=true&punctuate=true"
              "&detect_language=true")
    req = request.Request(
        f"{DEEPGRAM_REST}?{params}",
        data=audio,
        headers={
            "Authorization": f"Token {deepgram_key()}",
            "Content-Type": content_type or "audio/webm",
            "User-Agent": providers.USER_AGENT,
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        raise providers.ProviderError(
            f"Deepgram refused the audio ({exc.code}): {body}", status=exc.code) from exc
    except error.URLError as exc:
        raise providers.ProviderError(f"Could not reach Deepgram ({exc.reason}).") from exc

    try:
        alt = data["results"]["channels"][0]["alternatives"][0]
        text = (alt.get("transcript") or "").strip()
        lang = (data["results"]["channels"][0].get("detected_language")
                or data.get("results", {}).get("channels", [{}])[0].get("language") or "")
    except (KeyError, IndexError, TypeError):
        text, lang = "", ""
    return {"text": text, "language": (lang or "").lower(), "engine": f"deepgram:{DEEPGRAM_MODEL}"}


# --------------------------------------------------------------------------- #
# Whisper, via whichever OpenAI-compatible provider is configured
# --------------------------------------------------------------------------- #
def _whisper_chunk(audio: bytes, filename: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Post one clip to /audio/transcriptions, in memory - nothing hits disk."""
    boundary = uuid.uuid4().hex
    parts = []

    def field(name: str, value: str) -> None:
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"'
                     f'\r\n\r\n{value}\r\n'.encode())

    field("model", cfg["asr_model"])
    # verbose_json carries the detected language, which the caller needs in
    # order to decide whether the text has to be translated
    field("response_format", "verbose_json")
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="{filename}"\r\nContent-Type: application/octet-stream\r\n\r\n'.encode())
    parts.append(audio)
    parts.append(f"\r\n--{boundary}--\r\n".encode())

    req = request.Request(
        f"{cfg['base_url']}/audio/transcriptions",
        data=b"".join(parts),
        headers={"Authorization": f"Bearer {cfg['api_key']}",
                 "Content-Type": f"multipart/form-data; boundary={boundary}",
                 "User-Agent": providers.USER_AGENT},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise providers.ProviderError(
            providers._friendly(exc.code, body), status=exc.code, raw=body) from exc
    except error.URLError as exc:
        raise providers.ProviderError(f"Could not reach the provider ({exc.reason}).") from exc

    return {
        "text": (data.get("text") or "").strip(),
        "language": (data.get("language") or "").lower(),
        "engine": f"{cfg['label']}:{cfg['asr_model']}",
    }


# --------------------------------------------------------------------------- #
# language rule
# --------------------------------------------------------------------------- #
HINDI_NAMES = {"hi", "hin", "hindi"}
ENGLISH_NAMES = {"en", "eng", "english", "en-us", "en-in", "en-gb"}


def _is_devanagari(text: str) -> bool:
    return any("ऀ" <= ch <= "ॿ" for ch in text)


def normalise_language(text: str, language: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Hindi stays Hindi. Anything that is not Hindi or English becomes English.

    The helpline's callers speak Hindi, English, and a constant mix of the two,
    and a counsellor reading the live transcript should see Hindi as Hindi -
    transliterating it would make it harder to read, not easier. A third
    language is translated, because the counsellor on this console cannot be
    assumed to read it.
    """
    lang = (language or "").lower().split("-")[0]
    if not text:
        return {"text": text, "language": lang, "translated": False}
    if lang in HINDI_NAMES or (not lang and _is_devanagari(text)):
        return {"text": text, "language": "hi", "translated": False}
    if lang in ENGLISH_NAMES or not lang:
        return {"text": text, "language": lang or "en", "translated": False}

    # some third language - render it in English for the counsellor
    try:
        out = providers.chat_json(
            "You translate helpline call transcripts into English. Return json of the "
            'form {"english": "<the translation>"} and nothing else. Translate faithfully, '
            "including any threat or distress, and do not soften or summarise.",
            f"Language: {lang}\n\nText:\n{text}",
            cfg=cfg,
        )
        english = (out.get("english") or "").strip()
    except Exception:                       # noqa: BLE001 - never kill a live call
        english = ""
    if not english:
        return {"text": text, "language": lang, "translated": False}
    return {"text": english, "language": lang, "translated": True}


# --------------------------------------------------------------------------- #
# the one entry point the live session uses
# --------------------------------------------------------------------------- #
def transcribe_chunk(audio: bytes, *, content_type: str, filename: str,
                     cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Transcribe one short clip. Raises ProviderError with a readable message."""
    if not audio:
        return {"text": "", "language": "", "engine": "", "translated": False}

    if deepgram_key():
        got = _deepgram_chunk(audio, content_type)
    elif cfg.get("api_key"):
        got = _whisper_chunk(audio, filename, cfg)
    else:
        raise providers.ProviderError(
            "Live transcription needs a speech-to-text key. Set DEEPGRAM_API_KEY for "
            "streaming, or GROQ_API_KEY / OPENAI_API_KEY to use Whisper on short clips.")

    fixed = normalise_language(got["text"], got["language"], cfg)
    return {"text": fixed["text"], "language": fixed["language"],
            "translated": fixed["translated"], "engine": got["engine"]}
