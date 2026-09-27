/* Shared helpers: icons, theme, footer, toast.
   Loaded by the landing page, the auth page and the operator app, so the three
   never drift apart. No build step, no CDN - everything is hand-written here. */

const SVG = {
  files: 'M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5',
  alert: 'M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0zM12 9v4M12 17h.01',
  people: 'M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2M9 3a4 4 0 1 1 0 8 4 4 0 0 1 0-8M22 21v-2a4 4 0 0 0-3-3.9',
  clock: 'M12 3a9 9 0 1 1 0 18 9 9 0 0 1 0-18M12 7v5l3 2',
  grid: 'M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z',
  headset: 'M4 14v-2a8 8 0 1 1 16 0v2M2.5 15.5h3v5h-3zM18.5 15.5h3v5h-3z',
  chart: 'M4 20V10M10 20V4M16 20v-7M22 20H2',
  gear: 'M12 9a3 3 0 1 1 0 6 3 3 0 0 1 0-6M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-2.8 1.1V21a2 2 0 1 1-4 0v-.1a1.6 1.6 0 0 0-2.8-1.1l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1A1.6 1.6 0 0 0 3 15H3a2 2 0 1 1 0-4h.1A1.6 1.6 0 0 0 4.6 9a1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1A1.6 1.6 0 0 0 9 4.6V3a2 2 0 1 1 4 0v.1a1.6 1.6 0 0 0 2.8 1.1l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1A1.6 1.6 0 0 0 19.4 9H21a2 2 0 1 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z',
  spark: 'm12 3 1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z',
  scale: 'M12 3v18M7 21h10M5 7h14M5 7l-3 7h6zM19 7l3 7h-6z',
  shield: 'M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10zM9 12l2 2 4-4',
  cross: 'M12 5v14M5 12h14',
  eye: 'M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7-10-7-10-7M12 9a3 3 0 1 1 0 6 3 3 0 0 1 0-6',
  calendar: 'M5 5h14a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2zM16 3v4M8 3v4M3 11h18',
  upload: 'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12',
  mic: 'M12 2a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V5a3 3 0 0 1 3-3zM19 10v1a7 7 0 0 1-14 0v-1M12 19v3',
  text: 'M4 6h16M4 12h16M4 18h10',
  sun: 'M12 5a7 7 0 1 1 0 14 7 7 0 0 1 0-14M12 1v2M12 21v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M1 12h2M21 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4',
  moon: 'M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z',
  logout: 'M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9',
  user: 'M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 3a4 4 0 1 1 0 8 4 4 0 0 1 0-8',
  trash: 'M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6',
  play: 'M6 4l14 8-14 8z',
  check: 'M20 6 9 17l-5-5',
  arrow: 'M5 12h14M13 5l7 7-7 7',
  lock: 'M5 11h14a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2zM8 11V7a4 4 0 0 1 8 0v4',
  layers: 'M12 2 2 7l10 5 10-5zM2 17l10 5 10-5M2 12l10 5 10-5',
  refresh: 'M21 12a9 9 0 1 1-3-6.7M21 3v6h-6',
  info: 'M12 3a9 9 0 1 1 0 18 9 9 0 0 1 0-18M12 11v6M12 7.5h.01',
  download: 'M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3',
};

const icon = (name, size = 16) =>
  `<svg viewBox="0 0 24 24" width="${size}" height="${size}" fill="none" stroke="currentColor"
     stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"
     ><path d="${SVG[name] || SVG.info}"/></svg>`;

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

/* ------------------------------------------------------------------ theme */
const THEME_KEY = 'nav_theme';

function currentTheme() {
  try { return localStorage.getItem(THEME_KEY) === 'dark' ? 'dark' : 'light'; }
  catch (e) { return 'light'; }
}

function applyTheme(mode) {
  const t = mode === 'dark' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', t);
  try { localStorage.setItem(THEME_KEY, t); } catch (e) { /* private mode */ }
  document.querySelectorAll('[data-theme-btn]').forEach((b) =>
    b.classList.toggle('on', b.dataset.themeBtn === t));
  return t;
}

/** Renders the light/dark switch into a host element and wires it up.
 *  onChange is optional - the app uses it to persist the choice server-side. */
function mountThemeSwitch(host, onChange) {
  if (!host) return;
  host.className = 'tswitch';
  host.innerHTML = `
    <button type="button" data-theme-btn="light" title="Light theme">${icon('sun', 14)} Light</button>
    <button type="button" data-theme-btn="dark" title="Dark theme">${icon('moon', 14)} Dark</button>`;
  host.querySelectorAll('[data-theme-btn]').forEach((b) => {
    b.onclick = () => {
      const t = applyTheme(b.dataset.themeBtn);
      if (onChange) onChange(t);
    };
  });
  applyTheme(currentTheme());
}

/* ----------------------------------------------------------------- toast */
function toast(msg, kind) {
  const d = document.createElement('div');
  d.className = 'toast';
  if (kind === 'bad') d.style.background = 'var(--crit)';
  d.textContent = msg;
  document.body.appendChild(d);
  setTimeout(() => d.remove(), 3400);
}

/* ---------------------------------------------------------------- footer */
const FOOTER_HTML = `
<footer class="site-foot">
  <div class="wrap">
    <div class="cols">
      <div>
        <div class="brand">
          <img src="/assets/logo.png" alt="NAVHRIDYA" />
          <div>
            <h4 style="margin:0;color:var(--text);text-transform:none;letter-spacing:-.2px;font-size:16px">NAVHRIDYA</h4>
            <p style="margin:2px 0 0;font-size:13px;color:var(--muted)">
              A stress and trauma assessment layer proposed for the National Helpline
              Against Atrocities (14566), so the most vulnerable caller is reached first.</p>
          </div>
        </div>
        <div class="helpline">${icon('headset', 15)} NHAA helpline 14566 &middot; toll free, 24x7</div>
      </div>
      <div>
        <h4>Product</h4>
        <ul>
          <li><a href="/home#how">How it works</a></li>
          <li><a href="/home#differentiators">Key differentiators</a></li>
          <li><a href="/home#svi">SVI scoring</a></li>
          <li><a href="/home#safety">Safety by design</a></li>
        </ul>
      </div>
      <div>
        <h4>For counsellors</h4>
        <ul>
          <li><a href="/login">Sign in</a></li>
          <li><a href="/login#signup">Create account</a></li>
          <li><a href="/app#/upload">Upload a call</a></li>
          <li><a href="/app#/reports">Reports</a></li>
        </ul>
      </div>
      <div>
        <h4>Context</h4>
        <ul>
          <li>Ministry of Social Justice &amp; Empowerment</li>
          <li>SC/ST (Prevention of Atrocities) Act, 1989</li>
          <li>Smart India Hackathon 2026</li>
          <li>PS SIH26093 &middot; Team HackSmiths</li>
        </ul>
      </div>
    </div>
    <div class="legal">
      <span>Prototype built for Smart India Hackathon 2026. Not an official Government of
        India service, and not a substitute for emergency help.</span>
      <span>If someone is in immediate danger, call 112.</span>
    </div>
  </div>
</footer>`;

function mountFooter(host) {
  const el = host || document.getElementById('footer');
  if (el) el.outerHTML = FOOTER_HTML;
}

applyTheme(currentTheme());
