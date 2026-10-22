// SmartFlow IDX — Service Worker for PWA Offline Caching
const CACHE_NAME = 'smartflow-idx-v94.5';
const ASSETS_TO_CACHE = [
  '/static/styles.css?v=94.5',
  '/static/app.js?v=94.5',
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

// Web Push: tampilkan notifikasi di bar notifikasi HP (meski aplikasi/browser tertutup)
self.addEventListener('push', (event) => {
  let data = { title: 'SmartFlow IDX', body: '', url: '/' };
  try {
    if (event.data) data = Object.assign(data, event.data.json());
  } catch (_) {
    if (event.data) data.body = event.data.text();
  }
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: '/static/icons/icon-192.svg',
      badge: '/static/icons/icon-192.svg',
      data: { url: data.url || '/' },
      vibrate: [200, 100, 200],
    })
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const target = (event.notification.data && event.notification.data.url) || '/';
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then((list) => {
      for (const c of list) {
        if ('focus' in c) return c.focus();
      }
      return self.clients.openWindow(target.startsWith('http') ? target : '/');
    })
  );
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
