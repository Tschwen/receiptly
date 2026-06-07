// Service worker: serves the cached app shell so the app can start without a
// network navigation — which would trigger a reverse proxy's native Basic-Auth
// popup in standalone/home-screen mode. The cache is filled by the page
// (auth.js, refreshShellCache) after each successful boot; the worker itself
// never handles credentials. API and file requests pass straight through to
// the network, where the page attaches the Authorization header itself.
const CACHE = 'receiptly-shell-v1';

self.addEventListener('install', () => self.skipWaiting());

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  const isShell = req.mode === 'navigate'
    || url.pathname.startsWith('/i18n/')
    || url.pathname === '/auth.js';
  if (!isShell) return; // APIs, PDFs, ZIPs: network only
  e.respondWith(
    caches.open(CACHE)
      .then((c) => c.match(req, { ignoreSearch: true }))
      .then((hit) => hit || fetch(req))
  );
});
