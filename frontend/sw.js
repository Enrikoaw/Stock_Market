// SmartFlow IDX — Service Worker for PWA Offline Caching
const CACHE_NAME = 'smartflow-idx-v76';
const ASSETS_TO_CACHE = [
  '/static/styles.css?v=76.0',
  '/static/app.js?v=76.0',
  '/manifest.json',
  '/static/icons/icon.svg',
  '/static/icons/icon-192.svg',
  '/static/icons/icon-512.svg'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return Promise.allSettled(
        ASSETS_TO_CACHE.map((assetUrl) =>
          cache.add(assetUrl).catch((err) => {
            console.warn('[SW] Failed to cache asset:', assetUrl, err);
          })
        )
      );
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.map((key) => {
          if (key !== CACHE_NAME) {
            return caches.delete(key);
          }
        })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  // Hanya tangani GET requests
  if (event.request.method !== 'GET') return;

  const url = new URL(event.request.url);

  // Jangan sentuh API sama sekali (biarkan selalu live ke backend)
  if (url.pathname.startsWith('/api/')) return;

  // Navigasi halaman root HTML: Selalu Network-First dengan anti-cache header
  if (event.request.mode === 'navigate' || url.pathname === '/') {
    event.respondWith(
      fetch(event.request, { cache: 'no-cache' })
        .then((response) => {
          if (response && response.status === 200) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
          }
          return response;
        })
        .catch(async () => {
          return (
            (await caches.match(event.request)) ||
            (await caches.match('/')) ||
            new Response('Offline - Koneksi terputus', {
              status: 503,
              statusText: 'Offline',
              headers: { 'Content-Type': 'text/plain; charset=utf-8' },
            })
          );
        })
    );
    return;
  }

  // Asset static (styles, script, icons): Network-first dengan fallback cache offline
  if (url.pathname.startsWith('/static/') || url.pathname === '/manifest.json') {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          if (response && response.status === 200) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
          }
          return response;
        })
        .catch(async () => {
          return (
            (await caches.match(event.request)) ||
            (await caches.match(url.pathname)) ||
            new Response('Offline', { status: 503, statusText: 'Offline' })
          );
        })
    );
  }
});
