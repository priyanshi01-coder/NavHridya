# NAVHRIDYA — assessment layer for NHAA 14566

**SIH 2026 · PS SIH26093 · Team HackSmiths · working prototype**

A counsellor signs in, uploads a recorded call, and the system transcribes it,
screens it against deterministic safety rules, runs a distress/danger analysis,
computes a **Stress Vulnerability Index (0-100)** — **with the reasons behind
every number** — and puts the case on an operator dashboard.

Nothing in the app is hardcoded. Every figure is read back out of SQLite, which
is also why a browser refresh loses nothing: the state lives on the server.

**It starts empty, and it comes back to empty.** A fresh deployment has no
cases. The dashboard then counts the *live queue*: once every case has been
resolved or deleted, the console shows zero again - the same clean state a brand
new deployment shows. Nothing is destroyed; Reports still lists every case ever
scored, and the stat card says how many were closed. The first
case appears when a call is uploaded or a sample transcript is scored - never
before. To pre-fill it right before a demo, set `SEED_DEMO_CASES=true` in `.env`
and the five bundled samples are scored on the next start through the real
pipeline.

**The deployed link opens the console.** Somebody following it lands on the
dashboard, already signed in as the helpline's counsellor account - no form, no
sign-in wall. The sign-in page is reachable only by pressing **Sign out**.

This means the deployment is **open**: anyone with the URL is in that one shared
workspace and can read, change and delete the cases in it. That is deliberate for
a demo link, and it is the reason to change `SEED_ADMIN_PASSWORD` before sharing
the URL widely. A counsellor who signs in under their own name gets their own
case list, separate from the shared one.

**Pages, all of them working:**

| Page | What it is |
|---|---|
| `/` | The console - what the deployed link opens, already signed in |
| `/home` | Public site: hero, How it works, Key differentiators, SVI scoring, Safety by design, footer |
| `/login` | Sign in **and** create account, with a show-password toggle |
| `/app#/dashboard` | Stats, SVI gauge, risk donut, case details, recommendations, and why the case scored what it did |
| `/app#/live` | **Live Call**: the mic becomes the call, transcript and SVI update while it is still happening |
| `/app#/upload` | Upload Call, on its own page: audio or transcript in, a reasoned SVI out |
| `/app#/pending` | The review queue, grouped by the date each call was received |
| `/app#/reports` | Every case, with its recording, transcript, timestamps, SVI, reasons and status |
| `/app#/settings` | Profile, theme, password, sign out, delete account |

A light/dark theme toggle sits in the header of every page and is remembered on
the device and on the account.

---

## 1. Run it — two steps

```bash
cd NAVHRIDYA
pip install -r requirements.txt
python run.py                       # http://127.0.0.1:8000
```

Windows: double-click **`run.bat`**.  macOS/Linux: **`./run.sh`**. Both do both steps.

Then open **http://127.0.0.1:8000** and sign in with **`admin` / `admin123`**.

If port 8000 is busy (an earlier run still open), the launcher picks the next
free port and tells you which one - or pass `python run.py --port 8010`.

To free port 8000 on Windows instead:

```powershell
netstat -ano | findstr :8000        # last column is the PID
taskkill /PID <that-pid> /F
```

There is no `npm install` and no build step. The dashboard is plain HTML, CSS and
JavaScript served by the backend, with the gauge and the donut drawn as inline
SVG, so it renders with the venue wifi unplugged.

> There is no React build in this package. An earlier draft shipped one that had
> never been built or verified, and shipping unverified code alongside a working
> app is worse than not shipping it. The frontend here is hand-written HTML, CSS
> and JavaScript, and every page of it has been driven in a real browser.

---

## 2. What actually works

| Piece | Status |
|---|---|
| Login, sessions, protected routes | **working** — PBKDF2 passwords, signed tokens |
| Upload a call (audio **or** pasted transcript) | **working** |
| Transcription — Whisper via OpenAI or Groq | **working** with a key |
| Transcription — local faster-whisper | **working** with `USE_LOCAL_WHISPER=true` |
| Distress / danger analysis — any OpenAI-compatible model, JSON mode | **working** with a key (OpenAI or Groq) |
| Distress / danger analysis — local lexicon | **working offline**, labelled as such in the UI |
| **Safety-floor rule engine** | **working** — deterministic, runs outside the model |
| SVI scoring + risk bands | **working** — plain Python, 16 tests |
| **Reasons for every score** — which cues raised distress, which raised danger, the arithmetic step by step, which safety rules fired and on which words | **working** — from both the model and the local analyser |
| Public homepage with How it works and Key differentiators | **working** |
| Create account, show-password toggle, sign out to the homepage | **working** |
| Dashboard: stats, gauge, donut, case details, recommendations, recent cases | **working** — all read from the DB |
| Upload Call as its own page, with drag and drop | **working** |
| Pending Review, grouped by date, highest SVI first | **working** |
| Reports: every case with audio playback, transcript with rule matches highlighted, timestamps, SVI, reasons | **working** |
| Settings: profile, password, light/dark theme, sign out, delete account | **working** |
| State survives a refresh | **working** — it is in SQLite, not in the tab |
| Status changes (Take / Resolve / Escalate) | **working** |
| Live analysis of a call still in progress | **not built** — the stated next step after this prototype |

### Verified, not just written

```bash
pip install pytest && pytest          # 71 tests
```

- **30 core tests** — band boundaries, the 20-point bonus cap, the 100 ceiling,
  the safety floor raising *and never lowering* a score, clamping of
  out-of-range model output, Hindi and romanised-Hindi rule matching, and
  rejection of invented recommendations.
  Four of them pin this build's UI decisions: every light-mode rule is scoped so
  it cannot reach dark, the light risk bands stay far enough apart to tell apart,
  no engine or provider name is rendered anywhere in the interface, and Deepgram
  streaming is off.
- **41 API tests** — that the link signs you in with no form, that the console
  returns to zero once the queue is cleared while Reports keeps every case, that
  a case reference is never handed out twice after a deletion, that a live
  call's score moves while the call is running,
  that the safety floor fires mid-call with no model pass at all, that one
  visitor cannot touch another's live call, that ending a silent call saves
  nothing, that `/` serves the console, that each visitor gets a
  private empty workspace, that one visitor cannot read, change or delete
  another's case even by guessing its id, that a fresh database really is empty
  and that seeding is opt-in, auth and forged tokens, registration and duplicate
  usernames, profile and theme updates, account deletion taking its cases with
  it, the upload pipeline, the reason lists and the arithmetic trail being
  present on every case, audio being stored and streamed back (including that an
  anonymous request is refused), the pending queue ordering, and that the stat
  cards and the donut always equal what is actually in the database.
- The provider client was exercised against a **mock OpenAI-compatible server**:
  multipart audio upload, JSON-mode analysis, an invented recommendation being
  dropped, and the 401 / 429-no-credits paths each producing a readable message
  instead of a stack trace.

Every page was also driven end to end in a headless Chromium: homepage in both
themes, create account, show-password toggle, upload a real `.wav` through
Whisper and see the SVI come back with its reasons, paste a transcript, the
pending queue, opening a report and playing its recording, settings, switching to
dark, a hard refresh proving both the theme and the cases survive, a 390px
mobile viewport with no horizontal overflow, sign out landing on the public
homepage, and `/app` bouncing to the sign-in page without a token. Zero console
errors on any page.

---

## 3. Turning the real AI on

The app speaks the OpenAI REST API directly, so **any OpenAI-compatible
provider works** by changing one line. No vendor SDK to install.

### Option A — Groq (free)

Get a key at <https://console.groq.com/keys>, then in `.env`:

```
AI_PROVIDER=groq
GROQ_API_KEY=gsk_...
```

Uses `whisper-large-v3` for audio and Llama for the analysis. Free tier.

### Option B — OpenAI (needs credits on the account)

```
AI_PROVIDER=openai
OPENAI_API_KEY=sk-proj-...
```

Uses `whisper-1` and `gpt-4o-mini`. A key alone is not enough — the account
needs credits, or every call comes back `429 insufficient_quota`.

### Verify it before you present

```bash
python run.py --check-ai
```

```
  provider  : groq
  models    : whisper-large-v3 (audio) / llama-3.3-70b-versatile (analysis)
  api key   : set

  WORKING: groq / llama-3.3-70b-versatile responded: {'ok': True}
```

If it says NOT WORKING, the message tells you exactly why — wrong key, no
credits, retired model, or no connection.

### The three modes

| Mode | Set this | ASR | Analysis |
|---|---|---|---|
| **API** | `GROQ_API_KEY` or `OPENAI_API_KEY` | Whisper via the provider | the provider's model, JSON mode |
| **Local ASR** | `USE_LOCAL_WHISPER=true` + `pip install faster-whisper` | faster-whisper, offline | the API model if a key is set |
| **Offline demo** | nothing | paste a transcript | local lexicon analyser |

Offline mode exists on purpose. Venue wifi fails and keys get rate-limited; a
demo that dies on stage is worth nothing. The dashboard labels the engine
`local-lexicon-fallback` and, if the API was tried and failed, prints why — so
you never claim the model did something it did not.

**The proof is on the dashboard.** Every case prints its own pipeline under
Case Details: `groq:whisper-large-v3 → groq:llama-3.3-70b-versatile` means the
AI ran. `local-lexicon-fallback` means it did not, and the line under it says
what went wrong.

### When a model name stops working

Providers retire models, and a new account is not always granted access to every
model on the public list, so a name that worked last month can come back as
`404 - The model ... does not exist or you do not have access to it`.

Do not guess a replacement. Ask your own key which models it can use:

```bash
python run.py --list-models
```

It prints the analysis models and the speech-to-text models your key actually
has, and ends with the two lines to paste into `.env`:

```
NLP_MODEL=<a model your key has>
ASR_MODEL=<a whisper model your key has>
```

Then `python run.py --check-ai` to confirm. `--check-ai` also runs this lookup
by itself whenever the configured model comes back as not found, so it tells you
what to switch to instead of leaving you guessing.

## 3b. Live Call

A third input mode, next to upload and paste. The microphone stands in for the
call audio; the browser records it in short slices and posts each one, and the
reply carries the new transcript line and the re-scored SVI. The distress,
danger and SVI cards move while the caller is still talking.

Two cadences, deliberately different:

- **The deterministic safety rules run on every segment, the moment it arrives.**
  They are regex over text and cost nothing. An explicit threat raises the floor
  immediately - it does not wait for the model.
- **The model re-reads the call at most every 12 seconds** (or sooner if a lot of
  new speech has arrived). Re-analysing on every word would be slow, expensive
  and jittery, and would not make the number any truer.

**Language**: Hindi is shown in Hindi. English stays English. Any third language
is translated to English before it reaches the counsellor, and the line is
labelled as translated. Code-mixed Hindi-English comes through as spoken.

**Ending the call** runs the complete transcript through the ordinary pipeline
once more, and *that* is what gets saved - not the last live snapshot. A live
case and an uploaded case mean exactly the same thing. The running scores are
kept as snapshots, and drawn as a line under the live panel so you can see the
moment the risk moved.

Nothing is saved until you press End Call. Leaving the page mid-call stops the
microphone and discards it.

### Two transports

| | How | Latency | Needs | Status |
|---|---|---|---|---|
| **Short clips** (default) | ~4s of audio posted at a time, transcribed by whichever Whisper you already have | ~2-4s | nothing new | **tested end to end** |
| **Deepgram streaming** | raw PCM over a WebSocket, continuous | under a second | `DEEPGRAM_API_KEY` + `pip install websockets` | **switched off in this build** |

The streaming path is **switched off**. It was written from Deepgram's docs
without a key and without network access to api.deepgram.com, so it has never
been exercised against the real service, and shipping an untested path in front
of a demo is not worth the risk. The code is kept - `backend/ai/deepgram_stream.py`
and the `/ws/live` route - behind two flags that are both false:
`NAVHRIDYA_ENABLE_STREAMING` on the server and `STREAMING_ENABLED` in
`frontend/assets/app.js`. While they are false nothing opens a socket, nothing
reaches Deepgram, and no Deepgram state can appear in the UI. Every call uses the
clip path, which is tested end to end.

### This is a microphone demo, not telephony

A real deployment would never read a microphone. The telephony layer in front of
NHAA 14566 - the IVR, or a provider like Exotel or Twilio Media Streams - would
push call audio into exactly these endpoints. Say that out loud before a judge
asks.

---

## 4. What happens on upload

1. Save the audio to `data/uploads/`
2. **Transcribe** — Whisper, faster-whisper, or the pasted transcript
3. **Safety rules** — `backend/ai/safety_rules.py`, deterministic regex
4. **Analyse** — GPT-4o-mini returns distress, danger, five indicator flags, a summary, recommendations
5. **Score** — `backend/ai/svi.py`, plain Python
6. Persist and return the finished case

Step 3 runs **before** the model and is applied **after** it, deliberately: no
model output can talk the safety floor down.

### The SVI formula

```
base_score      = 0.5 × distress_score + 0.5 × danger_score
indicator_bonus = min(20, 5 × number_of_true_indicators)
svi_score       = min(100, base_score + indicator_bonus)

if safety_floor_triggered:
    svi_score = max(svi_score, 80)        # forced Critical floor

Low 0–40 · Moderate 40–60 · High 60–80 · Critical 80–100
```

Every term is stored in its own column, and the dashboard prints the working
under the gauge — `0.5×29 + 0.5×65 + 10 indicator bonus, raised to the 80 safety
floor = 80` — so the score is never a mystery number.

### The safety floor

Seven rule families — threat to life, weapons, self-harm, imminent danger,
sexual violence, physical violence, child at risk — in English, Devanagari Hindi
and romanised Hindi, because callers code-mix constantly. Each match records its
character span, so the counsellor sees *which words* fired the flag.

Adding a rule is one line in `RULES`. Keep patterns narrow: a false trigger
wastes a counsellor's time, so precision matters more than recall.

### Guardrails on the model

`backend/ai/nlp.py` validates everything before it reaches the scorer: scores
clamped to 0–100, flags coerced to booleans, recommendations filtered against the
fixed list of six. The model cannot invent a recommendation or push a score out
of range.

---

## 5. Demo script (about 3 minutes)

1. Open the link. It goes straight to the console and the console is empty - say
   so out loud, it is the honest starting point and it makes the next step land
   harder. (`admin / admin123` still signs in a named account at `/login`.)
2. **+ Upload Call → Load a sample →** `01_low_risk_information_request.txt`.
   Tick consent, **Run assessment**. Lands **Low**, safety floor *Not Triggered*.
3. Repeat with `02...` (**Moderate**) and `05...` (**High**). Point at the donut
   and the stat cards updating live.
4. Now `04_critical_safety_floor_trigger.txt`. It lands **Critical**, and the card
   lists the exact phrases that fired the rules.
5. Say out loud: *"the model scored distress at only 29 here — the model never
   decides this one. Those rules run outside it, so a calm-sounding caller in
   real danger still gets escalated."*
6. Click **Mark as under review** -> status changes, Under Support increments.
7. Scroll to **Why this case scored N**. Read one line out loud: the cue, the
   words it matched, the points it added. That is the difference between this and
   a sentiment score.
8. **Pending Review** -> the queue, dated and ordered by SVI. **Reports** -> open
   the audio case, play the recording, show the transcript with the rule matches
   highlighted in place.
9. **Settings** -> flip to dark, refresh the page, show that nothing was lost.
10. The one to finish on: **Live Call -> Start**. Speak as the caller - start
    calm, then say the threat out loud. The transcript fills in as you talk and
    the SVI jumps to Critical the moment the words land, with the matched phrase
    named underneath. **End Call** saves it like any other case.

---

## 6. Deploying it

### Render (easiest, free tier is enough)

1. Push this folder to a GitHub repo.
2. On render.com → **New → Blueprint** → point it at the repo. `render.yaml` is
   already here, so Render fills in the build and start commands itself.
3. In the service's **Environment** tab add `OPENAI_API_KEY` if you want the full
   AI path, and `SEED_ADMIN_PASSWORD` to something other than `admin123`.
4. Deploy. Your URL is `https://navhridya.onrender.com` (or whatever you named it).

Health check is at `/api/health`. The free tier sleeps after inactivity — open
the URL a minute before you present.

### Railway / Fly / any PaaS

`Procfile` and `runtime.txt` are included, so:

```
build:  pip install -r requirements-deploy.txt
start:  uvicorn backend.app:app --host 0.0.0.0 --port $PORT
```

Set `NAVHRIDYA_SECRET` to a random string and `OPENAI_API_KEY` if you want the
full path.

### Sharing a local run temporarily

```bash
python run.py --host 0.0.0.0        # then share your LAN IP, e.g. http://192.168.1.5:8000
```

### One thing to change before any real deployment

SQLite and local file uploads are fine for a prototype and for a judged demo.
For anything real you would move to PostgreSQL and object storage, and replace
the seeded `admin/admin123` account with proper user management.

---

## 7. Honest limits

- SVI weights and the 40/60/80 thresholds are **proposed design choices for the
  prototype, not clinically validated.** Say this before a judge asks.
- The prototype has never seen real NHAA call data. It has only been exercised on
  role-played transcripts.
- The local fallback analyser is a lexicon, not a language model, and is labelled
  as such everywhere it is used.
- `admin/admin123` is a seeded demo credential, not a security design.

---

## 8. Layout

```
run.py / run.bat / run.sh     one-command launcher
backend/
  app.py            HTTP routes — Starlette, upgrades itself to FastAPI if installed
  services.py       business logic, framework independent
  database.py       SQLite on the standard library
  security.py       PBKDF2 passwords + signed tokens
  live.py           live call sessions, running transcript and scores
  ai/
    live_asr.py     speech to text for a call in progress
    deepgram_stream.py  WebSocket streaming - opt-in, never run
    pipeline.py     the six steps, in order
    svi.py          scoring arithmetic            ← tested
    safety_rules.py deterministic rule engine     ← tested
    nlp.py          GPT-4o-mini + validation + local fallback
    asr.py          Whisper API / faster-whisper / pasted text
frontend/
  index.html        public homepage
  auth.html         sign in + create account
  app.html          the operator console shell
  assets/base.css   design tokens, light and dark
  assets/common.js  icons, theme, footer, toast
  assets/app.js     hash router + all five pages
samples/            five transcripts, one per risk band
tests/              46 tests
data/               SQLite db + uploaded audio (created on first run)
```
