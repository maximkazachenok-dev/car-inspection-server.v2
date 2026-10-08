// Пути относительные: приложение работает из любой папки (репозитория) на GitHub Pages
const CACHE_NAME = 'vehicle-inspection-v2';
const ASSETS = [
  './',
  './index.html',
  './manifest.json',
  './config.js',
  './icon-192.png',
  './icon-512.png',
];

self.addEventListener('install', e => {
  e.waitUntil(caches.open(CACHE_NAME).then(c => c.addAll(ASSETS)));
  self.skipWaiting();
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys().then(keys =>
    Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
  ));
  self.clients.claim();
});

self.addEventListener('fetch', e => {
  if (e.request.method !== 'GET') return;
  const url = new URL(e.request.url);
  // Запросы к серверу, Supabase и CDN, а также сайт-портал — без участия кэша приложения
  if (url.origin !== self.location.origin || url.pathname.includes('/portal/')) return;
  e.respondWith(
    fetch(e.request).catch(() => caches.match(e.request))
  );
});
