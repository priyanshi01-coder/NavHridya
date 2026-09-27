/* NAVHRIDYA operator app.
   A hash-routed single page: Dashboard, Upload Call, Pending Review, Reports,
   Settings. Plain DOM and hand-drawn SVG, so there is no build step and no CDN
   - the whole thing renders with the venue wifi unplugged.

   Every number shown here is read back from the database over the API. Nothing
   on this page is hardcoded, which is also why a browser refresh loses nothing:
   the state lives on the server, not in the tab. */

/* Somebody following the deployed link lands here, not on a sign-in wall.
   With no token we open a private guest workspace for them - empty, and never
   shared with the next visitor - rather than redirecting them away. */
let TOKEN = localStorage.getItem('nav_token');

async function openGuestSession() {
  const res = await fetch('/api/auth/guest', { method: 'POST' });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'Could not start a session.');
  TOKEN = data.token;
  localStorage.setItem('nav_token', TOKEN);
  localStorage.setItem('nav_user', JSON.stringify(data.user || {}));
  localStorage.removeItem('nav_case');
  return data.user;
}

/* Chart colours are read from the stylesheet so the SVGs follow the theme. */
const cssVar = (n) =>
  getComputedStyle(document.documentElement).getPropertyValue(n).trim() || '#888';
const risk = () => ({
  Low: cssVar('--low'), Moderate: cssVar('--mod'),
  High: cssVar('--high'), Critical: cssVar('--crit'),
});
const riskBg = () => ({
  Low: cssVar('--low-bg'), Moderate: cssVar('--mod-bg'),
  High: cssVar('--high-bg'), Critical: cssVar('--crit-bg'),
});
const ORDER = ['Low', 'Moderate', 'High', 'Critical'];
const STATUSES = ['Pending', 'In Progress', 'Resolved', 'Escalated'];
const statusColour = (s) => ({
  Pending: ['--mod-bg', '--mod'], 'In Progress': ['--surface-3', '--text'],
  Resolved: ['--low-bg', '--low'], Escalated: ['--crit-bg', '--crit'],
}[s] || ['--surface-3', '--text']);

const RECO_ICON = {
  'Immediate Counselling': 'headset', 'Legal Aid Support': 'scale',
  'Police Intervention (if required)': 'shield', 'Medical Assistance': 'cross',
  'Consider Witness Protection': 'eye', 'Follow-up within 24 hours': 'calendar',
};

const bandOf = (v) => (v >= 80 ? 'Critical' : v >= 60 ? 'High' : v >= 40 ? 'Moderate' : 'Low');
const pill = (text, bgVar, fgVar) =>
  `<span class="pill" style="background:var(${bgVar});color:var(${fgVar})">${esc(text)}</span>`;
const riskPill = (b) => pill(b, `--${{ Low: 'low', Moderate: 'mod', High: 'high', Critical: 'crit' }[b] || 'low'}-bg`,
  `--${{ Low: 'low', Moderate: 'mod', High: 'high', Critical: 'crit' }[b] || 'low'}`);
const statusPill = (s) => { const [bg, fg] = statusColour(s); return pill(s, bg, fg); };
const fmtSecs = (s) => (!s ? '-' : s >= 1 ? Number(s).toFixed(1) + 's'
  : Math.max(1, Math.round(s * 1000)) + 'ms');
const label = (k) => String(k).replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
const fmtBytes = (n) => (!n ? '-' : n > 1048576 ? (n / 1048576).toFixed(1) + ' MB'
  : Math.max(1, Math.round(n / 1024)) + ' KB');

const fmtDate = (iso) => new Date(iso).toLocaleDateString([], {
  day: '2-digit', month: 'short', year: 'numeric' });
const fmtTime = (iso) => new Date(iso).toLocaleTimeString([], {
  hour: '2-digit', minute: '2-digit' });
const fmtStamp = (iso) => `${fmtDate(iso)}, ${fmtTime(iso)}`;
function ago(iso) {
  const mins = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return mins + ' min ago';
  const h = Math.round(mins / 60);
  if (h < 24) return h + (h === 1 ? ' hour ago' : ' hours ago');
  const d = Math.round(h / 24);
  return d + (d === 1 ? ' day ago' : ' days ago');
}

/* --------------------------------------------------------------------- api */
async function api(path, opts = {}) {
  const res = await fetch('/api' + path, {
    ...opts,
    headers: { Authorization: 'Bearer ' + TOKEN, ...(opts.headers || {}) },
  });
  if (res.status === 401) { signOut(); throw new Error('Session expired'); }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || 'Request failed');
  return data;
}
const apiJson = (path, method, body) => api(path, {
  method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });

function signOut() {
  localStorage.removeItem('nav_token');
  localStorage.removeItem('nav_user');
  localStorage.removeItem('nav_case');
  /* clear the HttpOnly session cookie too, then leave for the public site */
  fetch('/api/auth/logout', { method: 'POST' })
    .catch(() => {})
    .then(() => location.replace('/home'));
}

/* ------------------------------------------------------------------- state */
const S = {
  me: null, cases: [], stats: null, dist: null,
  blurbs: {}, samples: [], selected: null, ready: false,
};

async function loadAll() {
  const [me, cases, stats, dist, recos, samples] = await Promise.all([
    api('/auth/me'), api('/cases'), api('/dashboard/stats'),
    api('/dashboard/risk-distribution'), api('/meta/recommendations'), api('/meta/samples'),
  ]);
  S.me = me; S.cases = cases; S.stats = stats; S.dist = dist; S.samples = samples;
  (recos || []).forEach((r) => { S.blurbs[r.title] = r.blurb; });
  const want = Number(localStorage.getItem('nav_case')) || null;
  S.selected = cases.find((c) => c.id === want) || cases[0] || null;
  S.ready = true;
}

/** Engine and timing detail belongs in the console, not in front of a counsellor. */
function logPipeline(c) {
  if (!c) return;
  try {
    console.info(`[navhridya] ${c.case_id}: ${c.asr_engine} -> ${c.nlp_engine} -> SVI `
      + `${c.svi_score} (${c.svi_category}) in ${c.processing_seconds}s`);
  } catch (e) { /* console unavailable */ }
}

function select(id) {
  S.selected = S.cases.find((c) => c.id === id) || null;
  if (S.selected) { localStorage.setItem('nav_case', String(id)); logPipeline(S.selected); }
}

/* -------------------------------------------------------------------- nav */
const PAGES = [
  ['dashboard', 'Dashboard', 'grid'],
  ['live', 'Live Call', 'mic'],
  ['upload', 'Upload Call', 'upload'],
  ['pending', 'Pending Review', 'clock'],
  ['reports', 'Reports', 'chart'],
  ['settings', 'Settings', 'gear'],
];

function route() {
  const h = (location.hash || '').replace(/^#\/?/, '').split('?')[0];
  return PAGES.some(([k]) => k === h) ? h : 'dashboard';
}

function renderChrome() {
  const here = route();
  const pending = S.cases.filter((c) => c.status === 'Pending').length;
  $('tabs').innerHTML = PAGES.map(([key, name, ic]) =>
    `<a class="tab ${key === here ? 'active' : ''}" href="#/${key}">${icon(ic, 15)} ${name}${
      key === 'pending' && pending ? `<span class="badge">${pending}</span>` : ''}</a>`).join('');
  const me = S.me || {};
  $('who').innerHTML = me.username
    ? (me.is_guest
      ? `<b>Guest session</b><small>not signed in</small>`
      : `<b>${esc(me.full_name || me.username)}</b><small>${esc(label(me.role || 'counsellor'))}</small>`)
    : '';
  $('signout').innerHTML = me.is_guest
    ? icon('user', 15) + ' Sign in'
    : icon('logout', 15) + ' Sign out';
}

/* ------------------------------------------------------------- gauge/donut */
function gauge(value, category) {
  const R = risk();
  const CX = 110, CY = 104, RAD = 78;
  const at = (v) => {
    const a = ((180 - (Math.max(0, Math.min(100, v)) / 100) * 180) * Math.PI) / 180;
    return [CX + RAD * Math.cos(a), CY - RAD * Math.sin(a)];
  };
  const arc = (a, b) => {
    const [x1, y1] = at(a), [x2, y2] = at(b);
    return `M ${x1} ${y1} A ${RAD} ${RAD} 0 0 1 ${x2} ${y2}`;
  };
  const segs = [[0, 40, R.Low], [40, 60, R.Moderate], [60, 80, R.High], [80, 100, R.Critical]];
  const ang = ((180 - (value / 100) * 180) * Math.PI) / 180;
  const nx = CX + (RAD - 20) * Math.cos(ang), ny = CY - (RAD - 20) * Math.sin(ang);
  const needle = cssVar('--text-2');
  return `<svg viewBox="0 0 220 124" style="width:100%;max-width:240px;display:block;margin:0 auto"
      role="img" aria-label="SVI ${value} of 100, ${category}">
    ${segs.map(([a, b, c]) =>
      `<path d="${arc(a + 0.7, b - 0.7)}" stroke="${c}" stroke-width="15" fill="none"/>`).join('')}
    <line x1="${CX}" y1="${CY}" x2="${nx.toFixed(1)}" y2="${ny.toFixed(1)}" stroke="${needle}"
      stroke-width="3.5" stroke-linecap="round"/>
    <circle cx="${CX}" cy="${CY}" r="6" fill="${needle}"/>
    <text x="${CX}" y="${CY - 26}" text-anchor="middle"
      style="font:750 33px Inter,sans-serif;fill:${R[category] || R.Low}">${value}<tspan
      style="font:600 13px Inter,sans-serif;fill:${cssVar('--faint')}"> /100</tspan></text>
  </svg>`;
}

function donut(counts, total) {
  if (!total) return `<div class="empty" style="height:170px;display:grid;place-items:center">
    No cases yet.<br/>Upload a call to populate this chart.</div>`;
  const R = risk();
  const CX = 88, CY = 88, RAD = 62, W = 24;
  let start = -90, paths = '';
  ORDER.forEach((k) => {
    const n = counts[k] || 0; if (!n) return;
    let sweep = (n / total) * 360;
    if (sweep >= 359.9) sweep = 359.9;
    const end = start + sweep;
    const p = (deg) => [CX + RAD * Math.cos((deg * Math.PI) / 180),
      CY + RAD * Math.sin((deg * Math.PI) / 180)];
    const [x1, y1] = p(start), [x2, y2] = p(end);
    paths += `<path d="M ${x1} ${y1} A ${RAD} ${RAD} 0 ${sweep > 180 ? 1 : 0} 1 ${x2} ${y2}"
      stroke="${R[k]}" stroke-width="${W}" fill="none"/>`;
    start = end;
  });
  return `<svg viewBox="0 0 176 176" style="width:100%;max-width:190px">${paths}
    <text x="${CX}" y="${CY - 2}" text-anchor="middle"
      style="font:750 24px Inter,sans-serif;fill:${cssVar('--text')}">${total}</text>
    <text x="${CX}" y="${CY + 15}" text-anchor="middle"
      style="font:400 10px Inter,sans-serif;fill:${cssVar('--faint')}">Total Cases</text></svg>`;
}

/** Horizontal bars of case volume per day, used on Reports. */
function trendBars(cases) {
  const days = [];
  for (let i = 6; i >= 0; i--) {
    const d = new Date(); d.setDate(d.getDate() - i);
    days.push({ key: d.toDateString(), lbl: d.toLocaleDateString([], { weekday: 'short' }), n: 0, high: 0 });
  }
  cases.forEach((c) => {
    const k = new Date(c.uploaded_at).toDateString();
    const slot = days.find((d) => d.key === k);
    if (slot) { slot.n += 1; if (c.svi_score >= 60) slot.high += 1; }
  });
  const max = Math.max(1, ...days.map((d) => d.n));
  const R = risk();
  return `<div style="margin-top:14px">${days.map((d) => `
    <div style="display:flex;align-items:center;gap:10px;padding:3px 0">
      <span style="width:34px;font-size:11.5px;color:var(--muted)">${d.lbl}</span>
      <span style="flex:1;height:16px;background:var(--surface-2);border-radius:5px;overflow:hidden;display:flex">
        <span style="width:${(d.high / max) * 100}%;background:${R.High}"></span>
        <span style="width:${((d.n - d.high) / max) * 100}%;background:${R.Low}"></span>
      </span>
      <span style="width:22px;text-align:right;font-size:12px;font-weight:700">${d.n}</span>
    </div>`).join('')}
    <p class="hint" style="display:flex;gap:14px;margin-top:8px">
      <span><span style="display:inline-block;width:9px;height:9px;border-radius:2px;background:${R.High}"></span>
        SVI 60+</span>
      <span><span style="display:inline-block;width:9px;height:9px;border-radius:2px;background:${R.Low}"></span>
        below 60</span></p></div>`;
}

/* ------------------------------------------------------- reason components */
function reasonList(items, colourVar) {
  if (!items || !items.length) return '<p class="hint">No reasons were recorded.</p>';
  return `<ul class="why">${items.map((r) =>
    `<li><span class="bullet" style="background:var(${colourVar})"></span>
      <span>${esc(r)}</span></li>`).join('')}</ul>`;
}

/** The full "why this score" block: both axes, the arithmetic trail, the rules. */
function whyBlock(c) {
  const dB = bandOf(c.distress_score), gB = bandOf(c.danger_score);
  return `
    <div class="whyhead">${icon('info', 14)} Why distress scored ${c.distress_score}
      <span class="score" style="color:var(--${{ Low: 'low', Moderate: 'mod', High: 'high', Critical: 'crit' }[dB]})">
        ${dB}</span></div>
    ${reasonList(c.distress_reasons, '--mod')}
    <div class="whyhead">${icon('alert', 14)} Why danger scored ${c.danger_score}
      <span class="score" style="color:var(--${{ Low: 'low', Moderate: 'mod', High: 'high', Critical: 'crit' }[gB]})">
        ${gB}</span></div>
    ${reasonList(c.danger_reasons, '--crit')}
    <div class="whyhead">${icon('layers', 14)} How the SVI was computed</div>
    <ol class="trail">${(c.score_explanation || []).map((l) => `<li>${esc(l)}</li>`).join('')
      || '<li>No trail was recorded for this case.</li>'}</ol>
    ${(c.safety_matches || []).length ? `
      <div class="whyhead">${icon('shield', 14)} Safety rules that fired outside the model</div>
      <ul class="why">${c.safety_matches.map((m) =>
        `<li><span class="bullet" style="background:var(--crit)"></span>
          <span><b style="color:var(--crit)">${esc(m.label)}</b> -
          matched &ldquo;${esc(m.matched_text)}&rdquo; at character ${m.start}</span></li>`).join('')}</ul>`
      : `<div class="whyhead">${icon('shield', 14)} Safety rules</div>
         <p class="hint">No deterministic safety rule matched this transcript, so no floor was
           applied.</p>`}`;
}

function recoList(c) {
  const list = c.recommendations || [];
  return `<ul class="recos">${list.length ? list.map((r) =>
    `<li>${icon(RECO_ICON[r] || 'spark')}<div><b>${esc(r)}</b>
      <span>${esc(S.blurbs[r] || '')}</span></div></li>`).join('')
    : '<li style="color:var(--faint)">No recommendations were returned for this transcript.</li>'}</ul>`;
}

/** Transcript with every safety-rule match highlighted in place. */
function highlighted(c) {
  const text = c.transcript || '';
  const spans = (c.safety_matches || [])
    .filter((m) => Number.isInteger(m.start) && Number.isInteger(m.end))
    .sort((a, b) => a.start - b.start);
  let out = '', at = 0;
  spans.forEach((m) => {
    if (m.start < at) return;
    out += esc(text.slice(at, m.start));
    out += `<mark title="${esc(m.label)}">${esc(text.slice(m.start, m.end))}</mark>`;
    at = m.end;
  });
  out += esc(text.slice(at));
  return out || '<span style="color:var(--faint)">No transcript stored.</span>';
}

/* ------------------------------------------------------- first-run state */
/** Shown on every list page while the console is still empty.
 *  A new deployment has no cases, and inventing some would be a lie - so the
 *  page says what to do instead of drawing charts of nothing. */
function firstRun(title, line) {
  return `
  <div class="card" style="margin-top:14px;text-align:center;padding:44px 22px">
    <div style="width:56px;height:56px;border-radius:16px;background:var(--accent-soft);
      color:var(--accent);display:grid;place-items:center;margin:0 auto 16px">
      ${icon('upload', 26)}</div>
    <h2 style="font-size:20px">${esc(title)}</h2>
    <p style="color:var(--muted);margin:9px auto 0;max-width:34em;font-size:14.5px">
      ${esc(line)}</p>

    <div style="display:flex;gap:10px;justify-content:center;flex-wrap:wrap;margin-top:22px">
      <a class="btn btn-primary" href="#/upload">${icon('upload', 16)} Upload a call</a>
      <a class="btn btn-outline" href="#/upload" data-sample="1">${icon('text', 16)}
        Try a sample transcript</a>
    </div>

    <div style="max-width:660px;margin:30px auto 0;text-align:left">
      <p style="font-size:12px;font-weight:750;letter-spacing:.7px;text-transform:uppercase;
        color:var(--muted);margin:0 0 10px">What happens when you do</p>
      <ol class="trail" style="margin:0">
        <li>The recording is transcribed, or you paste the transcript yourself.</li>
        <li>Deterministic safety rules are checked first, outside the model.</li>
        <li>Distress and danger are scored separately, each with written reasons.</li>
        <li>The SVI is computed in plain arithmetic and the case joins the queue.</li>
      </ol>
    </div>
  </div>`;
}

/* ===================================================================== */
/*  PAGE: Dashboard                                                      */
/* ===================================================================== */
function pageDashboard() {
  if (!S.cases.length) {
    return `
    <div class="phead">
      <div><h1>Operator Dashboard</h1>
        <p class="sub">Real-time monitoring of victim distress and case management</p></div>
      <div class="clock" id="clock"></div>
    </div>
    ${firstRun('No cases yet',
      'This console starts empty. Upload a recorded call, or paste a transcript, and the '
      + 'first case will appear here within a few seconds - scored, with the reasons behind '
      + 'the score.')}`;
  }

  const st = S.stats || {};
  const total = S.cases.length;
  const today = new Date().toDateString();
  const todayN = S.cases.filter((c) => new Date(c.uploaded_at).toDateString() === today).length;
  const pct = (n) => (total ? Math.round((n / total) * 100) : 0);
  const cards = [
    ['files', '--surface-3', '--text', 'Total Cases', st.total_cases ?? 0,
      `${todayN} added today`],
    ['alert', '--crit-bg', '--crit', 'High Risk', st.high_risk ?? 0,
      `${pct(st.high_risk || 0)}% of all cases`],
    ['people', '--low-bg', '--low', 'Under Support', st.under_support ?? 0,
      `${pct(st.under_support || 0)}% of all cases`],
    ['clock', '--mod-bg', '--mod', 'Avg. Processing Time',
      fmtSecs(st.avg_response_time_seconds || 0), 'upload to scored case'],
  ];

  const c = S.selected;
  const d = S.dist || { counts: {}, total: 0 };
  const hc = d.total ? Math.round((((d.counts.High || 0) + (d.counts.Critical || 0)) / d.total) * 100) : 0;

  return `
  <div class="phead">
    <div><h1>Operator Dashboard</h1>
      <p class="sub">Real-time monitoring of victim distress and case management</p></div>
    <div style="display:flex;align-items:center;gap:10px">
      <div class="clock" id="clock"></div>
      <a class="btn btn-primary btn-sm" href="#/upload">${icon('upload', 15)} Upload Call</a>
    </div>
  </div>

  <div class="grid g4" style="margin-top:14px">
    ${cards.map(([ic, bg, fg, lbl, val, note]) => `
      <div class="card"><div class="stat">
        <span class="ico" style="background:var(${bg});color:var(${fg})">${icon(ic)}</span>
        <div><p class="lbl">${lbl}</p><p class="val">${esc(val)}</p></div>
      </div><p class="note">${esc(note)}</p></div>`).join('')}
  </div>

  <div class="grid g2" style="margin-top:14px">
    <div class="card">
      ${c ? `
        <div style="display:flex;align-items:center;gap:7px">
          <p class="ct">Stress Vulnerability Index</p>
          <span title="0.5x distress + 0.5x danger + indicator bonus, with a deterministic safety floor"
            style="color:var(--muted);display:inline-flex;cursor:help">${icon('info', 14)}</span>
          <span style="margin-left:auto;color:var(--faint);font-size:12px">${esc(c.case_id)}</span>
        </div>
        ${gauge(c.svi_score, c.svi_category)}
        <div style="text-align:center;margin-top:-4px">${riskPill(c.svi_category)}</div>
        <div class="axes">
          <div class="axis"><p class="k">DISTRESS</p>
            <p class="v" style="color:var(--${{ Low: 'low', Moderate: 'mod', High: 'high', Critical: 'crit' }[bandOf(c.distress_score)]})">
              ${bandOf(c.distress_score)}</p><p class="n">${c.distress_score}/100</p></div>
          <div class="axis"><p class="k">DANGER</p>
            <p class="v" style="color:var(--${{ Low: 'low', Moderate: 'mod', High: 'high', Critical: 'crit' }[bandOf(c.danger_score)]})">
              ${bandOf(c.danger_score)}</p><p class="n">${c.danger_score}/100</p></div>
          <div class="axis" ${c.safety_floor_triggered ? 'style="background:var(--crit-bg)"' : ''}>
            <p class="k">SAFETY FLOOR</p>
            <p class="v" style="color:var(${c.safety_floor_triggered ? '--crit' : '--text-2'})">
              ${c.safety_floor_triggered ? 'Triggered' : 'Not triggered'}</p>
            <p class="n">${c.safety_floor_triggered ? `${(c.safety_matches || []).length} rule(s) fired`
              : 'no rule matched'}</p></div>
        </div>
        <div class="strip">${icon('spark')}<div>
          <b>0.5&times;${c.distress_score} + 0.5&times;${c.danger_score} +
          ${c.indicator_bonus} indicator bonus${c.safety_floor_applied
            ? ', raised to the 80 safety floor' : ''} = ${c.svi_score}</b><br/>
          ${(c.evidence_spans || []).length} evidence span(s) recorded behind this score.
        </div></div>`
      : `<p class="ct">Stress Vulnerability Index</p>
         <p class="empty">No case selected yet.<br/>
           <a class="btn btn-primary btn-sm" href="#/upload" style="margin-top:12px">
             ${icon('upload', 15)} Upload your first call</a></p>`}
    </div>

    <div class="card">
      <p class="ct">Risk Level Distribution</p>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;align-items:center;margin-top:8px">
        <div>${donut(d.counts || {}, d.total || 0)}</div>
        <ul class="legend">${ORDER.map((k) => {
          const n = (d.counts || {})[k] || 0;
          const p = d.total ? Math.round((n / d.total) * 100) : 0;
          return `<li><span class="dot" style="background:var(--${{ Low: 'low', Moderate: 'mod', High: 'high', Critical: 'crit' }[k]})"></span>
            <span class="nm">${k}</span><span class="ct2">${n}</span>
            <span class="pc">(${p}%)</span></li>`;
        }).join('')}</ul>
      </div>
      <div class="strip">${icon('chart')}<div>
        <b>${hc}% of cases are High or Critical</b><br/>
        Computed from ${d.total || 0} stored case${d.total === 1 ? '' : 's'}.</div></div>
    </div>
  </div>

  ${c ? `
  <div class="grid g2" style="margin-top:14px">
    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;gap:10px">
        <p class="ct">Case Details</p>
        <a class="btn btn-ghost btn-sm" href="#/reports">Open in Reports ${icon('arrow', 14)}</a>
      </div>
      <dl>
        <div class="row"><dt>Case ID</dt><dd><b>${esc(c.case_id)}</b></dd></div>
        <div class="row"><dt>Channel</dt><dd>NHAA 14566 (${esc(c.channel)})</dd></div>
        <div class="row"><dt>Language</dt><dd>${esc(c.language)}</dd></div>
        <div class="row"><dt>Received</dt><dd>${fmtStamp(c.uploaded_at)}
          <span style="color:var(--faint)">&middot; ${ago(c.uploaded_at)}</span></dd></div>
        <div class="row"><dt>SVI</dt><dd><b>${c.svi_score} / 100</b> &nbsp;${riskPill(c.svi_category)}</dd></div>
        <div class="row"><dt>Status</dt><dd>${statusPill(c.status)}</dd></div>
        <div class="row"><dt>Indicators</dt><dd class="tags">${
          Object.entries(c.indicators || {}).filter(([, v]) => v)
            .map(([k]) => `<span class="tag">${esc(label(k))}</span>`).join('')
          || '<span style="color:var(--faint);font-size:12.5px">None flagged</span>'}</dd></div>
        <div class="row"><dt>Summary</dt><dd>${esc(c.summary)}</dd></div>
        ${c.engine_note ? `<div class="row"><dt></dt>
          <dd style="font-size:11.5px;color:var(--crit)">AI analysis was unavailable for this
          case, so the offline analyser scored it.</dd></div>` : ''}
      </dl>
    </div>

    <div class="card">
      <div style="display:flex;gap:7px;align-items:center">${icon('spark')}
        <p class="ct">AI-Assisted Recommendations</p></div>
      ${recoList(c)}
      ${c.status === 'Pending'
        ? `<button class="btn btn-primary btn-block" id="mark" style="margin-top:14px">
             ${icon('check', 16)} Mark as under review</button>`
        : `<button class="btn btn-outline btn-block" style="margin-top:14px" disabled>
             Status: ${esc(c.status)}</button>`}
      <p class="hint" style="text-align:center;margin-top:10px">
        A counsellor decides every case. The model orders the queue, it does not close it.</p>
    </div>
  </div>

  <div class="card" style="margin-top:14px">
    <p class="ct">Why this case scored ${c.svi_score}</p>
    <p class="csub">The reasons below come from the analysis of this call, not from a template.</p>
    ${whyBlock(c)}
  </div>` : ''}

  <div class="card card-flush" style="margin-top:14px">
    <div style="display:flex;justify-content:space-between;align-items:center;padding:14px 16px">
      <p class="ct">Recent Cases</p>
      <span style="color:var(--faint);font-size:12.5px">${S.cases.length} total</span>
    </div>
    <div style="overflow-x:auto"><table>
      <thead><tr><th>Case ID</th><th>Channel</th><th>SVI</th><th>Risk</th>
        <th>Date</th><th>Time</th><th>Status</th></tr></thead>
      <tbody id="rows">${S.cases.length ? S.cases.slice(0, 12).map((r) => `
        <tr class="clickable ${S.selected && S.selected.id === r.id ? 'sel' : ''}" data-id="${r.id}">
          <td><b>${esc(r.case_id)}</b></td>
          <td style="color:var(--text-2)">${esc(r.channel)}</td>
          <td><b>${r.svi_score}</b></td><td>${riskPill(r.svi_category)}</td>
          <td style="color:var(--muted)">${fmtDate(r.uploaded_at)}</td>
          <td style="color:var(--muted)">${fmtTime(r.uploaded_at)}</td>
          <td>${statusPill(r.status)}</td></tr>`).join('')
        : '<tr><td colspan="7" class="empty">No cases yet.</td></tr>'}</tbody>
    </table></div>
  </div>`;
}

function wireDashboard() {
  tick();
  document.querySelectorAll('#rows tr[data-id]').forEach((tr) => {
    tr.onclick = () => { select(Number(tr.dataset.id)); render(); };
  });
  const m = $('mark');
  if (m) m.onclick = async () => {
    m.disabled = true;
    try {
      await apiJson(`/cases/${S.selected.id}/status`, 'PATCH', { status: 'In Progress' });
      toast('Case marked as under review.');
      await refresh(S.selected.id);
    } catch (ex) { toast(ex.message, 'bad'); m.disabled = false; }
  };
}


/* ===================================================================== */
/*  PAGE: Live Call                                                      */
/* ===================================================================== */
/* A call happening right now. The browser records the microphone in short
   slices and posts each one; the reply carries the new transcript line and the
   re-scored SVI, so the cards move while the caller is still talking.

   This is a microphone demo of a live call. In a real deployment the audio
   would arrive from the telephony layer in front of NHAA 14566 - an IVR, or a
   provider like Exotel or Twilio Media Streams - feeding the same endpoints. */

const LIVE = {
  cfg: null,          // what live transcription can do here
  session: null,      // the running call's state, straight from the server
  recorder: null,
  stream: null,
  sessionId: null,
  starting: false,
  ending: false,
  error: '',
  timer: null,
  seconds: 0,
  seenSegments: 0,
  lastSvi: null,
  inflight: 0,
  // Streaming is switched off in this build - see STREAMING_ENABLED below.
  useStreaming: false,
  ws: null,
};

const CHUNK_MS = 4000;   // how much speech goes in each slice

/* Deepgram streaming is switched OFF in this build.
   The code below it is kept so it can be finished and tested later, but nothing
   calls it while this is false: no socket is opened, no request is made, and
   there is no path by which a Deepgram failure could reach the screen. The
   clip-based pipeline - the one that has been tested end to end - carries every
   call. Set this to true, and NAVHRIDYA_ENABLE_STREAMING=true on the server, to
   pick the work back up. */
const STREAMING_ENABLED = false;

function fmtClock(total) {
  const m = Math.floor(total / 60), sec = Math.floor(total % 60);
  return `${String(m).padStart(2, '0')}:${String(sec).padStart(2, '0')}`;
}

/** The SVI over the course of the call, as a small line. */
function sparkline(snaps) {
  if (!snaps || snaps.length < 2) return '';
  const R = risk();
  const w = 320, h = 54, pad = 3;
  const maxT = Math.max(...snaps.map((s) => s.at || s.at_seconds || 0), 1);
  const pt = (s, i) => {
    const t = s.at != null ? s.at : (s.at_seconds || 0);
    const x = pad + (t / maxT) * (w - pad * 2);
    const y = h - pad - (Math.max(0, Math.min(100, s.svi_score)) / 100) * (h - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  };
  const pts = snaps.map(pt).join(' ');
  const last = snaps[snaps.length - 1];
  const [lx, ly] = pt(last).split(',');
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none"
      role="img" aria-label="SVI over the call">
    <line x1="${pad}" y1="${h - pad - 0.8 * (h - pad * 2)}" x2="${w - pad}"
      y2="${h - pad - 0.8 * (h - pad * 2)}" stroke="${R.Critical}" stroke-width="1"
      stroke-dasharray="3 3" opacity=".45"/>
    <polyline points="${pts}" fill="none" stroke="${R[last.svi_category] || R.Low}"
      stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
    <circle cx="${lx}" cy="${ly}" r="3.5" fill="${R[last.svi_category] || R.Low}"/>
  </svg>
  <p class="hint" style="margin:2px 0 0">SVI across the call. The dashed line is the
    Critical floor at 80.</p>`;
}

function liveScoreCard(st) {
  if (!st) return '';
  const band = (v) => ({ Low: 'low', Moderate: 'mod', High: 'high', Critical: 'crit' }[bandOf(v)]);
  return `
    ${gauge(st.svi_score, st.svi_category)}
    <div style="text-align:center;margin-top:-4px">${riskPill(st.svi_category)}</div>
    <div class="axes">
      <div class="axis"><p class="k">DISTRESS</p>
        <p class="v" style="color:var(--${band(st.distress_score)})">${st.distress_score}</p>
        <p class="n">${bandOf(st.distress_score)}</p></div>
      <div class="axis"><p class="k">DANGER</p>
        <p class="v" style="color:var(--${band(st.danger_score)})">${st.danger_score}</p>
        <p class="n">${bandOf(st.danger_score)}</p></div>
      <div class="axis" ${st.safety_floor_triggered ? 'style="background:var(--crit-bg)"' : ''}>
        <p class="k">SAFETY FLOOR</p>
        <p class="v" style="color:var(${st.safety_floor_triggered ? '--crit' : '--text-2'})">
          ${st.safety_floor_triggered ? 'Fired' : 'Clear'}</p>
        <p class="n">${(st.safety_rules_fired || []).length} rule(s)</p></div>
    </div>
    ${(st.safety_matches || []).length ? `
      <div class="whyhead">${icon('shield', 14)} Fired outside the model, on the words spoken</div>
      <ul class="why">${st.safety_matches.slice(-4).map((m) =>
        `<li><span class="bullet" style="background:var(--crit)"></span>
          <span><b style="color:var(--crit)">${esc(m.label)}</b> -
          &ldquo;${esc(m.matched_text)}&rdquo;</span></li>`).join('')}</ul>` : ''}
    ${st.analysed_once ? `
      <div class="whyhead">${icon('info', 14)} Why it reads this way, so far</div>
      ${reasonList((st.distress_reasons || []).slice(0, 3), '--mod')}
      ${reasonList((st.danger_reasons || []).slice(0, 3), '--crit')}
      ${st.summary ? `<div class="strip">${icon('text')}<div><b>Summary so far</b><br/>
        ${esc(st.summary)}</div></div>` : ''}`
      : `<p class="hint" style="margin-top:12px">The model reads the call every few seconds.
         The safety rules run on every word as it arrives.</p>`}
    ${sparkline(st.snapshots)}`;
}

function pageLive() {
  const cfg = LIVE.cfg;
  const st = LIVE.session;
  const running = !!LIVE.sessionId && !LIVE.ending;

  if (cfg && !cfg.available) {
    return `
    <div class="phead">
      <div><h1>Live Call</h1>
        <p class="sub">Score a call while it is still happening.</p></div>
    </div>
    <div class="card" style="margin-top:14px">
      <p class="ct">Live transcription is not configured</p>
      <p class="csub" style="margin-top:8px">${esc(cfg.note)}</p>
      <p class="hint" style="margin-top:14px">Upload Call still works - it needs the same
        key, or you can paste a transcript, which needs none.</p>
      <a class="btn btn-outline btn-sm" href="#/upload" style="margin-top:12px">
        ${icon('upload', 15)} Go to Upload Call</a>
    </div>`;
  }

  return `
  <div class="phead">
    <div><h1>Live Call</h1>
      <p class="sub">The call is scored while it is still happening. Nothing is saved until
        you end it.</p></div>
    ${running ? `<div style="text-align:right">
        <div class="rec"><span class="dot"></span> RECORDING</div>
        <div class="calltimer" id="ctimer">${fmtClock(LIVE.seconds)}</div>
      </div>` : ''}
  </div>

  ${!running ? `
    <div class="card" style="margin-top:14px;text-align:center;padding:40px 22px">
      <div style="width:56px;height:56px;border-radius:16px;background:var(--crit-bg);
        color:var(--crit);display:grid;place-items:center;margin:0 auto 16px">
        ${icon('mic', 26)}</div>
      <h2 style="font-size:20px">Start a live call</h2>
      <p style="color:var(--muted);margin:9px auto 0;max-width:36em;font-size:14.5px">
        Your microphone becomes the call audio. Speak as the caller would, and watch the
        distress, danger and SVI move while you are still talking. The case is only saved
        when you end the call.</p>
      <p class="err" id="lerr">${esc(LIVE.error)}</p>
      <button class="btn btn-danger" id="startLive" ${LIVE.starting ? 'disabled' : ''}
        style="margin-top:6px">
        ${LIVE.starting ? '<span class="spin"></span> Starting...' : icon('mic', 16) + ' Start Live Call'}
      </button>
      <div class="strip" style="max-width:640px;margin:26px auto 0;text-align:left">
        ${icon('info')}<div><b>How it listens</b><br/>
          The call is transcribed in short slices, so a line appears a couple of seconds
          after it is spoken. The safety rules run on every line the moment it arrives.</div></div>
      <p class="hint" style="max-width:640px;margin:12px auto 0;text-align:left">
        A microphone demo of a live call. A real deployment would sit behind the NHAA
        telephony layer, which would feed call audio into exactly this pipeline.
        Your browser will ask for microphone permission, and it only works over
        https or on localhost.</p>
    </div>`
  : `
    <div class="livewrap">
      <div class="card">
        <div class="livebar">
          <p class="ct">Live transcript</p>
          <button class="btn btn-danger btn-sm" id="endLive" style="margin-left:auto"
            ${LIVE.ending ? 'disabled' : ''}>
            ${LIVE.ending ? '<span class="spin"></span> Generating final report...'
                          : icon('check', 15) + ' End Call'}</button>
        </div>
        <div class="tscript" id="tscript">
          ${(st && st.segments && st.segments.length)
            ? st.segments.map((seg) => `
              <div class="tline"><span class="t">${fmtClock(seg.at)}</span>
                <span class="x">${esc(seg.text)}${seg.translated
                  ? `<span class="tag">translated from ${esc(seg.language)}</span>` : ''}</span>
              </div>`).join('')
            : `<div class="waiting">Listening... speak into the microphone and the first
                line appears in a few seconds.</div>`}
        </div>
        <p class="err" id="lerr">${esc(LIVE.error)}</p>
        <p class="hint">Hindi appears in Hindi. Any other language is shown in English.
          Each slice is about ${CHUNK_MS / 1000} seconds of speech.</p>
      </div>

      <div class="card" id="liveScore">
        <div style="display:flex;align-items:center;gap:7px">
          <p class="ct">Live SVI</p>
          <span style="margin-left:auto;color:var(--faint);font-size:12px">updating live</span>
        </div>
        ${liveScoreCard(st)}
      </div>
    </div>`}`;
}

/* ===================================================================== */
/*  PAGE: Upload Call                                                    */
/* ===================================================================== */
let UP = { mode: 'audio', file: null, result: null, busy: false,
           text: '', consent: false, channel: 'Call', language: 'Hindi' };

function pageUpload() {
  const aiMode = (S.me && S.me.ai_mode) || '';
  const audioReady = !/offline demo/i.test(aiMode);
  const r = UP.result;

  return `
  <div class="phead">
    <div><h1>Upload Call</h1>
      <p class="sub">Transcribe the recording, run the safety rules, and score the caller's
        Stress Vulnerability Index with its reasons.</p></div>
    <a class="btn btn-ghost btn-sm" href="#/dashboard">${icon('grid', 15)} Back to dashboard</a>
  </div>

  <div class="grid g2" style="margin-top:14px;align-items:start">
    <div class="card">
      <p class="ct">1. The recording</p>
      <p class="csub">A recorded call, or the transcript if the call came in over chat or the portal.</p>

      <div class="seg" style="margin-top:14px">
        <button type="button" id="mAudio" class="${UP.mode === 'audio' ? 'on' : ''}">
          ${icon('mic', 15)} Audio recording</button>
        <button type="button" id="mText" class="${UP.mode === 'text' ? 'on' : ''}">
          ${icon('text', 15)} Paste transcript</button>
      </div>

      <div id="paneAudio" style="display:${UP.mode === 'audio' ? '' : 'none'}">
        <label class="drop" id="drop">
          <input type="file" id="af" accept=".mp3,.wav,.m4a,.ogg,.webm,.mp4,.mpeg,.mpga" />
          ${icon('upload', 26)}
          <b id="fname">${UP.file ? esc(UP.file.name) : 'Choose a recorded call'}</b>
          <small id="fmeta">${UP.file ? fmtBytes(UP.file.size)
            : 'mp3, wav, m4a, ogg, webm or mp4 &middot; click to browse or drop a file here'}</small>
        </label>
        ${audioReady
          ? `<p class="hint">The recording is transcribed first, then the SVI is computed
             from that transcript.</p>`
          : `<p class="hint" style="color:var(--crit)">No speech-to-text is configured, so audio
             cannot be transcribed right now. Set GROQ_API_KEY or OPENAI_API_KEY in .env, or use
             USE_LOCAL_WHISPER=true, and restart. Paste-transcript mode works either way.</p>`}
      </div>

      <div id="paneText" style="display:${UP.mode === 'text' ? '' : 'none'}">
        ${S.samples.length ? `<label class="fld">Load a sample call
          <select id="sample"><option value="">- choose a sample -</option>
            ${S.samples.map((s, i) => `<option value="${i}">${esc(s.name)}</option>`).join('')}
          </select></label>` : ''}
        <label class="fld">Call transcript
          <textarea id="tx" rows="7"
            placeholder="Paste what the caller said...">${esc(UP.text)}</textarea></label>
      </div>

      <p class="ct" style="margin-top:22px">2. Call metadata</p>
      <div class="kv" style="margin-top:4px">
        <label class="fld" style="margin-top:6px">Channel
          <select id="ch">${['Call', 'Chat', 'Portal'].map((o) =>
            `<option ${o === UP.channel ? 'selected' : ''}>${o}</option>`).join('')}</select></label>
        <label class="fld" style="margin-top:6px">Language
          <select id="lg">${['Hindi', 'English', 'Hindi + English (code-mixed)', 'Marathi',
            'Bengali', 'Tamil', 'Telugu', 'Kannada', 'Gujarati', 'Odia', 'Punjabi'].map((o) =>
            `<option ${o === UP.language ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select></label>
      </div>

      <p class="ct" style="margin-top:22px">3. Consent</p>
      <label class="consent"><input type="checkbox" id="cs" ${UP.consent ? 'checked' : ''} />
        <span>The caller was told what this recording is used for and gave explicit consent.
          Without consent, NHAA continues exactly as it does today and nothing is analysed here.</span>
      </label>

      <p class="err" id="uerr"></p>
      <button class="btn btn-primary btn-block" id="go" ${UP.consent ? '' : 'disabled'}
        style="margin-top:6px">
        ${icon('spark', 16)} Run assessment</button>
      <p class="hint" id="wait" style="display:none;text-align:center">
        Transcription and analysis usually take 5 to 15 seconds. Leaving this page will not
        cancel it, but the result appears here.</p>
    </div>

    <div class="card" id="resultCard">
      ${r ? `
        <div style="display:flex;align-items:center;gap:8px">
          <p class="ct">Assessment complete</p>
          <span style="margin-left:auto;color:var(--faint);font-size:12px">${esc(r.case_id)}</span>
        </div>
        ${gauge(r.svi_score, r.svi_category)}
        <div style="text-align:center;margin-top:-4px">${riskPill(r.svi_category)}</div>
        <div class="axes">
          <div class="axis"><p class="k">DISTRESS</p><p class="v">${r.distress_score}</p>
            <p class="n">${bandOf(r.distress_score)}</p></div>
          <div class="axis"><p class="k">DANGER</p><p class="v">${r.danger_score}</p>
            <p class="n">${bandOf(r.danger_score)}</p></div>
          <div class="axis" ${r.safety_floor_triggered ? 'style="background:var(--crit-bg)"' : ''}>
            <p class="k">SAFETY FLOOR</p>
            <p class="v" style="color:var(${r.safety_floor_triggered ? '--crit' : '--text-2'})">
              ${r.safety_floor_triggered ? 'Fired' : 'Clear'}</p>
            <p class="n">${(r.safety_matches || []).length} rule(s)</p></div>
        </div>
        <div class="strip">${icon('info')}<div><b>Summary</b><br/>${esc(r.summary)}</div></div>
        ${whyBlock(r)}
        <div class="whyhead">${icon('spark', 14)} Recommended actions</div>
        ${recoList(r)}
        <div class="actions" style="justify-content:stretch">
          <a class="btn btn-primary" style="flex:1" href="#/dashboard" id="seeDash">
            Open on the dashboard ${icon('arrow', 15)}</a>
          <button class="btn btn-outline" id="again">Score another call</button>
        </div>
        <p class="hint">Saved - this case will still be here after a refresh.</p>`
      : `<p class="ct">What you will get back</p>
         <p class="csub">The result appears here as soon as the pipeline finishes.</p>
         <ul class="why" style="margin-top:14px">
           <li><span class="bullet" style="background:var(--accent)"></span>
             <span>A <b>Stress Vulnerability Index</b> from 0 to 100, with its risk band.</span></li>
           <li><span class="bullet" style="background:var(--accent)"></span>
             <span><b>Distress and danger scored separately</b>, each with the cues that raised it.</span></li>
           <li><span class="bullet" style="background:var(--accent)"></span>
             <span>The <b>arithmetic written out</b>, step by step, so the number can be checked.</span></li>
           <li><span class="bullet" style="background:var(--accent)"></span>
             <span>Any <b>safety rule</b> that fired outside the model, with the matched words.</span></li>
           <li><span class="bullet" style="background:var(--accent)"></span>
             <span>Up to four <b>recommended actions</b> from the fixed helpline list.</span></li>
         </ul>
         <div class="strip">${icon('mic')}<div><b>A call can also be scored live.</b><br/>
           This page scores a completed recording. <a href="#/live"
           style="color:var(--accent);font-weight:600">Live Call</a> does the same thing
           while the caller is still speaking, through the same pipeline.</div></div>`}
    </div>
  </div>`;
}

function wireUpload() {
  const setMode = (m) => { UP.mode = m; render(); };
  $('mAudio').onclick = () => setMode('audio');
  $('mText').onclick = () => setMode('text');

  const drop = $('drop'), af = $('af');
  if (af) {
    af.onchange = () => {
      UP.file = af.files[0] || null;
      $('fname').textContent = UP.file ? UP.file.name : 'Choose a recorded call';
      $('fmeta').textContent = UP.file ? fmtBytes(UP.file.size)
        : 'mp3, wav, m4a, ogg, webm or mp4 - click to browse or drop a file here';
    };
    ['dragenter', 'dragover'].forEach((ev) => drop.addEventListener(ev, (e) => {
      e.preventDefault(); drop.classList.add('hot'); }));
    ['dragleave', 'drop'].forEach((ev) => drop.addEventListener(ev, (e) => {
      e.preventDefault(); drop.classList.remove('hot'); }));
    drop.addEventListener('drop', (e) => {
      const f = e.dataTransfer && e.dataTransfer.files[0];
      if (f) { af.files = e.dataTransfer.files; af.onchange(); }
    });
  }

  const sel = $('sample');
  if (sel) sel.onchange = () => {
    if (sel.value !== '') { UP.text = S.samples[+sel.value].text; $('tx').value = UP.text; }
  };

  $('cs').onchange = () => {
    UP.consent = $('cs').checked;
    $('go').disabled = !UP.consent || UP.busy;
  };
  $('ch').onchange = () => { UP.channel = $('ch').value; };
  $('lg').onchange = () => { UP.language = $('lg').value; };
  const tx = $('tx');
  if (tx) tx.oninput = () => { UP.text = tx.value; };

  const again = $('again');
  if (again) again.onclick = () => {
    UP = { mode: UP.mode, file: null, result: null, busy: false, text: '',
           consent: false, channel: UP.channel, language: UP.language };
    render();
  };

  $('go').onclick = async () => {
    $('uerr').textContent = '';
    const fd = new FormData();
    fd.append('channel', $('ch').value);
    fd.append('language', $('lg').value);
    if (UP.mode === 'text') {
      const t = (UP.text || $('tx').value).trim();
      if (!t) { $('uerr').textContent = 'Paste a transcript first, or switch to audio.'; return; }
      fd.append('transcript_text', t);
    } else {
      if (!UP.file) { $('uerr').textContent = 'Choose an audio file first.'; return; }
      fd.append('audio_file', UP.file);
    }
    UP.busy = true;
    $('go').disabled = true;
    $('go').innerHTML = '<span class="spin"></span> Analysing the call...';
    $('wait').style.display = '';
    try {
      const c = await api('/cases/upload', { method: 'POST', body: fd });
      UP.result = c; UP.busy = false; UP.file = null;
      select(c.id);
      await refresh(c.id);
      toast(`${c.case_id} scored ${c.svi_score} - ${c.svi_category}`);
    } catch (ex) {
      UP.busy = false;
      $('uerr').textContent = ex.message;
      $('go').disabled = false;
      $('go').innerHTML = icon('spark', 16) + ' Run assessment';
      $('wait').style.display = 'none';
    }
  };
}


/* ------------------------------------------------------- live call wiring */
/** Repaint only the two live panels, so the transcript does not lose its
 *  scroll position and the whole page does not flash on every update. */
function paintLive() {
  const st = LIVE.session;
  const t = $('ctimer');
  if (t) t.textContent = fmtClock(LIVE.seconds);

  const box = $('tscript');
  if (box && st) {
    const segs = st.segments || [];
    if (segs.length !== LIVE.seenSegments) {
      const stuck = box.scrollTop + box.clientHeight >= box.scrollHeight - 40;
      box.innerHTML = segs.length
        ? segs.map((seg, i) => `
          <div class="tline ${i >= LIVE.seenSegments ? 'fresh' : ''}">
            <span class="t">${fmtClock(seg.at)}</span>
            <span class="x">${esc(seg.text)}${seg.translated
              ? `<span class="tag">translated from ${esc(seg.language)}</span>` : ''}</span>
          </div>`).join('')
        : `<div class="waiting">Listening... speak into the microphone and the first line
            appears in a few seconds.</div>`;
      LIVE.seenSegments = segs.length;
      if (stuck) box.scrollTop = box.scrollHeight;
    }
  }

  const panel = $('liveScore');
  if (panel && st) {
    panel.innerHTML = `
      <div style="display:flex;align-items:center;gap:7px">
        <p class="ct">Live SVI</p>
        <span style="margin-left:auto;color:var(--faint);font-size:12px">${
          LIVE.inflight ? 'analysing...' : 'updating live'}</span>
      </div>${liveScoreCard(st)}`;
    // a score that moved deserves to be noticed
    if (LIVE.lastSvi !== null && st.svi_score !== LIVE.lastSvi) {
      const g = panel.querySelector('svg');
      if (g) { g.classList.remove('bump'); void g.offsetWidth; g.classList.add('bump'); }
      if (st.svi_score > LIVE.lastSvi + 8) {
        toast(`SVI rose to ${st.svi_score} - ${st.svi_category}`,
              st.svi_category === 'Critical' ? 'bad' : undefined);
      }
    }
    LIVE.lastSvi = st.svi_score;
  }

  const err = $('lerr');
  if (err) err.textContent = LIVE.error;
}

/** Pick a container the browser can actually record, and the provider can read. */
function pickMime() {
  const wanted = ['audio/webm;codecs=opus', 'audio/webm', 'audio/ogg;codecs=opus', 'audio/mp4'];
  for (const m of wanted) {
    if (window.MediaRecorder && MediaRecorder.isTypeSupported(m)) return m;
  }
  return '';
}

async function startLiveCall() {
  LIVE.error = '';
  LIVE.starting = true;
  render();

  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, channelCount: 1 },
    });
  } catch (ex) {
    LIVE.starting = false;
    LIVE.error = 'The microphone was refused or is unavailable. Allow microphone access '
               + 'for this site and try again. (Browsers only allow it over https or on localhost.)';
    render();
    return;
  }

  try {
    const started = await apiJson('/live/start', 'POST', { language: 'Hindi' });
    LIVE.sessionId = started.session_id;
    LIVE.session = started;
  } catch (ex) {
    stream.getTracks().forEach((t) => t.stop());
    LIVE.starting = false;
    LIVE.error = ex.message;
    render();
    return;
  }

  LIVE.stream = stream;
  LIVE.seconds = 0;
  LIVE.seenSegments = 0;
  LIVE.lastSvi = null;
  LIVE.starting = false;

  const mime = pickMime();
  /* Each slice has to stand on its own as a playable file, because the server
     transcribes it by itself. A MediaRecorder that is left running emits later
     chunks without a header, so instead it is restarted for every slice. */
  const sliceOnce = () => {
    if (!LIVE.sessionId || LIVE.ending || !LIVE.stream) return;
    let rec;
    try {
      rec = new MediaRecorder(LIVE.stream, mime ? { mimeType: mime } : undefined);
    } catch (ex) {
      LIVE.error = 'This browser cannot record audio (MediaRecorder is unavailable).';
      paintLive();
      return;
    }
    const parts = [];
    rec.ondataavailable = (e) => { if (e.data && e.data.size) parts.push(e.data); };
    rec.onstop = async () => {
      const blob = new Blob(parts, { type: mime || 'audio/webm' });
      if (LIVE.sessionId && !LIVE.ending && blob.size > 1200) await sendChunk(blob);
      if (LIVE.sessionId && !LIVE.ending) sliceOnce();
    };
    rec.start();
    LIVE.recorder = rec;
    setTimeout(() => { if (rec.state === 'recording') rec.stop(); }, CHUNK_MS);
  };

  LIVE.timer = setInterval(() => { LIVE.seconds += 1; paintLive(); }, 1000);
  render();

  if (STREAMING_ENABLED && LIVE.useStreaming && LIVE.cfg && LIVE.cfg.streaming_possible) {
    let ok = false;
    try { ok = await startStreaming(LIVE.stream); } catch (ex) { ok = false; }
    if (ok) return;                       // streaming carries the call from here
    stopStreaming();                      // and otherwise, fall through quietly
  }
  sliceOnce();
}

async function sendChunk(blob) {
  const fd = new FormData();
  const ext = (blob.type || '').includes('mp4') ? 'mp4'
            : (blob.type || '').includes('ogg') ? 'ogg' : 'webm';
  fd.append('audio', blob, `slice.${ext}`);
  LIVE.inflight += 1;
  paintLive();
  try {
    const st = await api(`/live/${LIVE.sessionId}/chunk`, { method: 'POST', body: fd });
    if (LIVE.sessionId) { LIVE.session = st; LIVE.error = ''; }
  } catch (ex) {
    // one failed slice should not end the call - say so and keep listening
    LIVE.error = ex.message;
  } finally {
    LIVE.inflight = Math.max(0, LIVE.inflight - 1);
    paintLive();
  }
}


/* ------------------------------------------------- Deepgram streaming path */
/* Raw PCM16 at 16 kHz straight down a WebSocket, which is what Deepgram reads
   without transcoding. Opt-in, and it gives up quickly: if the socket does not
   produce anything within a few seconds, the tested clip path takes over so a
   call is never left silently dead.

   UNTESTED against the real Deepgram service - see backend/ai/deepgram_stream.py. */

const PCM_WORKLET = `
class PcmTap extends AudioWorkletProcessor {
  process (inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (ch) {
      const out = new Int16Array(ch.length);
      for (let i = 0; i < ch.length; i++) {
        const v = Math.max(-1, Math.min(1, ch[i]));
        out[i] = v < 0 ? v * 0x8000 : v * 0x7fff;
      }
      this.port.postMessage(out.buffer, [out.buffer]);
    }
    return true;
  }
}
registerProcessor('pcm-tap', PcmTap);`;

async function startStreaming(stream) {
  const ctx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
  const blobUrl = URL.createObjectURL(new Blob([PCM_WORKLET], { type: 'text/javascript' }));
  await ctx.audioWorklet.addModule(blobUrl);
  URL.revokeObjectURL(blobUrl);

  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(
    `${proto}://${location.host}/ws/live/${LIVE.sessionId}?token=${encodeURIComponent(TOKEN)}`);
  ws.binaryType = 'arraybuffer';
  LIVE.ws = ws;

  const src = ctx.createMediaStreamSource(stream);
  const tap = new AudioWorkletNode(ctx, 'pcm-tap');
  let buffered = [];
  tap.port.onmessage = (e) => {
    if (ws.readyState !== WebSocket.OPEN) return;
    buffered.push(new Uint8Array(e.data));
    // ~250ms of 16 kHz PCM16 before each send, so the socket is not flooded
    const total = buffered.reduce((n, b) => n + b.length, 0);
    if (total >= 8000) {
      const joined = new Uint8Array(total);
      let at = 0;
      buffered.forEach((b) => { joined.set(b, at); at += b.length; });
      buffered = [];
      ws.send(joined.buffer);
    }
  };
  src.connect(tap);

  ws.onmessage = (e) => {
    let msg;
    try { msg = JSON.parse(e.data); } catch (err) { return; }
    if (msg.type === 'state' && msg.state) { LIVE.session = msg.state; paintLive(); }
    else if (msg.type === 'error') {
      LIVE.error = msg.detail || 'Streaming failed.';
      paintLive();
    }
  };

  const teardown = () => {
    try { tap.disconnect(); src.disconnect(); ctx.close(); } catch (err) { /* closing */ }
  };
  ws.onclose = teardown;
  ws.onerror = teardown;

  // if nothing has come back by now, the socket is not going to work
  return new Promise((resolve) => {
    const settle = (ok) => resolve(ok);
    ws.onopen = () => setTimeout(() => settle(ws.readyState === WebSocket.OPEN && !LIVE.error), 4000);
    setTimeout(() => { if (ws.readyState !== WebSocket.OPEN) settle(false); }, 5000);
  });
}

function stopStreaming() {
  if (LIVE.ws) {
    try { LIVE.ws.close(); } catch (e) { /* already gone */ }
    LIVE.ws = null;
  }
}

function stopRecording() {
  if (LIVE.timer) { clearInterval(LIVE.timer); LIVE.timer = null; }
  stopStreaming();
  try { if (LIVE.recorder && LIVE.recorder.state === 'recording') LIVE.recorder.stop(); }
  catch (e) { /* already stopped */ }
  if (LIVE.stream) { LIVE.stream.getTracks().forEach((t) => t.stop()); LIVE.stream = null; }
  LIVE.recorder = null;
}

async function endLiveCall() {
  if (!LIVE.sessionId || LIVE.ending) return;
  LIVE.ending = true;
  LIVE.error = '';
  render();
  stopRecording();

  const sid = LIVE.sessionId;
  try {
    const cse = await apiJson(`/live/${sid}/end`, 'POST', {});
    LIVE.sessionId = null; LIVE.session = null; LIVE.ending = false;
    select(cse.id);
    await refresh(cse.id);
    toast(`${cse.case_id} saved - SVI ${cse.svi_score}, ${cse.svi_category}`);
    location.hash = '#/dashboard';
  } catch (ex) {
    LIVE.ending = false;
    LIVE.sessionId = null;
    LIVE.error = ex.message;
    render();
  }
}

function wireLive() {
  if (!LIVE.cfg) {
    api('/live/config').then((cfg) => { LIVE.cfg = cfg; if (route() === 'live') render(); })
      .catch(() => {});
  }
  const start = $('startLive');
  if (start) start.onclick = startLiveCall;
  const end = $('endLive');
  if (end) end.onclick = endLiveCall;
  if (LIVE.sessionId) paintLive();
}

/* leaving the page mid-call would orphan the microphone */
window.addEventListener('hashchange', () => {
  if (route() !== 'live' && LIVE.sessionId && !LIVE.ending) {
    stopRecording();
    LIVE.error = '';
    toast('Live call stopped - you left the page before ending it, so nothing was saved.');
    LIVE.sessionId = null;
    LIVE.session = null;
  }
});
window.addEventListener('beforeunload', () => { if (LIVE.sessionId) stopRecording(); });

/* ===================================================================== */
/*  PAGE: Pending Review                                                 */
/* ===================================================================== */
let PEND = { filter: 'all' };

function pagePending() {
  if (!S.cases.length) {
    return `
    <div class="phead">
      <div><h1>Pending Review</h1>
        <p class="sub">Cases waiting for a counsellor, highest SVI first.</p></div>
    </div>
    ${firstRun('The queue is empty',
      'Cases arrive here the moment a call is scored, ordered by SVI and grouped by the day '
      + 'they were received. Nothing is waiting because nothing has been uploaded yet.')}`;
  }

  const open = S.cases.filter((c) => c.status === 'Pending' || c.status === 'In Progress')
    .sort((a, b) => b.svi_score - a.svi_score ||
      new Date(b.uploaded_at) - new Date(a.uploaded_at));
  const shown = PEND.filter === 'all' ? open
    : open.filter((c) => (PEND.filter === 'critical'
      ? c.svi_category === 'Critical' || c.svi_category === 'High'
      : c.status === 'Pending'));

  const oldest = open.reduce((acc, c) =>
    (!acc || new Date(c.uploaded_at) < new Date(acc.uploaded_at) ? c : acc), null);
  const counts = {
    all: open.length,
    critical: open.filter((c) => c.svi_category === 'Critical' || c.svi_category === 'High').length,
    untouched: open.filter((c) => c.status === 'Pending').length,
  };

  /* group by calendar day, so the queue reads as a dated worklist */
  const groups = [];
  shown.forEach((c) => {
    const key = fmtDate(c.uploaded_at);
    let g = groups.find((x) => x.key === key);
    if (!g) { groups.push(g = { key, at: new Date(c.uploaded_at).getTime(), rows: [] }); }
    g.at = Math.max(g.at, new Date(c.uploaded_at).getTime());
    g.rows.push(c);
  });
  groups.sort((a, b) => b.at - a.at);   // newest day first, highest SVI within the day

  return `
  <div class="phead">
    <div><h1>Pending Review</h1>
      <p class="sub">Cases waiting for a counsellor, highest SVI first. Dates are the day the
        call was received.</p></div>
    <a class="btn btn-primary btn-sm" href="#/upload">${icon('upload', 15)} Upload Call</a>
  </div>

  <div class="grid g3" style="margin-top:14px">
    <div class="card"><div class="stat">
      <span class="ico" style="background:var(--mod-bg);color:var(--mod)">${icon('clock')}</span>
      <div><p class="lbl">Awaiting review</p><p class="val">${counts.all}</p></div></div>
      <p class="note">${counts.untouched} not yet opened</p></div>
    <div class="card"><div class="stat">
      <span class="ico" style="background:var(--crit-bg);color:var(--crit)">${icon('alert')}</span>
      <div><p class="lbl">High or Critical in the queue</p><p class="val">${counts.critical}</p></div></div>
      <p class="note">these are the calls to take first</p></div>
    <div class="card"><div class="stat">
      <span class="ico" style="background:var(--surface-3);color:var(--text)">${icon('calendar')}</span>
      <div><p class="lbl">Oldest waiting</p>
        <p class="val" style="font-size:19px">${oldest ? ago(oldest.uploaded_at) : '-'}</p></div></div>
      <p class="note">${oldest ? esc(oldest.case_id) + ' &middot; ' + fmtStamp(oldest.uploaded_at)
        : 'nothing waiting'}</p></div>
  </div>

  <div class="seg" style="margin-top:16px">
    <button type="button" data-f="all" class="${PEND.filter === 'all' ? 'on' : ''}">
      All waiting (${counts.all})</button>
    <button type="button" data-f="critical" class="${PEND.filter === 'critical' ? 'on' : ''}">
      High &amp; Critical (${counts.critical})</button>
    <button type="button" data-f="untouched" class="${PEND.filter === 'untouched' ? 'on' : ''}">
      Not opened yet (${counts.untouched})</button>
  </div>

  ${groups.length ? groups.map((g) => `
    <p style="margin:20px 0 6px;font-size:12px;font-weight:750;letter-spacing:.7px;
      text-transform:uppercase;color:var(--muted)">${icon('calendar', 13)} ${g.key}
      <span style="font-weight:550;letter-spacing:0;text-transform:none;color:var(--faint)">
        &middot; ${g.rows.length} case${g.rows.length === 1 ? '' : 's'}</span></p>
    <div class="card card-flush"><div style="overflow-x:auto"><table>
      <thead><tr><th>Case ID</th><th>Received</th><th>Waiting</th><th>SVI</th><th>Risk</th>
        <th>Top reason</th><th>Status</th><th></th></tr></thead>
      <tbody>${g.rows.map((c) => `
        <tr><td><b>${esc(c.case_id)}</b></td>
          <td style="color:var(--muted)">${fmtTime(c.uploaded_at)}</td>
          <td style="color:var(--muted)">${ago(c.uploaded_at)}</td>
          <td><b>${c.svi_score}</b></td>
          <td>${riskPill(c.svi_category)}</td>
          <td style="color:var(--text-2);max-width:280px">${esc(
            (c.danger_reasons && c.danger_reasons[0]) ||
            (c.distress_reasons && c.distress_reasons[0]) || '-')}</td>
          <td>${statusPill(c.status)}</td>
          <td style="text-align:right;white-space:nowrap">
            <button class="btn btn-ghost btn-sm" data-open="${c.id}">Open</button>
            ${c.status === 'Pending'
              ? `<button class="btn btn-outline btn-sm" data-take="${c.id}">Take</button>`
              : `<button class="btn btn-outline btn-sm" data-done="${c.id}">Resolve</button>`}
          </td></tr>`).join('')}</tbody>
    </table></div></div>`).join('')
  : `<div class="card" style="margin-top:16px"><p class="empty">
      ${counts.all ? 'Nothing matches this filter.' : 'The queue is clear. Every case has been reviewed.'}
     </p></div>`}

  <p class="hint" style="margin-top:16px">Queue order comes from the SVI. A counsellor can open
    any case in any order - NAVHRIDYA never removes a case from the queue by itself.</p>`;
}

function wirePending() {
  document.querySelectorAll('[data-f]').forEach((b) => {
    b.onclick = () => { PEND.filter = b.dataset.f; render(); };
  });
  document.querySelectorAll('[data-open]').forEach((b) => {
    b.onclick = () => { select(Number(b.dataset.open)); location.hash = '#/dashboard'; };
  });
  const move = (attr, status, msg) => document.querySelectorAll(`[${attr}]`).forEach((b) => {
    b.onclick = async () => {
      b.disabled = true;
      try {
        await apiJson(`/cases/${b.getAttribute(attr)}/status`, 'PATCH', { status });
        toast(msg);
        await refresh();
      } catch (ex) { toast(ex.message, 'bad'); b.disabled = false; }
    };
  });
  move('data-take', 'In Progress', 'Case taken - now under review.');
  move('data-done', 'Resolved', 'Case marked resolved.');
}

/* ===================================================================== */
/*  PAGE: Reports                                                        */
/* ===================================================================== */
let REP = { q: '', band: 'All', status: 'All', open: null };

function pageReports() {
  if (!S.cases.length) {
    return `
    <div class="phead">
      <div><h1>Reports</h1>
        <p class="sub">Every case uploaded on this deployment, with its recording, transcript,
          timestamps, SVI and the reasoning behind the score.</p></div>
    </div>
    ${firstRun('No cases on record',
      'Once a call has been scored it is kept here for good - the recording, the full '
      + 'transcript, the timestamps, the SVI and every reason behind it.')}`;
  }

  let rows = S.cases.slice();
  if (REP.band !== 'All') rows = rows.filter((c) => c.svi_category === REP.band);
  if (REP.status !== 'All') rows = rows.filter((c) => c.status === REP.status);
  if (REP.q.trim()) {
    const q = REP.q.trim().toLowerCase();
    rows = rows.filter((c) => (c.case_id + ' ' + c.transcript + ' ' + c.summary + ' ' +
      c.language + ' ' + c.channel).toLowerCase().includes(q));
  }

  const withAudio = S.cases.filter((c) => c.audio_filename).length;
  const avgSvi = S.cases.length
    ? Math.round(S.cases.reduce((a, c) => a + c.svi_score, 0) / S.cases.length) : 0;
  const floors = S.cases.filter((c) => c.safety_floor_triggered).length;

  return `
  <div class="phead">
    <div><h1>Reports</h1>
      <p class="sub">Every case uploaded on this deployment, with its recording, transcript,
        timestamps, SVI and the reasoning behind the score.</p></div>
    <a class="btn btn-primary btn-sm" href="#/upload">${icon('upload', 15)} Upload Call</a>
  </div>

  <div class="grid g4" style="margin-top:14px;align-items:start">
    <div class="card"><div class="stat">
      <span class="ico" style="background:var(--surface-3);color:var(--text)">${icon('files')}</span>
      <div><p class="lbl">Cases on record</p><p class="val">${S.cases.length}</p></div></div>
      <p class="note">${withAudio} with a stored recording</p></div>
    <div class="card"><div class="stat">
      <span class="ico" style="background:var(--mod-bg);color:var(--mod)">${icon('chart')}</span>
      <div><p class="lbl">Average SVI</p><p class="val">${avgSvi}</p></div></div>
      <p class="note">across every stored case</p></div>
    <div class="card"><div class="stat">
      <span class="ico" style="background:var(--crit-bg);color:var(--crit)">${icon('shield')}</span>
      <div><p class="lbl">Safety floor fired</p><p class="val">${floors}</p></div></div>
      <p class="note">forced to Critical outside the model</p></div>
    <div class="card">
      <p class="lbl" style="margin:0;font-size:12px;color:var(--muted);font-weight:550">
        Cases per day, last 7 days</p>
      ${trendBars(S.cases)}
    </div>
  </div>

  <div class="card" style="margin-top:14px">
    <div style="display:grid;gap:10px;grid-template-columns:1fr;align-items:end">
      <div style="display:grid;gap:10px;grid-template-columns:2fr 1fr 1fr">
        <label class="fld" style="margin:0">Search case ID, transcript or summary
          <input id="q" type="search" value="${esc(REP.q)}" placeholder="threat, #C2026..., Hindi" /></label>
        <label class="fld" style="margin:0">Risk band
          <select id="band">${['All', ...ORDER].map((b) =>
            `<option ${b === REP.band ? 'selected' : ''}>${b}</option>`).join('')}</select></label>
        <label class="fld" style="margin:0">Status
          <select id="status">${['All', ...STATUSES].map((b) =>
            `<option ${b === REP.status ? 'selected' : ''}>${b}</option>`).join('')}</select></label>
      </div>
    </div>
    <p class="hint">${rows.length} of ${S.cases.length} case${S.cases.length === 1 ? '' : 's'} shown.
      Click a row to open the full record, the recording and the reasoning.</p>
  </div>

  ${rows.length ? rows.map((c) => reportRow(c)).join('')
    : '<div class="card" style="margin-top:12px"><p class="empty">No case matches these filters.</p></div>'}

  <p class="hint" style="margin-top:16px">Recordings are stored on this deployment only and are
    streamed back from the server - they are never sent anywhere else from this page.</p>`;
}

function reportRow(c) {
  const isOpen = REP.open === c.id;
  return `
  <details class="acc" ${isOpen ? 'open' : ''} data-case="${c.id}">
    <summary>
      <span style="color:var(--muted)">${icon(c.audio_filename ? 'play' : 'text', 15)}</span>
      <span class="cid">${esc(c.case_id)}</span>
      <span style="color:var(--muted);font-size:12.5px">${fmtStamp(c.uploaded_at)}</span>
      <span class="sp">
        <span style="font-weight:750">SVI ${c.svi_score}</span>
        ${riskPill(c.svi_category)}${statusPill(c.status)}
      </span>
    </summary>
    <div class="body">
      <div class="kv">
        <div>
          <p class="ct" style="font-size:14px">Record</p>
          <dl>
            <div class="row"><dt>Case ID</dt><dd><b>${esc(c.case_id)}</b></dd></div>
            <div class="row"><dt>Uploaded</dt><dd>${fmtStamp(c.uploaded_at)}
              <span style="color:var(--faint)">&middot; ${ago(c.uploaded_at)}</span></dd></div>
            <div class="row"><dt>Channel</dt><dd>NHAA 14566 (${esc(c.channel)})</dd></div>
            <div class="row"><dt>Language</dt><dd>${esc(c.language)}</dd></div>
            <div class="row"><dt>Recording</dt><dd>${c.audio_filename
              ? `${esc(c.audio_original_name || c.audio_filename)}
                 <span style="color:var(--faint)">&middot; ${fmtBytes(c.audio_bytes)}${
                   c.audio_duration_seconds ? ' &middot; ' +
                   Math.round(c.audio_duration_seconds) + 's' : ''}</span>`
              : '<span style="color:var(--faint)">transcript only, no audio uploaded</span>'}</dd></div>
            <div class="row"><dt>SVI</dt><dd><b>${c.svi_score} / 100</b> &nbsp;${riskPill(c.svi_category)}</dd></div>
            <div class="row"><dt>Distress</dt><dd>${c.distress_score} / 100 (${bandOf(c.distress_score)})</dd></div>
            <div class="row"><dt>Danger</dt><dd>${c.danger_score} / 100 (${bandOf(c.danger_score)})</dd></div>
            <div class="row"><dt>Indicators</dt><dd class="tags">${
              Object.entries(c.indicators || {}).filter(([, v]) => v)
                .map(([k]) => `<span class="tag">${esc(label(k))}</span>`).join('')
              || '<span style="color:var(--faint);font-size:12.5px">None flagged</span>'}</dd></div>
            <div class="row"><dt>Summary</dt><dd>${esc(c.summary)}</dd></div>
          </dl>

          ${c.audio_filename ? `
            <p class="ct" style="font-size:14px;margin-top:16px">Recording</p>
            <audio controls preload="none" src="/api/cases/${c.id}/audio"></audio>
            <p class="hint"><a href="/api/cases/${c.id}/audio" download>${icon('download', 13)}
              Download the original file</a></p>` : ''}

          <p class="ct" style="font-size:14px;margin-top:16px">Transcript</p>
          <p class="hint" style="margin:0">Safety-rule matches are highlighted in place.</p>
          <div class="transcript">${highlighted(c)}</div>
        </div>

        <div>
          <p class="ct" style="font-size:14px">Why it scored ${c.svi_score}</p>
          ${whyBlock(c)}
          <div class="whyhead">${icon('spark', 14)} Recommended actions</div>
          ${recoList(c)}
          <div class="actions" style="justify-content:flex-start">
            <label class="fld" style="margin:0;flex:1;min-width:160px">Status
              <select data-set="${c.id}">${STATUSES.map((s) =>
                `<option ${s === c.status ? 'selected' : ''}>${s}</option>`).join('')}</select></label>
            <button class="btn btn-ghost btn-sm" data-focus="${c.id}"
              style="align-self:flex-end">Show on dashboard</button>
          </div>
          <div class="setrow danger-zone" style="border-bottom:0;padding-bottom:0">
            <div class="t"><b>Delete this case</b>
              <span>Removes the record, the transcript and the recording. This cannot be undone.</span></div>
            <button class="btn btn-danger btn-sm" data-del="${c.id}">${icon('trash', 14)} Delete</button>
          </div>
        </div>
      </div>
    </div>
  </details>`;
}

function wireReports() {
  const q = $('q');
  if (q) {
    q.oninput = () => {
      REP.q = q.value;
      clearTimeout(q._t);
      q._t = setTimeout(() => { render(); $('q').focus(); }, 260);
    };
  }
  const band = $('band'), status = $('status');
  if (band) band.onchange = () => { REP.band = band.value; render(); };
  if (status) status.onchange = () => { REP.status = status.value; render(); };

  document.querySelectorAll('details[data-case]').forEach((d) => {
    d.addEventListener('toggle', () => {
      if (d.open) REP.open = Number(d.dataset.case);
      else if (REP.open === Number(d.dataset.case)) REP.open = null;
    });
  });
  document.querySelectorAll('[data-set]').forEach((sel) => {
    sel.onchange = async () => {
      try {
        await apiJson(`/cases/${sel.dataset.set}/status`, 'PATCH', { status: sel.value });
        toast('Status updated to ' + sel.value + '.');
        await refresh();
      } catch (ex) { toast(ex.message, 'bad'); }
    };
  });
  document.querySelectorAll('[data-focus]').forEach((b) => {
    b.onclick = () => { select(Number(b.dataset.focus)); location.hash = '#/dashboard'; };
  });
  document.querySelectorAll('[data-del]').forEach((b) => {
    b.onclick = () => confirmDialog({
      title: 'Delete this case?',
      body: 'The record, its transcript and any stored recording are removed permanently. '
          + 'This cannot be undone.',
      confirm: 'Delete case',
      danger: true,
      onYes: async () => {
        await api('/cases/' + b.dataset.del, { method: 'DELETE' });
        REP.open = null;
        toast('Case deleted.');
        await refresh();
      },
    });
  });
}

/* ===================================================================== */
/*  PAGE: Settings                                                       */
/* ===================================================================== */
function pageSettings() {
  const me = S.me || {};
  const mine = S.cases.filter((c) => c.uploaded_by === me.id).length;
  const initials = (me.full_name || me.username || '?').split(/\s+/)
    .map((w) => w[0]).slice(0, 2).join('').toUpperCase();

  return `
  <div class="phead">
    <div><h1>Settings</h1>
      <p class="sub">Your profile, the appearance of this console, and account controls.</p></div>
  </div>

  <div class="grid g2" style="margin-top:14px;align-items:start">
    <div class="card">
      <p class="ct">Profile</p>
      <p class="csub">Shown on the cases you review and in the header of this console.</p>
      <div style="display:flex;gap:14px;align-items:center;margin-top:16px">
        <div class="avatar">${esc(initials)}</div>
        <div>
          <p style="margin:0;font-size:17px;font-weight:700">${esc(me.full_name || me.username || '')}</p>
          <p style="margin:2px 0 0;font-size:12.5px;color:var(--muted)">
            @${esc(me.username || '')} &middot; ${esc(label(me.role || 'counsellor'))}
            ${me.created_at ? '&middot; joined ' + fmtDate(me.created_at) : ''}</p>
        </div>
      </div>

      <label class="fld">Full name
        <input id="pFull" type="text" value="${esc(me.full_name || '')}" placeholder="Your name" /></label>
      <label class="fld">Work email
        <input id="pMail" type="email" value="${esc(me.email || '')}" placeholder="you@nhaa.gov.in" /></label>
      <label class="fld">Helpline centre
        <input id="pCentre" type="text" value="${esc(me.centre || '')}" /></label>
      <p class="err" id="pErr"></p>
      <button class="btn btn-primary" id="pSave">${icon('check', 16)} Save profile</button>

      <div class="strip">${icon('files')}<div><b>${mine} case${mine === 1 ? '' : 's'} uploaded
        by you</b><br/>Every case you upload stays linked to this account and appears in
        Reports.</div></div>
    </div>

    <div>
      <div class="card">
        <p class="ct">Appearance</p>
        <p class="csub">The choice is remembered on this device and on your account.</p>
        <div class="setrow">
          <div class="t"><b>Theme</b><span>Light for daytime shifts, dark for night shifts in a
            low-light control room.</span></div>
          <div id="tsw2"></div>
        </div>
      </div>

      <div class="card" style="margin-top:14px" ${me.is_guest ? 'hidden' : ''}>
        <p class="ct">Password</p>
        <p class="csub">Change the password used to sign in to this console.</p>
        <label class="fld">New password
          <span class="pw">
            <input id="pw1" type="password" placeholder="At least 8 characters"
              autocomplete="new-password" />
            <button type="button" id="peek2">Show</button>
          </span></label>
        <label class="fld">Confirm new password
          <input id="pw2" type="password" placeholder="Type it again" autocomplete="new-password" /></label>
        <p class="err" id="wErr"></p>
        <button class="btn btn-outline" id="wSave">${icon('lock', 16)} Update password</button>
      </div>

      <div class="card" style="margin-top:14px">
        <p class="ct">Session</p>
        <div class="setrow">
          <div class="t"><b>Sign out</b><span>Ends this session and returns to the NAVHRIDYA
            homepage. Your cases stay on the server.</span></div>
          <button class="btn btn-outline" id="sOut">${icon('logout', 16)} Sign out</button>
        </div>
      </div>

      <div class="card danger-zone" style="margin-top:14px" ${me.is_guest ? 'hidden' : ''}>
        <p class="ct" style="color:var(--crit)">Danger zone</p>
        <div class="setrow" style="border-bottom:0">
          <div class="t"><b>Delete this account</b>
            <span>Permanently removes your account and every case you uploaded, including stored
              recordings. This cannot be undone.</span></div>
          <button class="btn btn-danger" id="dAcc">${icon('trash', 16)} Delete account</button>
        </div>
      </div>

      <div class="card" style="margin-top:14px">
        <p class="ct">About this deployment</p>
        <dl>
          <div class="row"><dt>Analysis</dt><dd>${
            me.ai_mode && !/offline demo/i.test(me.ai_mode)
              ? 'AI analysis active' : 'Offline analyser (no AI key configured)'}</dd></div>
          <div class="row"><dt>Cases stored</dt><dd>${S.cases.length}</dd></div>
          <div class="row"><dt>Problem statement</dt><dd>PS SIH26093, Team HackSmiths</dd></div>
          <div class="row"><dt>Helpline</dt><dd>NHAA 14566, Ministry of Social Justice &amp;
            Empowerment</dd></div>
          <div class="row"><dt>Live calls</dt><dd>${
            LIVE.cfg ? (LIVE.cfg.available ? 'Available' : 'Not configured') : 'checking...'
          }</dd></div>
        </dl>
      </div>
    </div>
  </div>`;
}

function wireSettings() {
  mountThemeSwitch($('tsw2'), saveTheme);

  const sOut = $('sOut');
  if (sOut) sOut.onclick = () => confirmDialog({
    title: 'Sign out of NAVHRIDYA?',
    body: 'You will be returned to the homepage. Every case you uploaded stays on the server '
        + 'and will be here when you sign back in.',
    confirm: 'Sign out',
    onYes: async () => signOut(),
  });

  if (!$('peek2')) return;      // a guest sees no password or delete section

  $('peek2').onclick = () => {
    const f = $('pw1');
    const showing = f.type === 'text';
    f.type = showing ? 'password' : 'text';
    $('peek2').textContent = showing ? 'Show' : 'Hide';
  };

  $('pSave').onclick = async () => {
    $('pErr').textContent = '';
    $('pSave').disabled = true;
    try {
      S.me = Object.assign({}, S.me, await apiJson('/auth/me', 'PATCH', {
        full_name: $('pFull').value.trim(),
        email: $('pMail').value.trim(),
        centre: $('pCentre').value.trim(),
      }));
      localStorage.setItem('nav_user', JSON.stringify(S.me));
      toast('Profile saved.');
      render();
    } catch (ex) { $('pErr').textContent = ex.message; $('pSave').disabled = false; }
  };

  $('wSave').onclick = async () => {
    $('wErr').textContent = '';
    const a = $('pw1').value, b = $('pw2').value;
    if (a.length < 8) { $('wErr').textContent = 'The new password must be at least 8 characters.'; return; }
    if (a !== b) { $('wErr').textContent = 'The two passwords do not match.'; return; }
    $('wSave').disabled = true;
    try {
      await apiJson('/auth/me', 'PATCH', { new_password: a });
      toast('Password updated. It applies the next time you sign in.');
      $('pw1').value = ''; $('pw2').value = '';
    } catch (ex) { $('wErr').textContent = ex.message; }
    $('wSave').disabled = false;
  };

  $('dAcc').onclick = () => confirmDialog({
    title: 'Delete your account?',
    body: `This removes the account @${S.me.username} and every case you uploaded, including any `
        + 'stored recordings. It cannot be undone. Enter your password to confirm.',
    confirm: 'Delete my account',
    danger: true,
    password: true,
    onYes: async (pw) => {
      const out = await apiJson('/auth/me', 'DELETE', { password: pw });
      toast(`Account deleted along with ${out.cases_removed} case(s).`);
      setTimeout(signOut, 900);
    },
  });
}

async function saveTheme(mode) {
  try { await apiJson('/auth/me', 'PATCH', { theme: mode }); if (S.me) S.me.theme = mode; }
  catch (e) { /* the local choice already applied; the server copy is a convenience */ }
  render();
}

/* ------------------------------------------------------------- confirm box */
function confirmDialog({ title, body, confirm, danger, password, onYes }) {
  const host = $('modalHost');
  host.innerHTML = `<div class="modal"><div class="sheet">
    <h3 style="font-size:19px">${esc(title)}</h3>
    <p style="color:var(--text-2);font-size:14px;margin:10px 0 0">${esc(body)}</p>
    ${password ? `<label class="fld">Your password
      <span class="pw"><input id="cpw" type="password" autocomplete="current-password" />
        <button type="button" id="cpeek">Show</button></span></label>` : ''}
    <p class="err" id="cerr"></p>
    <div class="actions">
      <button class="btn btn-ghost" id="cno">Cancel</button>
      <button class="btn ${danger ? 'btn-danger' : 'btn-primary'}" id="cyes">${esc(confirm)}</button>
    </div>
  </div></div>`;
  const close = () => (host.innerHTML = '');
  $('cno').onclick = close;
  if (password) {
    $('cpeek').onclick = () => {
      const f = $('cpw');
      const showing = f.type === 'text';
      f.type = showing ? 'password' : 'text';
      $('cpeek').textContent = showing ? 'Show' : 'Hide';
    };
    $('cpw').focus();
  }
  $('cyes').onclick = async () => {
    $('cerr').textContent = '';
    $('cyes').disabled = true;
    try {
      await onYes(password ? $('cpw').value : undefined);
      close();
    } catch (ex) {
      $('cerr').textContent = ex.message;
      $('cyes').disabled = false;
    }
  };
}

/* ===================================================================== */
/*  router + boot                                                        */
/* ===================================================================== */
const VIEWS = {
  dashboard: [pageDashboard, wireDashboard],
  live: [pageLive, wireLive],
  upload: [pageUpload, wireUpload],
  pending: [pagePending, wirePending],
  reports: [pageReports, wireReports],
  settings: [pageSettings, wireSettings],
};

function render() {
  renderChrome();
  const [page, wire] = VIEWS[route()];
  $('view').innerHTML = page();
  if (wire) wire();
  // "Try a sample transcript" should land on the upload page already in
  // transcript mode, rather than making the person find the tab themselves
  document.querySelectorAll('[data-sample]').forEach((a) => {
    a.onclick = () => { UP.mode = 'text'; };
  });
}

async function refresh(keepId) {
  const [cases, stats, dist] = await Promise.all([
    api('/cases'), api('/dashboard/stats'), api('/dashboard/risk-distribution'),
  ]);
  S.cases = cases; S.stats = stats; S.dist = dist;
  const want = keepId != null ? keepId : (S.selected && S.selected.id);
  S.selected = cases.find((c) => c.id === want) || cases[0] || null;
  if (S.selected) localStorage.setItem('nav_case', String(S.selected.id));
  render();
}

function tick() {
  const el = $('clock');
  if (!el) return;
  const n = new Date();
  el.textContent =
    n.toLocaleDateString([], { weekday: 'short', day: '2-digit', month: 'short', year: 'numeric' })
    + '  ' + n.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false });
}

window.addEventListener('hashchange', () => {
  if (S.ready) render();
  window.scrollTo({ top: 0 });
});

(async function boot() {
  mountFooter();
  mountThemeSwitch($('tsw'), saveTheme);
  $('signout').onclick = () => {
    if (S.me && S.me.is_guest) { location.href = '/login'; return; }
    confirmDialog({
      title: 'Sign out of NAVHRIDYA?',
      body: 'You will be returned to the homepage. Every case you uploaded stays on the server.',
      confirm: 'Sign out',
      onYes: async () => signOut(),
    });
  };

  if (!location.hash) location.replace('#/dashboard');

  try {
    if (!TOKEN) await openGuestSession();
    await loadAll();
  } catch (ex) {
    $('view').innerHTML = `<div class="card" style="margin-top:24px">
      <p class="ct">Could not load your cases</p>
      <p class="csub">${esc(ex.message)}</p>
      <button class="btn btn-primary btn-sm" style="margin-top:12px"
        onclick="location.reload()">Try again</button></div>`;
    return;
  }

  if (S.me && S.me.theme && S.me.theme !== currentTheme()) applyTheme(S.me.theme);
  localStorage.setItem('nav_user', JSON.stringify(S.me));
  render();
  setInterval(tick, 30000);
})();
