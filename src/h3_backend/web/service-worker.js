const CACHE_NAME = 'h3-shell-__CACHE_VERSION__';
const OFFLINE = '/ui/offline.html';
const STATIC_PATHS = new Set([
  OFFLINE, '/ui/app.css', '/manifest.webmanifest',
  '/ui/icon-192.png', '/ui/icon-512.png', '/ui/apple-touch-icon.png',
]);
const PAGE_PATHS = new Set(['/', '/index', '/roteiro']);

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll([OFFLINE, '/ui/app.css'])));
});

self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(
    keys.filter(key => key.startsWith('h3-shell-') && key !== CACHE_NAME)
      .map(key => caches.delete(key)),
  )));
});

self.addEventListener('fetch', event => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== 'GET' || url.origin !== self.location.origin) return;
  const navigation = request.mode === 'navigate' && PAGE_PATHS.has(url.pathname);
  if (!navigation && (url.search || !STATIC_PATHS.has(url.pathname))) return;
  event.respondWith((async () => {
    try {
      const response = await fetch(request, {cache: 'no-store'});
      if (!navigation && response.ok && !response.redirected) {
        await caches.open(CACHE_NAME)
          .then(cache => cache.put(request, response.clone())).catch(() => undefined);
      }
      return response;
    } catch {
      const cache = await caches.open(CACHE_NAME);
      const cached = await cache.match(navigation ? OFFLINE : request);
      if (navigation && cached) {
        return new Response(await cached.text(), {
          status: 503,
          headers: {'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store'},
        });
      }
      return cached || Response.error();
    }
  })());
});
