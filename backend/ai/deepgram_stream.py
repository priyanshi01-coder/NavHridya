"""True streaming transcription over Deepgram's WebSocket.

    browser mic -> raw PCM16 frames -> our /ws/live/{id} -> Deepgram -> text back

This is the low-latency path: audio goes out continuously in ~250ms frames and
interim text comes back in well under a second, instead of waiting for a whole
clip to finish. It is used only when DEEPGRAM_API_KEY is set and the
`websockets` package is installed; otherwise the app falls back to posting short
clips, which needs neither.

--------------------------------------------------------------------------
HONEST STATUS: this module has never been run against the real Deepgram
service. It was written from their streaming API documentation, but the author
had no Deepgram key and no network route to api.deepgram.com to test it with.
The clip-based path in live_asr.py *has* been tested end to end and is what runs
by default. If this path misbehaves, unset DEEPGRAM_API_KEY and the app returns
to the tested behaviour with no other change.
--------------------------------------------------------------------------

A real deployment would not read a microphone at all: the telephony layer in
front of NHAA 14566 (an IVR, or Exotel / Twilio Media Streams) would push call
audio into this same socket.
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, AsyncIterator, Dict, Optional
from urllib.parse import urlencode

DEEPGRAM_WS = "wss://api.deepgram.com/v1/listen"

# 16 kHz mono PCM16 is what the browser AudioWorklet produces and what Deepgram
# reads without transcoding, so nothing has to re-encode in between.
SAMPLE_RATE = 16000


def websockets_available() -> bool:
    try:
        import websockets  # noqa: F401
        return True
    except ImportError:
        return False


# Streaming is OFF in this build. The module is kept intact so the work can be
# finished later, but with this false nothing opens a socket to Deepgram, the
# /ws/live route declines immediately, and the UI is never told the option
# exists - so no Deepgram failure can reach a user. Set
# NAVHRIDYA_ENABLE_STREAMING=true to pick it back up.
def enabled() -> bool:
    return os.environ.get("NAVHRIDYA_ENABLE_STREAMING", "false").strip().lower() \
        in {"1", "true", "yes"}


def streaming_possible() -> bool:
    from . import live_asr
    return enabled() and bool(live_asr.deepgram_key()) and websockets_available()


def why_not() -> str:
    """Say plainly which piece is missing, rather than failing silently."""
    from . import live_asr
    if not enabled():
        return "Streaming is switched off in this build."
    if not live_asr.deepgram_key():
        return "DEEPGRAM_API_KEY is not set."
    if not websockets_available():
        return ("The `websockets` package is not installed, so the server cannot hold a "
                "WebSocket open. Run: pip install websockets")
    return ""


def _query(language: str = "") -> str:
    params = {
        "model": os.environ.get("DEEPGRAM_MODEL", "nova-2"),
        "encoding": "linear16",
        "sample_rate": str(SAMPLE_RATE),
        "channels": "1",
        "punctuate": "true",
        "smart_format": "true",
        "interim_results": "true",
        "endpointing": "300",
    }
    # Deepgram wants either a fixed language or automatic detection, not both.
    if language:
        params["language"] = language
    else:
        params["detect_language"] = "true"
    return urlencode(params)


class DeepgramStream:
    """One open socket to Deepgram for the duration of one call."""

    def __init__(self, api_key: str, language: str = ""):
        self.api_key = api_key
        self.language = language
        self._ws = None

    async def __aenter__(self) -> "DeepgramStream":
        import websockets

        self._ws = await websockets.connect(
            f"{DEEPGRAM_WS}?{_query(self.language)}",
            additional_headers={"Authorization": f"Token {self.api_key}"},
            max_size=None,
            ping_interval=5,
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._ws is not None:
            try:
                # tells Deepgram to flush and close cleanly rather than truncate
                await self._ws.send(json.dumps({"type": "CloseStream"}))
            except Exception:                       # noqa: BLE001
                pass
            try:
                await self._ws.close()
            except Exception:                       # noqa: BLE001
                pass
            self._ws = None

    async def send_audio(self, frame: bytes) -> None:
        if self._ws is not None and frame:
            await self._ws.send(frame)

    async def transcripts(self) -> AsyncIterator[Dict[str, Any]]:
        """Yield {text, is_final, language} as Deepgram produces them."""
        if self._ws is None:
            return
        async for raw in self._ws:
            if isinstance(raw, bytes):
                continue
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if msg.get("type") and msg.get("type") != "Results":
                continue
            try:
                alt = msg["channel"]["alternatives"][0]
            except (KeyError, IndexError, TypeError):
                continue
            text = (alt.get("transcript") or "").strip()
            if not text:
                continue
            yield {
                "text": text,
                "is_final": bool(msg.get("is_final") or msg.get("speech_final")),
                "language": (msg.get("channel", {}).get("detected_language")
                             or self.language or "").lower(),
            }


async def bridge(client_recv, client_send, session, cfg: Dict[str, Any],
                 *, on_final=None) -> None:
    """Pump audio from the browser into Deepgram and text back out.

    `client_recv()` awaits the next binary frame from the browser and returns
    None when it hangs up. `client_send(dict)` delivers a JSON message to it.
    `on_final(text, language)` is called for each finalised utterance so the
    caller can append it to the session and re-score.
    """
    from . import live_asr

    key = live_asr.deepgram_key()
    if not key:
        await client_send({"type": "error", "detail": why_not()})
        return

    async with DeepgramStream(key) as dg:

        async def pump_audio() -> None:
            while True:
                frame = await client_recv()
                if frame is None:
                    break
                await dg.send_audio(frame)

        async def pump_text() -> None:
            async for piece in dg.transcripts():
                await client_send({
                    "type": "transcript",
                    "text": piece["text"],
                    "is_final": piece["is_final"],
                    "language": piece["language"],
                })
                if piece["is_final"] and on_final is not None:
                    await on_final(piece["text"], piece["language"])

        audio_task = asyncio.create_task(pump_audio())
        text_task = asyncio.create_task(pump_text())
        done, pending = await asyncio.wait(
            {audio_task, text_task}, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            exc = task.exception()
            if exc:
                await client_send({"type": "error", "detail": f"Streaming stopped: {exc}"})
