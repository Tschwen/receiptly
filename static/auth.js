// Optional in-app login for deployments behind an HTTP Basic Auth reverse proxy.
//
// Completely invisible unless the server answers 401: without proxy auth the
// app boots exactly as before. With proxy auth, credentials are entered once
// via a real HTML form (so password managers can autofill them — the native
// Basic-Auth dialog of standalone/home-screen webapps cannot), stored
// on-device and attached to every request as an Authorization header.
// The service worker (sw.js) serves the cached app shell so launches don't
// trigger the proxy's native login popup.

const AUTH_KEY = 'receiptly_auth';
const SHELL_CACHE = 'receiptly-shell-v1';
const SHELL_URLS = ['/', '/index.html', '/admin.html', '/auth.js', '/i18n/en.json', '/i18n/de.json'];

function getAuth() { return localStorage.getItem(AUTH_KEY); }
function setAuth(v) { localStorage.setItem(AUTH_KEY, v); }
function clearAuth() { localStorage.removeItem(AUTH_KEY); }

function authHeaders(extra) {
  const h = { ...(extra || {}) };
  const auth = getAuth();
  if (auth) h['Authorization'] = 'Basic ' + auth;
  return h;
}

// fetch() wrapper: attaches stored credentials and shows the login overlay on 401.
// With stored credentials we use credentials:'omit' so the explicit header is
// authoritative and the browser never opens its native auth dialog for the
// request; without stored credentials the browser's session auth (if any)
// keeps working untouched.
async function authFetch(url, opts = {}) {
  const init = { ...opts, headers: authHeaders(opts.headers) };
  if (getAuth()) init.credentials = 'omit';
  const res = await fetch(url, init);
  if (res.status === 401) {
    clearAuth();
    showLogin(false);
    throw new Error('401 Unauthorized');
  }
  return res;
}

// Basic-Auth token from user/password, UTF-8 safe (btoa alone chokes on umlauts).
function encodeBasic(user, pass) {
  const bytes = new TextEncoder().encode(user + ':' + pass);
  let bin = '';
  bytes.forEach(b => { bin += String.fromCharCode(b); });
  return btoa(bin);
}

const AUTH_T = (localStorage.getItem('lang') || 'en') === 'de' ? {
  title: 'Anmeldung', user: 'Benutzername', pass: 'Passwort', submit: 'Anmelden',
  later: 'Später', failed: 'Anmeldung fehlgeschlagen',
  hint: 'Die Zugangsdaten werden nur auf diesem Gerät gespeichert.',
} : {
  title: 'Login', user: 'Username', pass: 'Password', submit: 'Log in',
  later: 'Later', failed: 'Login failed',
  hint: 'Credentials are stored on this device only.',
};

// Login overlay. dismissable=true is the proactive variant (app still works
// this session via the browser's auth session, we just want to store
// credentials for the next launch); dismissable=false blocks until login.
function showLogin(dismissable) {
  if (document.getElementById('auth-overlay')) return;

  const style = document.createElement('style');
  style.textContent = `
    #auth-overlay{position:fixed;inset:0;background:rgba(58,46,34,.88);display:flex;align-items:center;justify-content:center;z-index:1000;backdrop-filter:blur(4px);-webkit-backdrop-filter:blur(4px)}
    .auth-card{background:var(--white,#fff);border-radius:20px;padding:32px 28px;max-width:320px;width:calc(100% - 32px);margin:16px;text-align:center}
    .auth-title{font-size:20px;color:var(--text,#3a2e22);margin-bottom:18px}
    .auth-field{width:100%;background:var(--white,#fff);border:1.5px solid var(--highlight,#d4c4a0);border-radius:12px;padding:13px 14px;font-family:'Georgia',serif;font-size:16px;color:var(--text,#3a2e22);outline:none;margin-bottom:10px;-webkit-appearance:none;appearance:none;box-sizing:border-box}
    .auth-field:focus{border-color:var(--ochre,#b8842a)}
    .auth-error{color:var(--red,#c0392b);font-size:13px;min-height:18px;margin-bottom:8px}
    .auth-btn{width:100%;padding:14px;border:none;border-radius:12px;background:var(--header,#3a2e22);color:var(--on-header,#f5f0e8);font-family:'Georgia',serif;font-size:15px;cursor:pointer}
    .auth-later{background:none;border:none;color:var(--text,#3a2e22);font-family:'Georgia',serif;font-size:13px;cursor:pointer;margin-top:12px;text-decoration:underline}
    .auth-hint{font-size:11px;color:var(--text,#3a2e22);opacity:.6;margin-top:14px;line-height:1.4}
  `;
  document.head.appendChild(style);

  const ov = document.createElement('div');
  ov.id = 'auth-overlay';
  ov.innerHTML = `
    <div class="auth-card">
      <div class="auth-title">🔒 ${AUTH_T.title}</div>
      <form id="auth-form" method="post" action="#">
        <input class="auth-field" id="auth-user" name="username" type="text" required
               autocomplete="username" autocapitalize="none" autocorrect="off"
               placeholder="${AUTH_T.user}" />
        <input class="auth-field" id="auth-pass" name="password" type="password" required
               autocomplete="current-password" placeholder="${AUTH_T.pass}" />
        <div class="auth-error" id="auth-error"></div>
        <button class="auth-btn" id="auth-submit" type="submit">${AUTH_T.submit}</button>
      </form>
      ${dismissable ? `<button class="auth-later" id="auth-later" type="button">${AUTH_T.later}</button>` : ''}
      <div class="auth-hint">${AUTH_T.hint}</div>
    </div>`;
  document.body.appendChild(ov);

  if (dismissable) {
    document.getElementById('auth-later').addEventListener('click', () => ov.remove());
  }

  document.getElementById('auth-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const btn = document.getElementById('auth-submit');
    const err = document.getElementById('auth-error');
    const token = encodeBasic(
      document.getElementById('auth-user').value.trim(),
      document.getElementById('auth-pass').value,
    );
    btn.disabled = true;
    err.textContent = '';
    try {
      const res = await fetch('/api/config', {
        headers: { 'Authorization': 'Basic ' + token },
        credentials: 'omit',
        cache: 'no-store',
      });
      if (res.ok) {
        setAuth(token);
        location.reload();
        return;
      }
      err.textContent = AUTH_T.failed;
    } catch (_) {
      err.textContent = AUTH_T.failed;
    }
    btn.disabled = false;
  });
}

// Detect "behind proxy auth via browser session, but nothing stored yet"
// (first launch / after storage eviction): credentials:'omit' suppresses the
// session's HTTP auth where supported, so a 401 here means the proxy wants
// auth and we should capture credentials now for popup-free future launches.
// If the browser ignores 'omit', recovery simply happens on the next launch.
async function probeAuthNeeded() {
  if (getAuth()) return;
  try {
    const res = await fetch('/api/config', { credentials: 'omit', cache: 'no-store' });
    if (res.status === 401) showLogin(true);
  } catch (_) {}
}

// ── App shell cache ───────────────────────────────────────────────────────────
// The page (not the worker) fills the cache, so the worker never needs
// credentials. Stale-while-revalidate: every successful boot refreshes the
// shell for the next launch.
async function refreshShellCache() {
  if (!('caches' in window)) return;
  try {
    const cache = await caches.open(SHELL_CACHE);
    await Promise.all(SHELL_URLS.map(async (u) => {
      try {
        const res = await fetch(u, {
          headers: authHeaders(),
          cache: 'no-store',
          credentials: getAuth() ? 'omit' : 'same-origin',
        });
        if (res.ok) await cache.put(u, res);
      } catch (_) {}
    }));
  } catch (_) {}
}

// Call once after the app finished booting (successfully or not).
function authBootDone() {
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').catch(() => {});
  }
  refreshShellCache();
  probeAuthNeeded();
}

// ── Authenticated file links (PDF / ZIP) ─────────────────────────────────────
// Plain navigation cannot carry our header, so with stored credentials files
// are fetched as blobs. Without stored credentials the default behavior is
// kept (returns true so the <a> just navigates).
async function authOpen(url) {
  if (!getAuth()) { window.open(url, '_blank'); return; }
  try {
    const res = await authFetch(url);
    const blobUrl = URL.createObjectURL(await res.blob());
    const w = window.open(blobUrl, '_blank');
    if (!w) {
      const a = document.createElement('a');
      a.href = blobUrl; a.target = '_blank'; a.rel = 'noopener';
      document.body.appendChild(a); a.click(); a.remove();
    }
  } catch (_) {}
}

async function authDownload(url, filename) {
  try {
    const res = await authFetch(url);
    const blobUrl = URL.createObjectURL(await res.blob());
    const a = document.createElement('a');
    a.href = blobUrl; a.download = filename;
    document.body.appendChild(a); a.click(); a.remove();
  } catch (_) {}
}

function authLink(event, url, downloadName) {
  if (!getAuth()) return true;
  event.preventDefault();
  if (downloadName) authDownload(url, downloadName); else authOpen(url);
  return false;
}
