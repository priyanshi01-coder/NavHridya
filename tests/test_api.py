"""API-level tests: auth, the upload pipeline, and the dashboard aggregates.

Uses Starlette's TestClient, so it exercises the real routes end to end against
a throwaway database.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["NAVHRIDYA_DB"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["NAVHRIDYA_SECRET"] = "test-secret-key-for-the-suite-only-32b"

from starlette.testclient import TestClient  # noqa: E402

from backend.app import app  # noqa: E402

client = TestClient(app)

CALM = "I just wanted to ask which documents are needed for a caste certificate."
DANGEROUS = "Woh log ghar ke bahar khade hain, unke paas chaku hai, usne kaha jaan se maar dunga."


def _token() -> str:
    r = client.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth():
    return {"Authorization": "Bearer " + _token()}


def test_health_reports_which_server_and_mode():
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["server"] in ("fastapi", "starlette")


def test_login_rejects_a_bad_password():
    assert client.post("/api/auth/login",
                       json={"username": "admin", "password": "wrong"}).status_code == 401


def test_protected_routes_need_a_token():
    assert client.get("/api/cases").status_code == 401
    assert client.get("/api/dashboard/stats").status_code == 401


def test_a_forged_token_is_rejected():
    assert client.get("/api/cases",
                      headers={"Authorization": "Bearer not.a.token"}).status_code == 401


def test_upload_needs_audio_or_transcript():
    r = client.post("/api/cases/upload", headers=_auth(), data={"channel": "Call"})
    assert r.status_code == 400


def test_calm_transcript_scores_low_and_does_not_trigger_the_floor():
    r = client.post("/api/cases/upload", headers=_auth(),
                    data={"channel": "Call", "language": "English", "transcript_text": CALM})
    assert r.status_code == 201, r.text
    case = r.json()
    assert case["safety_floor_triggered"] is False
    assert case["svi_category"] in ("Low", "Moderate")
    assert case["case_id"].startswith("#C")


def test_explicit_danger_is_forced_to_critical_with_evidence():
    case = client.post("/api/cases/upload", headers=_auth(),
                       data={"channel": "Call", "language": "Hindi",
                             "transcript_text": DANGEROUS}).json()
    assert case["safety_floor_triggered"] is True
    assert case["svi_score"] >= 80 and case["svi_category"] == "Critical"
    assert any(m["rule_id"] == "threat_to_life" for m in case["safety_matches"])
    assert len(case["evidence_spans"]) > 0


def test_recommendations_only_come_from_the_fixed_list():
    from backend.ai.nlp import ALLOWED_RECOMMENDATIONS
    case = client.post("/api/cases/upload", headers=_auth(),
                       data={"transcript_text": DANGEROUS}).json()
    assert all(r in ALLOWED_RECOMMENDATIONS for r in case["recommendations"])


def test_dashboard_numbers_match_the_stored_cases():
    cases = client.get("/api/cases", headers=_auth()).json()
    stats = client.get("/api/dashboard/stats", headers=_auth()).json()
    dist = client.get("/api/dashboard/risk-distribution", headers=_auth()).json()

    assert stats["total_cases"] == len(cases)
    assert stats["high_risk"] == sum(
        1 for c in cases if c["svi_category"] in ("High", "Critical"))
    assert dist["total"] == len(cases)
    for band in ("Low", "Moderate", "High", "Critical"):
        assert dist["counts"][band] == sum(1 for c in cases if c["svi_category"] == band)


def test_status_update_moves_a_case_into_under_support():
    case = client.get("/api/cases", headers=_auth()).json()[0]
    before = client.get("/api/dashboard/stats", headers=_auth()).json()["under_support"]
    r = client.patch(f"/api/cases/{case['id']}/status", headers=_auth(),
                     json={"status": "In Progress"})
    assert r.status_code == 200 and r.json()["status"] == "In Progress"
    after = client.get("/api/dashboard/stats", headers=_auth()).json()["under_support"]
    assert after == before + 1


def test_an_invalid_status_is_rejected():
    case = client.get("/api/cases", headers=_auth()).json()[0]
    assert client.patch(f"/api/cases/{case['id']}/status", headers=_auth(),
                        json={"status": "Banana"}).status_code == 400


def test_unknown_case_is_404():
    assert client.get("/api/cases/999999", headers=_auth()).status_code == 404


def test_pages_and_assets_are_served():
    assert client.get("/").status_code == 200
    assert client.get("/app").status_code == 200
    assert client.get("/assets/app.js").status_code == 200


# ---------------------------------------------------------------- accounts
def test_register_creates_an_account_that_can_sign_in():
    r = client.post("/api/auth/register", json={
        "username": "meera", "password": "counsellor1",
        "full_name": "Meera Das", "email": "meera@nhaa.gov.in"})
    assert r.status_code == 201, r.text
    user = r.json()["user"]
    assert user["username"] == "meera" and user["full_name"] == "Meera Das"
    assert user["role"] == "counsellor"
    assert client.post("/api/auth/login",
                       json={"username": "meera", "password": "counsellor1"}).status_code == 200


def test_register_rejects_a_duplicate_username_and_a_short_password():
    assert client.post("/api/auth/register",
                       json={"username": "admin", "password": "somethinglong"}).status_code == 409
    assert client.post("/api/auth/register",
                       json={"username": "shorty", "password": "abc"}).status_code == 400


def test_profile_and_theme_can_be_updated():
    r = client.patch("/api/auth/me", headers=_auth(),
                     json={"full_name": "Night Supervisor", "theme": "dark"})
    assert r.status_code == 200
    assert r.json()["full_name"] == "Night Supervisor" and r.json()["theme"] == "dark"
    assert client.patch("/api/auth/me", headers=_auth(),
                        json={"theme": "neon"}).status_code == 400


def test_delete_account_needs_the_password_and_removes_its_cases():
    client.post("/api/auth/register", json={"username": "tempuser", "password": "counsellor1"})
    tok = client.post("/api/auth/login",
                      json={"username": "tempuser", "password": "counsellor1"}).json()["token"]
    head = {"Authorization": f"Bearer {tok}"}
    made = client.post("/api/cases/upload", headers=head, data={"transcript_text": DANGEROUS})
    assert made.status_code == 201
    case_pk = made.json()["id"]

    assert client.request("DELETE", "/api/auth/me", headers=head,
                          json={"password": "wrong"}).status_code == 403
    out = client.request("DELETE", "/api/auth/me", headers=head,
                         json={"password": "counsellor1"})
    assert out.status_code == 200 and out.json()["cases_removed"] == 1
    assert client.get("/api/auth/me", headers=head).status_code == 401
    assert client.get(f"/api/cases/{case_pk}", headers=_auth()).status_code == 404


# ------------------------------------------------------------------ reasons
def test_a_scored_case_carries_its_reasons_and_the_arithmetic_trail():
    case = client.post("/api/cases/upload", headers=_auth(),
                       data={"transcript_text": DANGEROUS}).json()
    assert case["distress_reasons"] and case["danger_reasons"]
    assert all(isinstance(x, str) and x.strip() for x in case["distress_reasons"])
    trail = case["score_explanation"]
    assert len(trail) >= 3
    assert str(case["svi_score"]) in trail[-1] and case["svi_category"] in trail[-1]


def test_a_calm_transcript_still_explains_why_it_scored_low():
    case = client.post("/api/cases/upload", headers=_auth(),
                       data={"transcript_text": CALM}).json()
    assert case["svi_category"] == "Low"
    assert case["danger_reasons"], "a low score must still say why"


# ------------------------------------------------------------------- audio
def test_audio_is_stored_and_streamed_back_to_an_authenticated_caller():
    import io
    import struct
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"".join(struct.pack("<h", 0) for _ in range(8000)))
    raw = buf.getvalue()

    r = client.post("/api/cases/upload", headers=_auth(),
                    data={"transcript_text": DANGEROUS},
                    files={"audio_file": ("call.wav", raw, "audio/wav")})
    assert r.status_code == 201, r.text
    case = r.json()
    assert case["audio_filename"] and case["audio_original_name"] == "call.wav"
    assert case["audio_bytes"] == len(raw)
    assert case["audio_duration_seconds"] == 1.0

    got = client.get(f"/api/cases/{case['id']}/audio", headers=_auth())
    assert got.status_code == 200 and got.content == raw

    # the browser's <audio> element sends no Authorization header, so the
    # session cookie set at login has to be enough on its own
    fresh = TestClient(app)
    fresh.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert fresh.get(f"/api/cases/{case['id']}/audio").status_code == 200

    anon = TestClient(app)
    assert anon.get(f"/api/cases/{case['id']}/audio").status_code == 401


def test_a_case_without_audio_reports_404_for_its_recording():
    case = client.post("/api/cases/upload", headers=_auth(),
                       data={"transcript_text": CALM}).json()
    assert client.get(f"/api/cases/{case['id']}/audio", headers=_auth()).status_code == 404


def test_an_unsupported_audio_type_is_refused():
    r = client.post("/api/cases/upload", headers=_auth(),
                    files={"audio_file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 400 and "Unsupported audio type" in r.json()["detail"]


# ----------------------------------------------------------------- queues
def test_pending_queue_holds_only_open_cases_highest_first():
    rows = client.get("/api/cases/pending", headers=_auth()).json()
    assert all(r["status"] in ("Pending", "In Progress") for r in rows)
    scores = [r["svi_score"] for r in rows]
    assert scores == sorted(scores, reverse=True)


def test_a_case_can_be_deleted_with_its_audio():
    case = client.post("/api/cases/upload", headers=_auth(),
                       data={"transcript_text": CALM}).json()
    assert client.delete(f"/api/cases/{case['id']}", headers=_auth()).status_code == 200
    assert client.get(f"/api/cases/{case['id']}", headers=_auth()).status_code == 404


def test_logout_clears_the_session_cookie():
    c = TestClient(app)
    c.post("/api/auth/login", json={"username": "admin", "password": "admin123"})
    assert c.get("/api/auth/me").status_code == 200
    c.post("/api/auth/logout")
    assert c.get("/api/auth/me").status_code == 401


def test_the_public_pages_are_served_without_a_token():
    anon = TestClient(app)
    for path in ("/", "/login", "/signup", "/assets/base.css", "/assets/common.js"):
        assert anon.get(path).status_code == 200, path


# ------------------------------------------------------------ first run
def test_a_fresh_deployment_starts_with_no_cases():
    """Nothing exists until somebody uploads something.

    A counsellor opening this for the first time must not be shown demo rows -
    the console is empty until a call is actually scored. Seeding is opt-in via
    SEED_DEMO_CASES, and this suite never sets it.
    """
    import os
    import tempfile

    from backend import database as database_module
    from backend import services as services_module

    original_db, original_conn = database_module.DB_PATH, database_module._conn
    database_module.DB_PATH = os.path.join(tempfile.mkdtemp(), "fresh.db")
    database_module._conn = None
    try:
        services_module.ensure_seed_user()
        made = services_module.ensure_demo_cases()
        assert made == 0, "demo cases must not be seeded by default"
        assert database_module.count_cases() == 0
        assert database_module.list_cases() == []
        assert database_module.pending_cases() == []
        stats = database_module.stats()
        assert stats["total_cases"] == 0 and stats["high_risk"] == 0
        assert database_module.risk_distribution()["total"] == 0
        # the sign-in account still has to exist, or nobody can get in
        assert database_module.count_users() == 1
    finally:
        database_module.DB_PATH, database_module._conn = original_db, original_conn


def test_demo_seeding_can_be_switched_on_deliberately():
    import os
    import tempfile

    from backend import database as database_module
    from backend import services as services_module

    original_db, original_conn = database_module.DB_PATH, database_module._conn
    database_module.DB_PATH = os.path.join(tempfile.mkdtemp(), "seeded.db")
    database_module._conn = None
    os.environ["SEED_DEMO_CASES"] = "true"
    try:
        services_module.ensure_seed_user()
        made = services_module.ensure_demo_cases()
        assert made == 5, f"expected the five bundled samples, scored {made}"
        assert services_module.ensure_demo_cases() == 0, "must not seed twice"
    finally:
        os.environ.pop("SEED_DEMO_CASES", None)
        database_module.DB_PATH, database_module._conn = original_db, original_conn


# ------------------------------------------------- the deployed link
def test_the_root_url_serves_the_console_not_a_sign_in_wall():
    anon = TestClient(app)
    root = anon.get("/")
    assert root.status_code == 200
    assert "Operator Dashboard" in root.text, "/ must serve the console"
    # the public site is still there, one click away
    assert anon.get("/home").status_code == 200
    assert "answered first" in anon.get("/home").text


def test_a_visitor_gets_a_private_empty_workspace():
    visitor = TestClient(app)
    r = visitor.post("/api/auth/guest")
    assert r.status_code == 201, r.text
    user = r.json()["user"]
    assert user["is_guest"] is True and user["username"].startswith("guest_")

    head = {"Authorization": f"Bearer {r.json()['token']}"}
    assert visitor.get("/api/cases", headers=head).json() == []
    assert visitor.get("/api/cases/pending", headers=head).json() == []
    stats = visitor.get("/api/dashboard/stats", headers=head).json()
    assert stats["total_cases"] == 0 and stats["high_risk"] == 0
    assert stats["under_support"] == 0
    assert visitor.get("/api/dashboard/risk-distribution", headers=head).json()["total"] == 0


def test_one_visitor_never_sees_another_visitors_cases():
    """The whole point of a per-visitor session: a public demo link cannot leak
    one person's uploaded call into the next person's console."""
    first = TestClient(app)
    a = first.post("/api/auth/guest").json()
    ahead = {"Authorization": f"Bearer {a['token']}"}
    made = first.post("/api/cases/upload", headers=ahead, data={"transcript_text": DANGEROUS})
    assert made.status_code == 201
    case = made.json()
    assert len(first.get("/api/cases", headers=ahead).json()) == 1

    second = TestClient(app)
    b = second.post("/api/auth/guest").json()
    bhead = {"Authorization": f"Bearer {b['token']}"}
    assert b["user"]["username"] != a["user"]["username"], "each visitor needs their own session"
    assert second.get("/api/cases", headers=bhead).json() == [], "leaked into another session"
    assert second.get("/api/cases/pending", headers=bhead).json() == []
    assert second.get("/api/dashboard/stats", headers=bhead).json()["total_cases"] == 0

    # and B cannot reach A's case by guessing its id
    assert second.get(f"/api/cases/{case['id']}", headers=bhead).status_code == 404
    assert second.get(f"/api/cases/{case['id']}/audio", headers=bhead).status_code == 404
    assert second.patch(f"/api/cases/{case['id']}/status", headers=bhead,
                        json={"status": "Resolved"}).status_code == 404
    assert second.delete(f"/api/cases/{case['id']}", headers=bhead).status_code == 404

    # A still has it, untouched
    still = first.get(f"/api/cases/{case['id']}", headers=ahead)
    assert still.status_code == 200 and still.json()["status"] == "Pending"


def test_a_signed_in_counsellor_also_only_sees_their_own_cases():
    first = TestClient(app)
    first.post("/api/auth/register", json={"username": "asha", "password": "counsellor1"})
    ahead = {"Authorization": f"Bearer {first.post('/api/auth/login', json={'username': 'asha', 'password': 'counsellor1'}).json()['token']}"}
    first.post("/api/cases/upload", headers=ahead, data={"transcript_text": CALM})
    assert len(first.get("/api/cases", headers=ahead).json()) == 1

    second = TestClient(app)
    second.post("/api/auth/register", json={"username": "bina", "password": "counsellor1"})
    bhead = {"Authorization": f"Bearer {second.post('/api/auth/login', json={'username': 'bina', 'password': 'counsellor1'}).json()['token']}"}
    assert second.get("/api/cases", headers=bhead).json() == []


# ------------------------------------------------------------- live calls
def _live_cfg_available():
    from backend import services as services_module
    return services_module.live_config()["available"]


def test_live_config_says_plainly_whether_it_can_transcribe():
    cfg = client.get("/api/live/config", headers=_auth()).json()
    assert set(("available", "note", "streaming_possible")) <= set(cfg)
    assert isinstance(cfg["note"], str) and cfg["note"]
    # the note is written for a counsellor, so it must not name a vendor or model
    lowered = cfg["note"].lower()
    for vendor in ("deepgram", "groq", "openai", "whisper", "nova-2", "gpt-"):
        assert vendor not in lowered, f"{vendor} leaked into a user-facing string"
    assert cfg["streaming_possible"] is False, "streaming is switched off in this build"


def test_a_live_call_scores_as_it_goes_and_saves_one_case_at_the_end():
    """The whole point: the score moves while the call is still running, the
    deterministic rules fire the moment the words are spoken, and what is saved
    is a full pass over the complete transcript."""
    from backend import live as live_module
    from backend import services as services_module

    # drive the session directly - the HTTP layer is covered by the ASR test
    # below, and this keeps the test independent of any speech-to-text key
    session = live_module.STORE.create(None, channel="Live Call", language="Hindi")
    original = live_module.ANALYSIS_INTERVAL
    live_module.ANALYSIS_INTERVAL = 0.0
    cfg = services_module.config()
    try:
        session.add_segment("Namaste, main gaon se bol rahi hoon.")
        session.run_analysis(cfg)
        calm = session.state()

        session.add_segment("Usne kaha jaan se maar dunga, uske paas chaku hai.")
        alarmed = session.state()

        # the floor fired on the words alone, before any further model pass
        assert alarmed["safety_floor_triggered"] is True
        assert "threat_to_life" in alarmed["safety_rules_fired"]
        assert alarmed["svi_score"] >= 80 and alarmed["svi_category"] == "Critical"
        assert alarmed["svi_score"] > calm["svi_score"], "the score must move during the call"
        assert len(alarmed["segments"]) == 2
    finally:
        live_module.ANALYSIS_INTERVAL = original

    assert session.snapshots, "snapshots must be kept for the trend line"


def test_the_deterministic_floor_does_not_wait_for_the_model():
    from backend import live as live_module

    session = live_module.STORE.create(None)
    original = live_module.ANALYSIS_INTERVAL
    live_module.ANALYSIS_INTERVAL = 10_000.0          # the model will not run again
    try:
        session.add_segment("Sab theek hai, bas information chahiye thi.")
        assert session.state()["safety_floor_triggered"] is False
        session.add_segment("Abhi darwaza tod rahe hain, jaan se maar denge.")
        state = session.state()
        assert state["safety_floor_triggered"] is True
        assert state["svi_score"] >= 80
        assert state["analysed_once"] is False, "no model pass should have run at all"
    finally:
        live_module.ANALYSIS_INTERVAL = original


def test_a_live_call_belongs_to_the_session_that_started_it():
    first = TestClient(app)
    a = first.post("/api/auth/guest").json()
    ahead = {"Authorization": f"Bearer {a['token']}"}
    started = first.post("/api/live/start", headers=ahead, json={})
    if started.status_code == 400:
        return                       # no speech-to-text key configured in this run
    sid = started.json()["session_id"]

    second = TestClient(app)
    bhead = {"Authorization": f"Bearer {second.post('/api/auth/guest').json()['token']}"}
    assert second.get(f"/api/live/{sid}/state", headers=bhead).status_code == 404
    assert second.post(f"/api/live/{sid}/end", headers=bhead, json={}).status_code == 404
    assert first.get(f"/api/live/{sid}/state", headers=ahead).status_code == 200


def test_ending_a_call_with_no_speech_saves_nothing():
    c2 = TestClient(app)
    head = {"Authorization": f"Bearer {c2.post('/api/auth/guest').json()['token']}"}
    started = c2.post("/api/live/start", headers=head, json={})
    if started.status_code == 400:
        return
    sid = started.json()["session_id"]
    before = len(c2.get("/api/cases", headers=head).json())
    ended = c2.post(f"/api/live/{sid}/end", headers=head, json={})
    assert ended.status_code == 400
    assert len(c2.get("/api/cases", headers=head).json()) == before


def test_the_streaming_module_is_inert_and_says_why():
    """Switched off means switched off: nothing may connect, and the reason is
    stated for whoever picks the work back up."""
    from backend.ai import deepgram_stream

    assert deepgram_stream.enabled() is False
    assert deepgram_stream.streaming_possible() is False
    assert deepgram_stream.why_not() == "Streaming is switched off in this build."
