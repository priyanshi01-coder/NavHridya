"""SQLite storage, on the standard library only.

No ORM install step: `sqlite3` ships with Python. The schema mirrors the data
model in the spec, and every SVI term is stored in its own column so the
dashboard can show the working rather than just the answer.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("NAVHRIDYA_DB", os.path.join(ROOT, "data", "navhridya.db"))
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'counsellor',
    full_name     TEXT NOT NULL DEFAULT '',
    email         TEXT NOT NULL DEFAULT '',
    centre        TEXT NOT NULL DEFAULT 'NHAA 14566 - National Helpline Against Atrocities',
    theme         TEXT NOT NULL DEFAULT 'light',
    is_guest      INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cases (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id                TEXT UNIQUE NOT NULL,
    uploaded_by            INTEGER REFERENCES users(id),
    audio_filename         TEXT,
    channel                TEXT NOT NULL DEFAULT 'Call',
    language               TEXT NOT NULL DEFAULT 'Hindi',
    uploaded_at            TEXT NOT NULL,
    transcript             TEXT NOT NULL DEFAULT '',
    asr_engine             TEXT,
    nlp_engine             TEXT,
    distress_score         INTEGER NOT NULL DEFAULT 0,
    danger_score           INTEGER NOT NULL DEFAULT 0,
    base_score             REAL    NOT NULL DEFAULT 0,
    indicator_bonus        INTEGER NOT NULL DEFAULT 0,
    safety_floor_triggered INTEGER NOT NULL DEFAULT 0,
    safety_floor_applied   INTEGER NOT NULL DEFAULT 0,
    svi_score              INTEGER NOT NULL DEFAULT 0,
    svi_category           TEXT    NOT NULL DEFAULT 'Low',
    indicators             TEXT    NOT NULL DEFAULT '{}',
    safety_matches         TEXT    NOT NULL DEFAULT '[]',
    evidence_spans         TEXT    NOT NULL DEFAULT '[]',
    recommendations        TEXT    NOT NULL DEFAULT '[]',
    summary                TEXT    NOT NULL DEFAULT '',
    status                 TEXT    NOT NULL DEFAULT 'Pending',
    processing_seconds     REAL    NOT NULL DEFAULT 0,
    engine_note            TEXT,
    distress_reasons       TEXT    NOT NULL DEFAULT '[]',
    danger_reasons         TEXT    NOT NULL DEFAULT '[]',
    score_explanation      TEXT    NOT NULL DEFAULT '[]',
    audio_original_name    TEXT,
    audio_bytes            INTEGER NOT NULL DEFAULT 0,
    audio_duration_seconds REAL    NOT NULL DEFAULT 0,
    is_live_call           INTEGER NOT NULL DEFAULT 0,
    live_duration_seconds  REAL    NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS call_snapshots (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    case_id                INTEGER REFERENCES cases(id) ON DELETE CASCADE,
    at_seconds             REAL    NOT NULL DEFAULT 0,
    taken_at               TEXT    NOT NULL,
    distress_score         INTEGER NOT NULL DEFAULT 0,
    danger_score           INTEGER NOT NULL DEFAULT 0,
    safety_floor_triggered INTEGER NOT NULL DEFAULT 0,
    svi_score              INTEGER NOT NULL DEFAULT 0,
    svi_category           TEXT    NOT NULL DEFAULT 'Low'
);

CREATE INDEX IF NOT EXISTS idx_snapshots_case ON call_snapshots(case_id, at_seconds);

-- One row per day, holding the last case number handed out. Kept separately
-- from the cases themselves so deleting a case never frees its reference for
-- reuse: a case number a counsellor has written down must not come back
-- attached to a different call.
CREATE TABLE IF NOT EXISTS case_counters (
    day  TEXT PRIMARY KEY,
    last INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_cases_created ON cases(id DESC);
"""

JSON_COLUMNS = ("indicators", "safety_matches", "evidence_spans", "recommendations",
                "distress_reasons", "danger_reasons", "score_explanation")
BOOL_COLUMNS = ("safety_floor_triggered", "safety_floor_applied", "is_live_call")


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


_conn: Optional[sqlite3.Connection] = None


MIGRATIONS = {
    "users": {
        "full_name": "TEXT NOT NULL DEFAULT \'\'",
        "email": "TEXT NOT NULL DEFAULT \'\'",
        "centre": "TEXT NOT NULL DEFAULT \'\'",
        "theme": "TEXT NOT NULL DEFAULT \'light\'",
        "is_guest": "INTEGER NOT NULL DEFAULT 0",
    },
    "cases": {
        "engine_note": "TEXT",
        "distress_reasons": "TEXT NOT NULL DEFAULT \'[]\'",
        "danger_reasons": "TEXT NOT NULL DEFAULT \'[]\'",
        "score_explanation": "TEXT NOT NULL DEFAULT \'[]\'",
        "audio_original_name": "TEXT",
        "audio_bytes": "INTEGER NOT NULL DEFAULT 0",
        "audio_duration_seconds": "REAL NOT NULL DEFAULT 0",
        "is_live_call": "INTEGER NOT NULL DEFAULT 0",
        "live_duration_seconds": "REAL NOT NULL DEFAULT 0",
    },
}


def _migrate(c: sqlite3.Connection) -> None:
    """Add any column a newer build expects but an existing file lacks.

    SQLite has no ALTER TABLE IF NOT EXISTS, so the existing columns are read
    first. This keeps a database created by an earlier version usable instead of
    failing with "no such column" on the first query.
    """
    for table, columns in MIGRATIONS.items():
        have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
        for name, decl in columns.items():
            if name not in have:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    c.commit()


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = _connect()
        _conn.executescript(SCHEMA)
        _conn.commit()
        _migrate(_conn)
    return _conn


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ------------------------------------------------------------------- users
DEFAULT_CENTRE = "NHAA 14566 - National Helpline Against Atrocities"


def create_user(username: str, password_hash: str, role: str = "counsellor",
                full_name: str = "", email: str = "",
                centre: str = DEFAULT_CENTRE, is_guest: bool = False) -> int:
    with _lock:
        cur = conn().execute(
            "INSERT INTO users (username, password_hash, role, full_name, email, centre, "
            "is_guest, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (username, password_hash, role, full_name, email, centre,
             1 if is_guest else 0, utcnow()),
        )
        conn().commit()
        return int(cur.lastrowid)


def update_user(user_id: int, **fields) -> None:
    allowed = {"full_name", "email", "centre", "theme", "password_hash"}
    sets = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not sets:
        return
    clause = ", ".join(f"{k} = ?" for k in sets)
    with _lock:
        conn().execute(f"UPDATE users SET {clause} WHERE id = ?",
                       (*sets.values(), user_id))
        conn().commit()


def get_user_by_id(user_id: int) -> Optional[sqlite3.Row]:
    return conn().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def delete_user(user_id: int) -> Dict[str, Any]:
    """Remove the account and every case it uploaded.

    Returns the number of cases deleted and the saved audio names, so the caller
    can remove those files from disk too. The two are not the same number: a
    case created from a pasted transcript has no recording.
    """
    rows = conn().execute(
        "SELECT audio_filename FROM cases WHERE uploaded_by = ?", (user_id,)).fetchall()
    files = [r["audio_filename"] for r in rows if r["audio_filename"]]
    with _lock:
        conn().execute(
            "DELETE FROM call_snapshots WHERE case_id IN "
            "(SELECT id FROM cases WHERE uploaded_by = ?)", (user_id,))
        conn().execute("DELETE FROM cases WHERE uploaded_by = ?", (user_id,))
        conn().execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn().commit()
    return {"cases": len(rows), "files": files}


def get_user(username: str) -> Optional[sqlite3.Row]:
    return conn().execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()


def count_users() -> int:
    return int(conn().execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"])


# ------------------------------------------------------------------- cases
def next_case_id() -> str:
    """The next case reference for today, e.g. #C20260928-0004.

    Handed out by a counter, not by counting rows. Counting rows reuses a
    reference after a deletion - which both collides with the unique index and,
    worse, could put an old reference on a new call.
    """
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    with _lock:
        c = conn()
        c.execute("INSERT OR IGNORE INTO case_counters (day, last) VALUES (?, 0)", (day,))
        # keep the counter ahead of anything a previous build already issued
        row = c.execute("SELECT MAX(CAST(substr(case_id, -4) AS INTEGER)) AS m FROM cases "
                        "WHERE case_id LIKE ?", (f"#C{day}-%",)).fetchone()
        seen = int(row["m"] or 0)
        c.execute("UPDATE case_counters SET last = MAX(last, ?) + 1 WHERE day = ?", (seen, day))
        nxt = int(c.execute("SELECT last FROM case_counters WHERE day = ?", (day,))
                  .fetchone()["last"])
        c.commit()
    return f"#C{day}-{nxt:04d}"


def insert_case(row: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(row)
    for col in JSON_COLUMNS:
        payload[col] = json.dumps(payload.get(col, {} if col == "indicators" else []))
    for col in BOOL_COLUMNS:
        payload[col] = 1 if payload.get(col) else 0
    payload.setdefault("uploaded_at", utcnow())
    payload = {k: v for k, v in payload.items() if v is not None or k == "engine_note"}

    cols = ", ".join(payload)
    marks = ", ".join("?" for _ in payload)
    with _lock:
        for attempt in range(6):
            try:
                cur = conn().execute(
                    f"INSERT INTO cases ({cols}) VALUES ({marks})", tuple(payload.values()))
                break
            except sqlite3.IntegrityError:
                # another upload took this reference between our read and write
                payload["case_id"] = next_case_id()
                if attempt == 5:
                    raise
        conn().commit()
        return get_case(int(cur.lastrowid))


def _hydrate(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    for col in JSON_COLUMNS:
        try:
            d[col] = json.loads(d.get(col) or ("{}" if col == "indicators" else "[]"))
        except json.JSONDecodeError:
            d[col] = {} if col == "indicators" else []
    for col in BOOL_COLUMNS:
        d[col] = bool(d.get(col))
    return d


def get_case(case_pk: int) -> Optional[Dict[str, Any]]:
    row = conn().execute("SELECT * FROM cases WHERE id = ?", (case_pk,)).fetchone()
    return _hydrate(row) if row else None


# Each account sees only the calls it uploaded. On a public demo link every
# visitor gets their own session, so one person's uploads never appear in
# somebody else's console - and a first visit is genuinely empty.
def list_cases(limit: int = 200, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
    if user_id is None:
        rows = conn().execute(
            "SELECT * FROM cases ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    else:
        rows = conn().execute(
            "SELECT * FROM cases WHERE uploaded_by = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit)).fetchall()
    return [_hydrate(r) for r in rows]


def get_case_by_case_id(case_id: str) -> Optional[Dict[str, Any]]:
    row = conn().execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
    return _hydrate(row) if row else None


def pending_cases(limit: int = 200, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
    if user_id is None:
        rows = conn().execute(
            "SELECT * FROM cases WHERE status IN ('Pending','In Progress') "
            "ORDER BY svi_score DESC, id DESC LIMIT ?", (limit,)).fetchall()
    else:
        rows = conn().execute(
            "SELECT * FROM cases WHERE status IN ('Pending','In Progress') "
            "AND uploaded_by = ? ORDER BY svi_score DESC, id DESC LIMIT ?",
            (user_id, limit)).fetchall()
    return [_hydrate(r) for r in rows]


def count_cases(user_id: Optional[int] = None) -> int:
    if user_id is None:
        return int(conn().execute("SELECT COUNT(*) AS n FROM cases").fetchone()["n"])
    return int(conn().execute(
        "SELECT COUNT(*) AS n FROM cases WHERE uploaded_by = ?", (user_id,)).fetchone()["n"])


def backdate_case(case_pk: int, when: str) -> None:
    with _lock:
        conn().execute("UPDATE cases SET uploaded_at = ? WHERE id = ?", (when, case_pk))
        conn().commit()


def delete_case(case_pk: int) -> Optional[str]:
    row = conn().execute("SELECT audio_filename FROM cases WHERE id = ?",
                         (case_pk,)).fetchone()
    if not row:
        return None
    with _lock:
        conn().execute("DELETE FROM call_snapshots WHERE case_id = ?", (case_pk,))
        conn().execute("DELETE FROM cases WHERE id = ?", (case_pk,))
        conn().commit()
    return row["audio_filename"]


def set_status(case_pk: int, status: str) -> Optional[Dict[str, Any]]:
    with _lock:
        conn().execute("UPDATE cases SET status = ? WHERE id = ?", (status, case_pk))
        conn().commit()
    return get_case(case_pk)


# ------------------------------------------------------- live-call snapshots
def add_snapshots(case_pk: int, snapshots: List[Dict[str, Any]]) -> int:
    """Store the running scores taken while a live call was in progress.

    Kept so the case can later show how the risk moved during the call - the
    moment a caller disclosed a threat is visible as a step in the line.
    """
    if not snapshots:
        return 0
    rows = [(case_pk, s.get("at", 0.0), s.get("clock") or utcnow(),
             int(s.get("distress_score", 0)), int(s.get("danger_score", 0)),
             1 if s.get("safety_floor_triggered") else 0,
             int(s.get("svi_score", 0)), s.get("svi_category", "Low"))
            for s in snapshots]
    with _lock:
        conn().executemany(
            "INSERT INTO call_snapshots (case_id, at_seconds, taken_at, distress_score, "
            "danger_score, safety_floor_triggered, svi_score, svi_category) "
            "VALUES (?,?,?,?,?,?,?,?)", rows)
        conn().commit()
    return len(rows)


def snapshots_for(case_pk: int) -> List[Dict[str, Any]]:
    rows = conn().execute(
        "SELECT * FROM call_snapshots WHERE case_id = ? ORDER BY at_seconds",
        (case_pk,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["safety_floor_triggered"] = bool(d["safety_floor_triggered"])
        out.append(d)
    return out


def stats(user_id: Optional[int] = None) -> Dict[str, Any]:
    """Headline numbers for the dashboard.

    These count the *active* queue - everything not yet marked Resolved. A
    counsellor who has worked through every case should see the console back at
    zero, the way it looked before the first upload, rather than a tally of work
    already finished. Nothing is hidden: Reports still lists every case ever
    scored, and `archived_cases` says how many have been closed.
    """
    c = conn()
    scope = " WHERE uploaded_by = ?" if user_id is not None else ""
    where = " AND uploaded_by = ?" if user_id is not None else ""
    params: tuple = (user_id,) if user_id is not None else ()

    active = " status <> 'Resolved'"
    total = int(c.execute(
        f"SELECT COUNT(*) AS n FROM cases WHERE{active}{where}", params).fetchone()["n"])
    high = int(c.execute(
        f"SELECT COUNT(*) AS n FROM cases WHERE{active} AND "
        f"svi_category IN ('High','Critical'){where}", params).fetchone()["n"])
    under = int(c.execute(
        f"SELECT COUNT(*) AS n FROM cases WHERE status = 'In Progress'{where}",
        params).fetchone()["n"])
    archived = int(c.execute(
        f"SELECT COUNT(*) AS n FROM cases WHERE status = 'Resolved'{where}",
        params).fetchone()["n"])
    every = int(c.execute(f"SELECT COUNT(*) AS n FROM cases{scope}", params).fetchone()["n"])
    avg = c.execute(
        f"SELECT AVG(processing_seconds) AS a FROM cases WHERE{active}{where}",
        params).fetchone()["a"] or 0.0
    return {
        "total_cases": total,
        "high_risk": high,
        "under_support": under,
        "archived_cases": archived,
        "cases_ever": every,
        "avg_response_time_seconds": round(float(avg), 4),
    }


def risk_distribution(user_id: Optional[int] = None) -> Dict[str, Any]:
    counts = {"Low": 0, "Moderate": 0, "High": 0, "Critical": 0}
    sql = "SELECT svi_category, COUNT(*) AS n FROM cases WHERE status <> 'Resolved'"
    params: tuple = ()
    if user_id is not None:
        sql += " AND uploaded_by = ?"
        params = (user_id,)
    for r in conn().execute(sql + " GROUP BY svi_category", params):
        if r["svi_category"] in counts:
            counts[r["svi_category"]] = int(r["n"])
    return {"counts": counts, "total": sum(counts.values())}
