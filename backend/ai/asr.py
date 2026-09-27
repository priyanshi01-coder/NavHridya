"""Speech-to-text.

Three paths, tried in the order that gives a working demo soonest:
  1. an OpenAI-compatible API   - OpenAI Whisper, or Groq's whisper-large-v3
  2. local faster-whisper       - no network, set USE_LOCAL_WHISPER=true
  3. a pasted transcript        - lets the pipeline be demoed with no audio

Every path returns the same shape, including which engine produced it, so the
dashboard can always state where the text came from.
"""
from __future__ import annotations

from typing import Dict

from . import providers


def transcribe_with_api(path: str, cfg: Dict) -> Dict:
    text = providers.transcribe_audio(path, cfg=cfg)
    if not text:
        raise providers.ProviderError("The provider returned an empty transcript.")
    return {"transcript": text, "engine": f"{cfg['label']}:{cfg['asr_model']}"}


def transcribe_locally(path: str, model_size: str = "medium") -> Dict:
    """faster-whisper. First run downloads the model, so warm it up before a demo."""
    from faster_whisper import WhisperModel

    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, info = model.transcribe(path, beam_size=5)
    text = " ".join(seg.text.strip() for seg in segments).strip()
    return {
        "transcript": text,
        "engine": f"faster-whisper:{model_size}",
        "detected_language": getattr(info, "language", None),
    }


def transcribe(path: str, cfg: Dict, use_local: bool, local_model: str = "medium") -> Dict:
    if use_local:
        return transcribe_locally(path, local_model)

    if cfg.get("api_key"):
        try:
            return transcribe_with_api(path, cfg)
        except providers.ProviderError as exc:
            # fall back to local whisper if it happens to be installed
            try:
                out = transcribe_locally(path, local_model)
                out["engine"] += " (api failed)"
                return out
            except ImportError:
                raise RuntimeError(
                    f"{exc.message}\n\n"
                    "Audio needs a working transcription engine. Either fix the key/credits "
                    "above, set USE_LOCAL_WHISPER=true after `pip install faster-whisper`, "
                    "or switch to transcript mode, which needs neither."
                ) from exc

    raise RuntimeError(
        "No transcription engine is configured. Set an API key in .env, or "
        "USE_LOCAL_WHISPER=true with faster-whisper installed, or paste a transcript instead."
    )
