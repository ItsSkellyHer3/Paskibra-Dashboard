const CACHE_NAME = 'paskibra-v2-cache-v16';
const STATIC_ASSETS = [
  '/',
  '/offline',
  '/static/css/main.css?v=2.1.12',
  '/static/img/paskiblogo.jpg?v=2.1.12',
  '/manifest.json'
];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE_NAME).then(cache => cache.addAll(STATIC_ASSETS)));
  self.skipWaiting();
});

self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key)))));
  self.clients.claim();
});

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;

  if (event.request.mode === 'navigate') {
    event.respondWith(fetch(event.request).catch(() => caches.match(event.request) || caches.match('/offline')));
    return;
  }

  const url = new URL(event.request.url);
  if (url.origin !== self.location.origin) return;

  if (
    url.pathname.startsWith('/static/') ||
    url.pathname.startsWith('/media/avatar/') ||
    url.pathname === '/manifest.json'
  ) {
    event.respondWith((async () => {
      const cached = await caches.match(event.request);
      if (cached) return cached;
      const response = await fetch(event.request);
      if (response.ok) {
        const cache = await caches.open(CACHE_NAME);
        await cache.put(event.request, response.clone());
      }
      return response;
    })());
  }
});

// Push Event
self.addEventListener('push', event => {
  if (!event.data) return;
  let data;
  try { data = event.data.json(); }
  catch { data = { title: 'Paskibra', body: event.data.text() }; }
  const requestedUrl = data.data?.url || '/';
  let safeUrl = '/';
  try {
    const candidate = new URL(requestedUrl, self.location.origin);
    if (candidate.origin === self.location.origin) safeUrl = candidate.href;
  } catch {}
  const options = {
    body: data.body || '',
    icon: data.icon || '/static/img/paskiblogo.jpg',
    badge: '/static/img/paskiblogo.jpg',
    tag: data.tag || 'paskibra-notification',
    renotify: false,
    data: {
      url: safeUrl
    }
  };
  event.waitUntil(self.registration.showNotification(data.title || 'Paskibra', options));
});

// Notification Click Event
self.addEventListener('notificationclick', event => {
  event.notification.close();
  const urlToOpen = event.notification.data?.url || self.location.origin + '/';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(windowClients => {
      const target = new URL(urlToOpen, self.location.origin);
      for (let client of windowClients) {
        const openUrl = new URL(client.url);
        if (openUrl.origin === target.origin && openUrl.pathname === target.pathname && 'focus' in client) return client.focus();
      }
      if (clients.openWindow) return clients.openWindow(target.href);
    })
  );
});
