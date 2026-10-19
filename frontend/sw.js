// SmartFlow IDX — Service Worker for PWA Offline Caching
const CACHE_NAME = 'smartflow-idx-v69';
const ASSETS_TO_CACHE = [
  '/',
  '/static/styles.css',
  '/static/app.js',
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
  // Hanya tangani GET requests untuk asset static (jangan cache POST/DELETE API)
  if (event.request.method !== 'GET') return;

  const url = new URL(event.request.url);

  // Jika request ke /static/, root HTML, atau /manifest.json, gunakan network-first dengan cache fallback
  if (url.pathname.startsWith('/static/') || url.pathname === '/' || url.pathname === '/manifest.json') {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          if (response && response.status === 200) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
          }
          return response;
        })
        .catch(() => caches.match(event.request))
    );
  }
});
