"""OpenAI-compatible provider client, over plain HTTP.

Speaking the REST API directly instead of through a vendor SDK buys three
things: one less dependency to install, any OpenAI-compatible endpoint works
(OpenAI, Groq, Together, a local Ollama) by changing a base URL, and the whole
path is testable against a mock server.

Provider is chosen with AI_PROVIDER in .env; each has sensible defaults that
can be overridden per-key.
"""
from __future__ import annotations

import json
import mimetypes
import os
import uuid
from typing import Any, Dict, List, Optional
from urllib import error, request

PROVIDERS: Dict[str, Dict[str, str]] = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "key_env": "OPENAI_API_KEY",
        "asr_model": "whisper-1",
        "nlp_model": "gpt-4o-mini",
        "label": "openai",
    },
    "groq": {
        # Free tier, and OpenAI-compatible, so nothing else in the app changes.
        "base_url": "https://api.groq.com/openai/v1",
        "key_env": "GROQ_API_KEY",
        "asr_model": "whisper-large-v3",
        "nlp_model": "llama-3.3-70b-versatile",
        "label": "groq",
    },
}

DEFAULT_TIMEOUT = 120

# Groq (and several other providers) sit behind Cloudflare, which blocks a
# request whose User-Agent looks like a bare script - urllib sends
# "Python-urllib/3.x" by default and Cloudflare answers 403 with error code
# 1010 before the request ever reaches the API. Identifying ourselves properly
# is all it takes, so every request below goes out with these headers.
USER_AGENT = "NAVHRIDYA/3.0 (SIH 2026 prototype; +https://github.com/hacksmiths)"


def _headers(cfg: Dict[str, Any], content_type: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {cfg['api_key']}",
        "Content-Type": content_type,
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }


class ProviderError(RuntimeError):
    """Carries a message already written for a human, plus the raw detail."""

    def __init__(self, message: str, *, status: int | None = None, raw: str = ""):
        super().__init__(message)
        self.message = message
        self.status = status
        self.raw = raw


def resolve() -> Dict[str, Any]:
    """Work out which provider to use from the environment."""
    name = (os.environ.get("AI_PROVIDER") or "").strip().lower()
    if name not in PROVIDERS:
        # no explicit choice: use whichever key is actually present
        name = "groq" if os.environ.get("GROQ_API_KEY") else "openai"

    spec = PROVIDERS[name]
    key = (os.environ.get(spec["key_env"]) or "").strip()
    if key.lower() in {"", "your_key_here", "sk-...", "changeme"}:
        key = ""

    return {
        "name": name,
        "label": spec["label"],
        "api_key": key,
        "base_url": (os.environ.get("AI_BASE_URL") or spec["base_url"]).rstrip("/"),
        "asr_model": os.environ.get("ASR_MODEL") or spec["asr_model"],
        "nlp_model": os.environ.get("NLP_MODEL") or spec["nlp_model"],
    }


def _friendly(status: int, body: str) -> str:
    """Turn a provider error into something a person can act on."""
    detail = body
    try:
        parsed = json.loads(body)
        detail = parsed.get("error", {}).get("message") or body
    except (json.JSONDecodeError, AttributeError):
        pass

    low = detail.lower()
    if status == 403 and ("1010" in detail or "cloudflare" in low or "<html" in low):
        return ("The provider's CDN blocked the request before it reached the API "
                "(Cloudflare error 1010). This is not a problem with your key. Update to a "
                "build that sends a User-Agent header, or switch to transcript mode.")
    if status == 403:
        return (f"The provider refused the request ({detail}). If the key is new, it may not "
                "have access to this model yet.")
    if status == 400 and "json" in low and "response_format" in low:
        return ("The provider rejected the request because JSON mode needs the word "
                "'json' in the prompt. Update to a build that adds it automatically "
                "(this one does), or pick a different NLP_MODEL.")
    if status == 401:
        return f"The API key was rejected ({detail}). Check the key in your .env file."
    if status == 429 and ("quota" in low or "credit" in low or "billing" in low):
        return ("The account has no credits left, so the provider refused the request. "
                "Add credits, or switch to a free provider by putting "
                "AI_PROVIDER=groq and GROQ_API_KEY=... in your .env file.")
    if status == 429:
        return f"Rate limited by the provider ({detail}). Wait a few seconds and retry."
    if status == 404:
        return (f"The model was not found ({detail}). Set ASR_MODEL / NLP_MODEL in .env "
                "to a model your provider currently serves.")
    return f"Provider returned {status}: {detail}"


def _send(req: request.Request, timeout: int = DEFAULT_TIMEOUT) -> Dict[str, Any]:
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise ProviderError(_friendly(exc.code, body), status=exc.code, raw=body) from exc
    except error.URLError as exc:
        raise ProviderError(
            f"Could not reach the provider ({exc.reason}). Check your internet connection."
        ) from exc


# JSON mode has a rule that is easy to miss: the provider refuses the request
# with a 400 unless the word "json" appears somewhere in the messages. Groq
# enforces it strictly. Rather than relying on every caller to remember, the
# word is guaranteed here.
_JSON_NUDGE = "Respond with a single valid json object and nothing else."


def chat_json(system: str, user: str, *, cfg: Dict[str, Any]) -> Dict[str, Any]:
    """One chat completion, forced into JSON mode."""
    if "json" not in f"{system}\n{user}".lower():
        system = f"{system}\n\n{_JSON_NUDGE}".strip()

    payload = {
        "model": cfg["nlp_model"],
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
    }
    req = request.Request(
        f"{cfg['base_url']}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=_headers(cfg, "application/json"),
        method="POST",
    )
    data = _send(req)
    try:
        return json.loads(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        raise ProviderError(f"The model did not return usable JSON: {exc}") from exc


def transcribe_audio(path: str, *, cfg: Dict[str, Any]) -> str:
    """Multipart upload to the /audio/transcriptions endpoint."""
    boundary = uuid.uuid4().hex
    filename = os.path.basename(path)
    ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    with open(path, "rb") as fh:
        audio = fh.read()

    parts: list[bytes] = []
    def field(name: str, value: str) -> None:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n'
            f"{value}\r\n".encode()
        )

    field("model", cfg["asr_model"])
    field("response_format", "json")
    parts.append(
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; '
        f'filename="{filename}"\r\nContent-Type: {ctype}\r\n\r\n'.encode()
    )
    parts.append(audio)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    body = b"".join(parts)

    req = request.Request(
        f"{cfg['base_url']}/audio/transcriptions",
        data=body,
        headers=_headers(cfg, f"multipart/form-data; boundary={boundary}"),
        method="POST",
    )
    return (_send(req).get("text") or "").strip()


def list_models(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Ask the provider which models THIS key can actually use.

    Model names churn - providers retire them, and a new account is not always
    given access to every model on the public list. Rather than guessing a name
    that may already be wrong, this asks the account itself, so `--list-models`
    can print the real answer.
    """
    req = request.Request(
        f"{cfg['base_url']}/models",
        headers={"Authorization": f"Bearer {cfg['api_key']}",
                 "User-Agent": USER_AGENT, "Accept": "application/json"},
        method="GET",
    )
    data = _send(req, timeout=30)
    ids = sorted(str(m.get("id")) for m in (data.get("data") or []) if m.get("id"))
    audio = [m for m in ids if "whisper" in m or "distil" in m]
    chat = [m for m in ids if m not in audio and "tts" not in m and "guard" not in m]
    return {"all": ids, "chat": chat, "audio": audio}


def suggest_chat_model(models: List[str]) -> Optional[str]:
    """Pick a sensible analysis model out of whatever the account offers.

    Preference order, best instruction-follower first. Anything matching a hint
    beats anything that does not; within a hint, the first name wins.
    """
    hints = ("llama-3.3-70b", "llama-3.1-70b", "gpt-oss-120b", "gpt-oss-20b",
             "llama-4", "qwen3-32b", "qwen3", "llama-3.1-8b", "gemma2", "llama")
    for hint in hints:
        for m in models:
            if hint in m:
                return m
    return models[0] if models else None


def suggest_audio_model(models: List[str]) -> Optional[str]:
    for hint in ("whisper-large-v3-turbo", "whisper-large-v3", "whisper"):
        for m in models:
            if hint in m:
                return m
    return models[0] if models else None


def ping(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Cheapest possible call, to prove the key and the model both work."""
    if not cfg["api_key"]:
        return {"ok": False, "detail": f"No API key set ({PROVIDERS[cfg['name']]['key_env']})."}
    try:
        out = chat_json(
            'Reply with the json object {"ok": true} and nothing else.',
            "ping", cfg=cfg)
        return {"ok": True, "detail": f"{cfg['label']} / {cfg['nlp_model']} responded: {out}"}
    except ProviderError as exc:
        return {"ok": False, "detail": exc.message}
