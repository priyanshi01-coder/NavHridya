"""Tests for the parts that must never be wrong: the SVI arithmetic and the
deterministic safety floor. Run with `pytest` from the backend directory."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.ai.safety_rules import check_safety_floor
from backend.ai.svi import band_for, compute_svi
from backend.ai.nlp import ALLOWED_RECOMMENDATIONS, analyze_locally, validate_analysis
from backend.ai.pipeline import run_pipeline

NO_FLAGS = {k: False for k in
            ("fear", "threat", "high_stress", "emotional_distress", "social_isolation")}


# ---------------------------------------------------------------- bands
def test_band_boundaries():
    assert band_for(0) == "Low"
    assert band_for(39.9) == "Low"
    assert band_for(40) == "Moderate"      # lower bound inclusive
    assert band_for(59.9) == "Moderate"
    assert band_for(60) == "High"
    assert band_for(79.9) == "High"
    assert band_for(80) == "Critical"
    assert band_for(100) == "Critical"     # 100 belongs to Critical


# ---------------------------------------------------------------- formula
def test_base_score_is_the_mean_of_the_two_axes():
    r = compute_svi(60, 40, NO_FLAGS, False)
    assert r["base_score"] == 50.0
    assert r["svi_score"] == 50
    assert r["svi_category"] == "Moderate"


def test_indicator_bonus_is_five_each_capped_at_twenty():
    one = compute_svi(40, 40, {**NO_FLAGS, "fear": True}, False)
    assert one["indicator_bonus"] == 5 and one["svi_score"] == 45

    all_five = compute_svi(40, 40, {k: True for k in NO_FLAGS}, False)
    assert all_five["indicator_count"] == 5
    assert all_five["indicator_bonus"] == 20          # capped, not 25
    assert all_five["svi_score"] == 60


def test_score_never_exceeds_one_hundred():
    r = compute_svi(100, 100, {k: True for k in NO_FLAGS}, False)
    assert r["svi_score"] == 100
    assert r["svi_category"] == "Critical"


def test_safety_floor_lifts_a_low_score_to_eighty():
    r = compute_svi(10, 10, NO_FLAGS, True)
    assert r["svi_score"] == 80
    assert r["svi_category"] == "Critical"
    assert r["safety_floor_applied"] is True


def test_safety_floor_never_lowers_a_higher_score():
    r = compute_svi(95, 95, {k: True for k in NO_FLAGS}, True)
    assert r["svi_score"] == 100
    assert r["safety_floor_applied"] is False         # floor was already exceeded


def test_out_of_range_model_output_is_clamped():
    r = compute_svi(500, -200, NO_FLAGS, False)
    assert r["distress_score"] == 100 and r["danger_score"] == 0
    assert r["svi_score"] == 50


# ---------------------------------------------------------------- safety rules
def test_plain_distress_does_not_trigger_the_floor():
    out = check_safety_floor("I feel very sad and alone, nobody in the village talks to us.")
    assert out["triggered"] is False and out["matches"] == []


def test_explicit_threat_triggers_with_evidence_span():
    out = check_safety_floor("He said he will kill me if I go to the police.")
    assert out["triggered"] is True
    assert "threat_to_life" in out["rules_fired"]
    m = out["matches"][0]
    assert m["matched_text"].lower().startswith("kill me")
    assert m["start"] < m["end"]


def test_hindi_and_romanised_hindi_both_trigger():
    assert check_safety_floor("usne kaha jaan se maar dunga")["triggered"] is True
    assert check_safety_floor("उसने कहा जान से मार दूंगा")["triggered"] is True


def test_weapon_and_self_harm_rules():
    assert "weapon" in check_safety_floor("he had a knife in his hand")["rules_fired"]
    assert "self_harm" in check_safety_floor("I want to end my life")["rules_fired"]


# ---------------------------------------------------------------- validation
def test_invented_recommendations_are_dropped():
    out = validate_analysis({
        "distress_score": 50, "danger_score": 50, "indicators": {},
        "summary": "x",
        "recommendations": ["Immediate Counselling", "Send a drone", "Legal Aid Support"],
    })
    assert out["recommendations"] == ["Immediate Counselling", "Legal Aid Support"]
    assert all(r in ALLOWED_RECOMMENDATIONS for r in out["recommendations"])


def test_missing_fields_do_not_crash_validation():
    out = validate_analysis({})
    assert out["distress_score"] == 0 and out["danger_score"] == 0
    assert set(out["indicators"]) == set(NO_FLAGS)


# ---------------------------------------------------------------- pipeline
OFFLINE = {"api_key": "", "label": "none", "name": "openai",
           "base_url": "", "asr_model": "whisper-1", "nlp_model": "gpt-4o-mini"}


def _run(text):
    return run_pipeline(audio_path=None, transcript_text=text, cfg=OFFLINE)


def test_pipeline_end_to_end_on_a_calm_transcript():
    r = _run("I wanted to ask about the documents needed for a caste certificate. "
             "Everything is fine otherwise, I just needed some information today.")
    assert r["safety_floor_triggered"] is False
    assert r["svi_category"] in ("Low", "Moderate")
    assert r["svi_score"] == int(round(min(100, r["base_score"] + r["indicator_bonus"])))


def test_pipeline_forces_critical_when_a_rule_fires_even_if_scores_are_low():
    r = _run("Sab theek hai lekin usne kaha jaan se maar dunga.")
    assert r["safety_floor_triggered"] is True
    assert r["svi_score"] >= 80 and r["svi_category"] == "Critical"
    assert any(e["type"] == "safety_rule" for e in r["evidence_spans"])


def test_pipeline_requires_some_input():
    try:
        run_pipeline(audio_path=None, transcript_text="  ", cfg=OFFLINE)
    except ValueError:
        return
    raise AssertionError("expected ValueError when no audio and no transcript")


# ------------------------------------------------------- provider resolution
def test_provider_defaults_to_whichever_key_is_present():
    import os
    from backend.ai import providers

    # every variable resolve() reads, so a real .env on the machine running the
    # suite cannot change the answer - ASR_MODEL and NLP_MODEL override the
    # per-provider defaults this test asserts on
    saved = {k: os.environ.get(k) for k in
             ("AI_PROVIDER", "OPENAI_API_KEY", "GROQ_API_KEY", "AI_BASE_URL",
              "ASR_MODEL", "NLP_MODEL")}
    try:
        for k in saved:
            os.environ.pop(k, None)

        os.environ["OPENAI_API_KEY"] = "sk-x"
        assert providers.resolve()["name"] == "openai"

        os.environ.pop("OPENAI_API_KEY")
        os.environ["GROQ_API_KEY"] = "gsk-x"
        got = providers.resolve()
        assert got["name"] == "groq"
        assert "groq.com" in got["base_url"]
        assert got["asr_model"] == "whisper-large-v3"

        os.environ["AI_PROVIDER"] = "openai"
        os.environ["OPENAI_API_KEY"] = "sk-y"
        assert providers.resolve()["name"] == "openai"
    finally:
        for k, v in saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v


def test_placeholder_keys_are_treated_as_absent():
    import os
    from backend.ai import providers

    saved = os.environ.get("OPENAI_API_KEY")
    try:
        for junk in ("", "your_key_here", "sk-...", "CHANGEME"):
            os.environ["OPENAI_API_KEY"] = junk
            os.environ.pop("GROQ_API_KEY", None)
            assert providers.resolve()["api_key"] == "", junk
    finally:
        os.environ.pop("OPENAI_API_KEY", None)
        if saved is not None:
            os.environ["OPENAI_API_KEY"] = saved


def test_provider_errors_are_explained_not_dumped():
    from backend.ai import providers

    no_credit = providers._friendly(
        429, '{"error":{"message":"You have no credits remaining",'
             '"code":"credit_balance_exhausted"}}')
    assert "no credits" in no_credit.lower()
    assert "groq" in no_credit.lower()          # points at the free way out

    bad_key = providers._friendly(401, '{"error":{"message":"Incorrect API key"}}')
    assert "key was rejected" in bad_key.lower()

    missing_model = providers._friendly(404, '{"error":{"message":"model not found"}}')
    assert "ASR_MODEL" in missing_model


def test_a_provider_failure_never_loses_the_case():
    """The model failing must still produce a scored case, clearly labelled."""
    from backend.ai import nlp

    broken = {"api_key": "sk-x", "label": "openai", "name": "openai",
              "base_url": "http://127.0.0.1:9/v1",   # nothing listens there
              "asr_model": "whisper-1", "nlp_model": "gpt-4o-mini"}
    out = nlp.analyze_transcript("usne dhamki di, main dar gayi hoon", broken)
    assert out["engine"] == "local-lexicon-fallback"
    assert "failed" in out["engine_note"].lower()
    assert 0 <= out["distress_score"] <= 100


# ------------------------------------------------- JSON mode request shape
def test_json_mode_requests_always_contain_the_word_json():
    """Groq refuses a json_object request unless the messages mention 'json'.

    The prompt must never be able to lose that word, so the client guarantees
    it. This test drives a throwaway server and inspects what went on the wire.
    """
    import json as _json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from backend.ai import providers

    captured = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            n = int(self.headers.get("Content-Length", 0))
            req = _json.loads(self.rfile.read(n))
            captured["req"] = req
            captured["ua"] = self.headers.get("User-Agent")
            blob = " ".join(m["content"] for m in req["messages"]).lower()
            if req.get("response_format", {}).get("type") == "json_object" \
                    and "json" not in blob:
                body = _json.dumps({"error": {"message":
                    "'messages' must contain the word 'json' in some form"}}).encode()
                code = 400
            else:
                body = _json.dumps(
                    {"choices": [{"message": {"content": '{"ok": true}'}}]}).encode()
                code = 200
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    cfg = {"name": "groq", "label": "groq", "api_key": "k",
           "base_url": f"http://127.0.0.1:{server.server_port}/v1",
           "asr_model": "whisper-large-v3", "nlp_model": "test-model"}

    # a prompt with no mention of json must still be accepted
    out = providers.chat_json("Be terse.", "hello", cfg=cfg)
    assert out == {"ok": True}
    sent = " ".join(m["content"] for m in captured["req"]["messages"]).lower()
    assert "json" in sent

    # and the User-Agent must never fall back to urllib's default, which
    # Cloudflare blocks with error 1010
    assert "NAVHRIDYA" in captured["ua"] and "urllib" not in captured["ua"].lower()

    # the real analysis prompt already says json, and must keep saying it
    from backend.ai.nlp import SYSTEM_PROMPT
    assert "json" in SYSTEM_PROMPT.lower()

    server.shutdown()


# ------------------------------------------------------- live language rule
def test_hindi_stays_hindi_and_a_third_language_is_translated():
    from backend.ai import live_asr

    cfg = {"api_key": "", "label": "none", "base_url": "", "nlp_model": "", "asr_model": ""}

    hindi = live_asr.normalise_language("मुझे डर लग रहा है", "hi", cfg)
    assert hindi["text"] == "मुझे डर लग रहा है" and hindi["translated"] is False

    # Devanagari with no language reported is still Hindi
    guessed = live_asr.normalise_language("कोई हमसे बात नहीं करता", "", cfg)
    assert guessed["language"] == "hi" and guessed["translated"] is False

    english = live_asr.normalise_language("They threatened my family.", "en", cfg)
    assert english["text"] == "They threatened my family." and english["translated"] is False

    # a third language would be translated - with no provider configured the
    # call fails, and the original must be kept rather than dropped on the floor
    tamil = live_asr.normalise_language("எனக்கு பயமாக இருக்கிறது", "ta", cfg)
    assert tamil["text"] == "எனக்கு பயமாக இருக்கிறது"
    assert tamil["translated"] is False


def test_an_empty_live_segment_changes_nothing():
    from backend.live import LiveSession

    s = LiveSession("t", None)
    s.add_segment("")
    assert s.transcript == "" and s.segments == []
    assert s.state()["svi_score"] == 0


# ---------------------------------------------------- theme tokens and copy
def _base_css() -> str:
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "frontend", "assets", "base.css"), encoding="utf-8") as fh:
        return fh.read()


def test_light_only_styling_never_reaches_dark():
    """Every light-mode rule added by the polish pass is scoped so dark cannot
    match it. A rule that forgets the scope would silently change dark mode."""
    import re
    css = _base_css()
    polish = css[css.index("/*  Light mode only."):]
    polish = re.sub(r"/\*.*?\*/", "", polish, flags=re.S)      # drop comments first
    rules = [block.split("{")[0].strip()
             for block in polish.split("}") if "{" in block and block.strip()]
    for selector in rules:
        if selector.startswith("@") or not selector:
            continue
        for part in selector.split(","):
            part = part.strip()
            if part:
                assert part.startswith('html:not([data-theme="dark"])'), \
                    f"unscoped rule would affect dark mode: {part}"


def test_the_risk_bands_stay_distinguishable_in_light():
    """Moderate and High used to be too close to tell apart on the donut."""
    css = _base_css()
    light = css[css.index(":root{"):css.index('html[data-theme="dark"]')]
    for token in ("--low:", "--mod:", "--high:", "--crit:"):
        assert token in light, f"{token} missing from the light palette"
    assert "--mod:#b8860b" in light.replace(" ", "")
    assert "--high:#c0441a" in light.replace(" ", "")
    # dark keeps its own steps, untouched by the light pass
    dark = css[css.index('html[data-theme="dark"]'):]
    assert "--mod:#d6a63f" in dark.replace(" ", "")
    assert "--high:#e5824a" in dark.replace(" ", "")


def test_no_engine_or_provider_detail_is_rendered_in_the_ui():
    """Model names, providers and timings are for our logs, not for a counsellor."""
    import os
    import re
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "frontend", "assets", "app.js"), encoding="utf-8") as fh:
        js = fh.read()
    # strip comments, then look at what is left
    code = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.M)
    for banned in ("Pipeline</dt>", "Transcribed by", "analysed by",
                   "Use Deepgram streaming", "asr_engine)}", "cfg.engine"):
        assert banned not in code, f"{banned!r} is still rendered in the UI"
    assert "console.info" in code, "the detail should still reach the console"


def test_deepgram_streaming_is_switched_off():
    from backend.ai import deepgram_stream

    assert deepgram_stream.enabled() is False, "streaming must be off by default"
    assert deepgram_stream.streaming_possible() is False
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "frontend", "assets", "app.js"), encoding="utf-8") as fh:
        js = fh.read()
    assert "const STREAMING_ENABLED = false;" in js


# ------------------------------------------------------- branding and motion
def test_no_html_entity_is_passed_through_the_escaper():
    """An entity inside esc() renders as literal text - `&middot;` showed up on
    the dashboard that way once."""
    import os
    import re
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "frontend", "assets", "app.js"), encoding="utf-8") as fh:
        js = fh.read()
    for m in re.finditer(r"esc\(([^()]*(?:\([^()]*\))?[^()]*)\)", js):
        assert not re.search(r"&[a-zA-Z]+;", m.group(1)), \
            f"HTML entity would render as text: {m.group(1).strip()[:60]}"


def test_the_homepage_cannot_leave_content_invisible():
    """An earlier scroll-triggered reveal stranded whole sections at opacity 0
    when the observer never reached them. Entrance motion must be plain CSS
    animation, which always runs to completion."""
    import os
    import re
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(here, "frontend", "index.html"), encoding="utf-8") as fh:
        html = fh.read()
    assert "IntersectionObserver" not in html
    style = html[html.index("<style>"):html.index("</style>")]
    # nothing may sit at opacity:0 unless an animation is bringing it back
    for block in style.split("}"):
        if "opacity:0" in block.replace(" ", "") and "keyframes" not in block \
                and "@" not in block.split("{")[0]:
            assert "animation" in block, f"rule can strand content hidden: {block.strip()[:80]}"
    assert "prefers-reduced-motion" in style


def test_both_headers_use_the_circular_logo():
    import os
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for page, selector in (("index.html", ".logo img"), ("app.html", ".appbar .brand img"),
                           ("auth.html", ".pitch a.logo img")):
        with open(os.path.join(here, "frontend", page), encoding="utf-8") as fh:
            css = fh.read()
        rule = css[css.index(selector + "{"):]
        rule = rule[:rule.index("}")]
        assert "border-radius:50%" in rule, f"{page} {selector} is not circular"
        size = int(rule.split("width:")[1].split("px")[0])
        assert size >= 40, f"{page} {selector} is only {size}px"
