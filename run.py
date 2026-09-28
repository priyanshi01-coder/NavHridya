#!/usr/bin/env python3
"""NAVHRIDYA prototype launcher.

    python run.py                 # http://127.0.0.1:8000
    python run.py --port 8010     # if 8000 is already taken
"""
from __future__ import annotations

import argparse
import os
import socket
import sys

VERSION = "5.1"          # bumped whenever this file changes - check it on startup
BUILD = "2026-09-28b"

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def port_is_free(host: str, port: int) -> bool:
    """True when nothing is listening on the port.

    Checked by trying to connect rather than to bind: on Windows a bind test
    with SO_REUSEADDR succeeds even when the port is already taken, which made
    this report a busy port as free.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex((host, port)) != 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--reload", action="store_true")
    ap.add_argument("--check-ai", action="store_true",
                    help="call the provider once and report whether it works, then exit")
    ap.add_argument("--list-models", action="store_true",
                    help="print the models your API key can actually use, then exit")
    args = ap.parse_args()

    from backend.ai import providers
    from backend.services import config

    if args.list_models or args.check_ai:
        cfg = config()
        print(f"\n  NAVHRIDYA v{VERSION} ({BUILD})")
        print(f"  provider  : {cfg['label']}")
        print(f"  base url  : {cfg['base_url']}")
        print(f"  models    : {cfg['asr_model']} (audio) / {cfg['nlp_model']} (analysis)")
        print(f"  api key   : {'set' if cfg['api_key'] else 'NOT SET'}")

    if args.list_models:
        if not cfg["api_key"]:
            sys.exit("\n  No API key is set, so there is nothing to list.\n")
        try:
            found = providers.list_models(cfg)
        except Exception as exc:
            sys.exit(f"\n  Could not list models: "
                     f"{getattr(exc, 'message', None) or exc}\n")
        print(f"\n  Models this key can use ({len(found['all'])} in total)\n")
        print("  For the analysis (put one of these in .env as NLP_MODEL):")
        for m in found["chat"]:
            print(f"    {m}")
        print("\n  For audio transcription (ASR_MODEL):")
        for m in found["audio"] or ["  (none - this provider offers no speech-to-text)"]:
            print(f"    {m}")
        nlp = providers.suggest_chat_model(found["chat"])
        asr = providers.suggest_audio_model(found["audio"])
        print("\n  Suggested - copy these two lines into your .env file:\n")
        if nlp:
            print(f"    NLP_MODEL={nlp}")
        if asr:
            print(f"    ASR_MODEL={asr}")
        print("\n  Then:  python run.py --check-ai\n")
        sys.exit(0)

    if args.check_ai:
        result = providers.ping(cfg)
        print(f"\n  {'WORKING' if result['ok'] else 'NOT WORKING'}: {result['detail']}")
        if not result["ok"] and "not found" in result["detail"].lower():
            # the configured model is gone or not granted to this key - say
            # which ones are, instead of leaving them to guess
            try:
                found = providers.list_models(cfg)
                nlp = providers.suggest_chat_model(found["chat"])
                asr = providers.suggest_audio_model(found["audio"])
                print("\n  Your key does have access to these, though. Put this in .env:\n")
                if nlp:
                    print(f"    NLP_MODEL={nlp}")
                if asr:
                    print(f"    ASR_MODEL={asr}")
                print("\n  Full list:  python run.py --list-models")
            except Exception:
                print("\n  See the full list with:  python run.py --list-models")
        print()
        sys.exit(0 if result["ok"] else 1)

    try:
        import uvicorn
    except ImportError:
        sys.exit("uvicorn is not installed.  Run:  pip install -r requirements.txt")

    from backend import config as cfgmod
    from backend.app import HAVE_FASTAPI

    # find a free port rather than dying on "address already in use"
    port = args.port
    if not port_is_free(args.host, port):
        for candidate in range(args.port + 1, args.port + 21):
            if port_is_free(args.host, candidate):
                print(f"\n  Port {args.port} is already in use "
                      f"(an earlier run is probably still open) - using {candidate} instead.")
                port = candidate
                break
        else:
            sys.exit(f"Ports {args.port}-{args.port + 20} are all busy. "
                     f"Close the other server, or pass --port <free port>.")

    cfg = config()
    env_file = os.path.join(HERE, ".env")

    print(f"\n  NAVHRIDYA v{VERSION} ({BUILD}) - assessment layer for NHAA 14566")
    print(f"  server    : {'FastAPI' if HAVE_FASTAPI else 'Starlette (FastAPI not installed)'}")
    print(f"  .env      : {'loaded ' + str(cfgmod.LOADED) if cfgmod.LOADED else 'not found or empty'}")
    print(f"  AI mode   : {cfg['ai_mode']}")
    if not cfg["api_key"] and not cfg["use_local_whisper"]:
        print("              ^ no API key, so audio upload is off and the analysis")
        print("                uses the local lexicon, not a language model.")
        if not os.path.exists(env_file):
            print(f"                Create {env_file} with:  OPENAI_API_KEY=sk-...")
        print("                Free alternative: AI_PROVIDER=groq + GROQ_API_KEY=gsk_...")
    else:
        print("              verify it with:  python run.py --check-ai")
    print(f"  dashboard : http://{args.host}:{port}")
    print(f"  public site: http://{args.host}:{port}/home")
    print("  sign in   : admin / admin123  (the link itself needs no account)\n")

    uvicorn.run("backend.app:app", host=args.host, port=port, reload=args.reload)


if __name__ == "__main__":
    main()
