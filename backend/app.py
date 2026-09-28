"""HTTP layer.

Runs on FastAPI when it is installed - the stack named in the PPT - and falls
back to Starlette, which is the exact ASGI machinery FastAPI is built on, so the
prototype starts with no installation step. Both paths serve identical routes
and call the same `services` functions.
"""
from __future__ import annotations

import json
import os

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route, WebSocketRoute
from starlette.staticfiles import StaticFiles

import asyncio

from . import database as db
from . import live
from . import security
from . import services as sv
from .ai import live_asr
from .services import ApiError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND = os.path.join(ROOT, "frontend")

try:
    import fastapi  # noqa: F401
    HAVE_FASTAPI = True
except Exception:
    HAVE_FASTAPI = False


def _err(exc: ApiError) -> JSONResponse:
    return JSONResponse({"detail": exc.message}, status_code=exc.status)


SESSION_COOKIE = "nav_session"


def _user(request):
    """Authenticate from the Authorization header, or the session cookie.

    The cookie exists for one reason: a browser <audio> element cannot send an
    Authorization header, so the recording endpoint would be unreachable from
    the player. Keeping the token in an HttpOnly cookie is safer than putting
    it in the URL, where it would end up in logs and history.
    """
    header = request.headers.get("authorization")
    if not header:
        token = request.cookies.get(SESSION_COOKIE)
        if token:
            header = "Bearer " + token
    return sv.current_user(header)


def _with_session(payload: dict, status: int = 200) -> JSONResponse:
    res = JSONResponse(payload, status_code=status)
    token = payload.get("token")
    if token:
        res.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax",
                       path="/", max_age=security.TOKEN_TTL_SECONDS)
    return res


async def _json_body(request) -> dict:
    try:
        return await request.json()
    except Exception:
        return {}


# ------------------------------------------------------------------ pages
def _page(name: str):
    async def handler(request):
        return FileResponse(os.path.join(FRONTEND, name))
    return handler


page_home = _page("index.html")     # the public site, at /home
page_auth = _page("auth.html")
page_app = _page("app.html")        # the console, and what "/" now serves


# ------------------------------------------------------------------- auth
async def api_login(request):
    body = await _json_body(request)
    try:
        return _with_session(sv.login(body.get("username", ""), body.get("password", "")))
    except ApiError as exc:
        return _err(exc)


async def api_register(request):
    body = await _json_body(request)
    try:
        return _with_session(sv.register(
            body.get("username", ""), body.get("password", ""),
            body.get("full_name", ""), body.get("email", "")), 201)
    except ApiError as exc:
        return _err(exc)


async def api_session(request):
    """Sign the caller in as the counsellor account, with no form to fill.

    What makes the deployed link open straight onto the dashboard.
    """
    return _with_session(sv.open_session(), 201)


async def api_logout(request):
    res = JSONResponse({"ok": True})
    res.delete_cookie(SESSION_COOKIE, path="/")
    return res


async def api_me(request):
    try:
        return JSONResponse(_user(request))
    except ApiError as exc:
        return _err(exc)


async def api_me_update(request):
    try:
        user = _user(request)
        body = await _json_body(request)
        fields = {k: body[k] for k in ("full_name", "email", "centre", "theme", "new_password")
                  if k in body}
        return JSONResponse(sv.update_profile(user["id"], **fields))
    except ApiError as exc:
        return _err(exc)


async def api_me_delete(request):
    try:
        user = _user(request)
        body = await _json_body(request)
        out = sv.delete_account(user["id"], str(body.get("password", "")))
        res = JSONResponse(out)
        res.delete_cookie(SESSION_COOKIE, path="/")
        return res
    except ApiError as exc:
        return _err(exc)


# ------------------------------------------------------------------ cases
async def api_upload(request):
    try:
        user = _user(request)
    except ApiError as exc:
        return _err(exc)

    form = await request.form()
    upload = form.get("audio_file")
    audio_bytes = None
    audio_name = None
    if upload is not None and hasattr(upload, "read"):
        audio_name = getattr(upload, "filename", None)
        if audio_name:
            audio_bytes = await upload.read()

    try:
        case = sv.create_case(
            user_id=user["id"],
            channel=str(form.get("channel") or "Call"),
            language=str(form.get("language") or "Hindi"),
            transcript_text=str(form.get("transcript_text") or "") or None,
            audio_bytes=audio_bytes,
            audio_name=audio_name,
        )
        return JSONResponse(case, status_code=201)
    except ApiError as exc:
        return _err(exc)


async def api_cases(request):
    try:
        user = _user(request)
        return JSONResponse(db.list_cases(user_id=user["id"]))
    except ApiError as exc:
        return _err(exc)


async def api_case(request):
    try:
        user = _user(request)
        return JSONResponse(sv.fetch_case(int(request.path_params["case_pk"]), user["id"]))
    except ApiError as exc:
        return _err(exc)


async def api_pending(request):
    try:
        user = _user(request)
        return JSONResponse(db.pending_cases(user_id=user["id"]))
    except ApiError as exc:
        return _err(exc)


async def api_case_audio(request):
    """Stream the stored recording back so Reports can play it in the browser."""
    try:
        _user(request)
        case = sv.fetch_case(int(request.path_params["case_pk"]))
        path = sv.audio_path_for(case)
    except ApiError as exc:
        return _err(exc)
    ext = os.path.splitext(path)[1].lower()
    media = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".m4a": "audio/mp4",
             ".ogg": "audio/ogg", ".webm": "audio/webm", ".mp4": "audio/mp4",
             ".mpeg": "audio/mpeg", ".mpga": "audio/mpeg"}.get(ext, "application/octet-stream")
    return FileResponse(path, media_type=media,
                        filename=case.get("audio_original_name") or os.path.basename(path))


async def api_case_delete(request):
    try:
        user = _user(request)
        case_pk = int(request.path_params["case_pk"])
        sv.fetch_case(case_pk, user["id"])
        name = db.delete_case(case_pk)
    except ApiError as exc:
        return _err(exc)
    if name:
        try:
            os.remove(os.path.join(sv.UPLOAD_DIR, os.path.basename(str(name))))
        except OSError:
            pass
    return JSONResponse({"deleted": True})


async def api_case_status(request):
    try:
        user = _user(request)
        body = await _json_body(request)
        return JSONResponse(sv.update_status(int(request.path_params["case_pk"]),
                                             str(body.get("status", "")), user["id"]))
    except ApiError as exc:
        return _err(exc)


# ------------------------------------------------------------- live calls
async def api_live_config(request):
    try:
        _user(request)
        return JSONResponse(sv.live_config())
    except ApiError as exc:
        return _err(exc)


async def api_live_start(request):
    try:
        user = _user(request)
        body = await _json_body(request)
        return JSONResponse(sv.start_live_call(
            user["id"], str(body.get("channel") or "Live Call"),
            str(body.get("language") or "Hindi")), status_code=201)
    except ApiError as exc:
        return _err(exc)


async def api_live_chunk(request):
    """One short clip of the call that is happening right now."""
    try:
        user = _user(request)
    except ApiError as exc:
        return _err(exc)

    form = await request.form()
    upload = form.get("audio")
    audio, name, ctype = b"", "chunk.webm", "audio/webm"
    if upload is not None and hasattr(upload, "read"):
        audio = await upload.read()
        name = getattr(upload, "filename", None) or name
        ctype = getattr(upload, "content_type", None) or ctype

    try:
        return JSONResponse(sv.push_live_audio(
            str(request.path_params["session_id"]), user["id"], audio,
            content_type=ctype, filename=name))
    except ApiError as exc:
        return _err(exc)


async def api_live_state(request):
    try:
        user = _user(request)
        return JSONResponse(sv.live_state(str(request.path_params["session_id"]), user["id"]))
    except ApiError as exc:
        return _err(exc)


async def api_live_end(request):
    try:
        user = _user(request)
        return JSONResponse(sv.end_live_call(
            str(request.path_params["session_id"]), user["id"]), status_code=201)
    except ApiError as exc:
        return _err(exc)


async def ws_live(websocket):
    """Stream microphone audio straight through to Deepgram.

    Only reachable when DEEPGRAM_API_KEY is set and `websockets` is installed;
    the frontend asks /api/live/config first and falls back to posting short
    clips when this is not available. See deepgram_stream.py - this path has not
    been exercised against the real Deepgram service.
    """
    from .ai import deepgram_stream

    await websocket.accept()
    try:
        if not deepgram_stream.streaming_possible():
            await websocket.send_json({"type": "error",
                                       "detail": deepgram_stream.why_not()})
            await websocket.close()
            return

        token = websocket.query_params.get("token", "")
        try:
            user = sv.current_user(f"Bearer {token}" if token else None)
        except ApiError as exc:
            await websocket.send_json({"type": "error", "detail": exc.message})
            await websocket.close()
            return

        session = live.STORE.get(str(websocket.path_params["session_id"]), user["id"])
        if not session:
            await websocket.send_json({"type": "error",
                                       "detail": "That live call is not running any more."})
            await websocket.close()
            return

        cfg = sv.config()

        async def client_recv():
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                return None
            return message.get("bytes") or None

        async def client_send(payload):
            await websocket.send_json(payload)

        async def on_final(text, language):
            fixed = live_asr.normalise_language(text, language, cfg)
            session.add_segment(fixed["text"], language=fixed["language"],
                                translated=fixed["translated"],
                                engine=f"deepgram:{deepgram_stream.os.environ.get('DEEPGRAM_MODEL', 'nova-2')}")
            await asyncio.to_thread(session.run_analysis, cfg)
            await client_send({"type": "state", "state": session.state()})

        await deepgram_stream.bridge(client_recv, client_send, session, cfg,
                                     on_final=on_final)
    except Exception as exc:  # noqa: BLE001 - never leave the socket hanging
        try:
            await websocket.send_json({"type": "error", "detail": str(exc)})
        except Exception:  # noqa: BLE001
            pass
    finally:
        try:
            await websocket.close()
        except Exception:  # noqa: BLE001
            pass


# -------------------------------------------------------------- dashboard
async def api_stats(request):
    try:
        user = _user(request)
        return JSONResponse(sv.dashboard_stats(user["id"]))
    except ApiError as exc:
        return _err(exc)


async def api_distribution(request):
    try:
        user = _user(request)
        return JSONResponse(db.risk_distribution(user["id"]))
    except ApiError as exc:
        return _err(exc)


async def api_recommendations(request):
    return JSONResponse(sv.recommendation_catalog())


async def api_samples(request):
    return JSONResponse(sv.sample_transcripts())


async def api_health(request):
    cfg = sv.config()
    return JSONResponse({
        "status": "ok",
        "server": "fastapi" if HAVE_FASTAPI else "starlette",
        "ai_mode": cfg["ai_mode"],
        "nlp_model": cfg["nlp_model"],
    })


routes = [
    # "/" is the console. Somebody following the deployed link should land in
    # the product, not on a sign-in wall - app.js opens a private guest session
    # for them if they have no token yet.
    Route("/", page_app),
    Route("/app", page_app),
    Route("/home", page_home),
    Route("/about", page_home),
    Route("/login", page_auth),
    Route("/signup", page_auth),
    Route("/api/auth/login", api_login, methods=["POST"]),
    Route("/api/auth/register", api_register, methods=["POST"]),
    Route("/api/auth/session", api_session, methods=["POST"]),
    Route("/api/auth/logout", api_logout, methods=["POST"]),
    Route("/api/auth/me", api_me, methods=["GET"]),
    Route("/api/auth/me", api_me_update, methods=["PATCH", "PUT"]),
    Route("/api/auth/me", api_me_delete, methods=["DELETE"]),
    Route("/api/cases/upload", api_upload, methods=["POST"]),
    Route("/api/cases", api_cases),
    Route("/api/live/config", api_live_config),
    Route("/api/live/start", api_live_start, methods=["POST"]),
    Route("/api/live/{session_id}/chunk", api_live_chunk, methods=["POST"]),
    Route("/api/live/{session_id}/state", api_live_state),
    Route("/api/live/{session_id}/end", api_live_end, methods=["POST"]),
    WebSocketRoute("/ws/live/{session_id}", ws_live),
    Route("/api/cases/pending", api_pending),
    Route("/api/cases/{case_pk:int}", api_case, methods=["GET"]),
    Route("/api/cases/{case_pk:int}", api_case_delete, methods=["DELETE"]),
    Route("/api/cases/{case_pk:int}/audio", api_case_audio),
    Route("/api/cases/{case_pk:int}/status", api_case_status, methods=["PATCH", "POST"]),
    Route("/api/dashboard/stats", api_stats),
    Route("/api/dashboard/risk-distribution", api_distribution),
    Route("/api/meta/recommendations", api_recommendations),
    Route("/api/meta/samples", api_samples),
    Route("/api/health", api_health),
    Mount("/assets", StaticFiles(directory=os.path.join(FRONTEND, "assets")), name="assets"),
]

middleware = [
    Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
]

sv.ensure_seed_user()
sv.ensure_demo_cases()
app = Starlette(routes=routes, middleware=middleware)
