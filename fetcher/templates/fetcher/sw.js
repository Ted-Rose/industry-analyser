{% load static %}// Service worker for the Industry Analyser PWA.
// Rendered by Django so the cache version stays in sync with the
// PWA_CACHE_VERSION constant in fetcher/views.py.
const CACHE_NAME = 'industry-analyser-{{ cache_version }}';
const PRECACHE_URLS = ['/'];
const STATIC_URL = '{% get_static_prefix %}';

// Paths the worker must never serve from cache — auth flows and, most
// importantly, /api/ JSON (a stale API response would silently corrupt
// SPA state).
const BYPASS_PATHS = ['/admin', '/api'];

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(PRECACHE_URLS))
    );
    self.skipWaiting();
});

self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys =>
            Promise.all(
                keys.filter(k =>
                    k.startsWith('industry-analyser-') &&
                    k !== CACHE_NAME
                ).map(k => caches.delete(k))
            )
        )
    );
    self.clients.claim();
});

self.addEventListener('fetch', event => {
    const req = event.request;

    // Only handle same-origin GET requests.
    if (req.method !== 'GET') return;
    const url = new URL(req.url);
    if (url.origin !== self.location.origin) return;
    if (BYPASS_PATHS.some(p => url.pathname.startsWith(p))) return;

    // Navigations: network-first so pages always render fresh data
    // (e.g. after a POST-redirect-GET). Cache the response for
    // offline use; fall back to the cached copy, then '/'.
    if (req.mode === 'navigate') {
        event.respondWith(
            fetch(req)
                .then(res => {
                    // Navigation requests use redirect mode 'manual',
                    // so a redirecting response (session expiry →
                    // login, APPEND_SLASH) surfaces as
                    // 'opaqueredirect' (status 0, possibly no URL).
                    // Hand it back untouched — the browser follows it
                    // as a new navigation that re-enters this handler
                    // at the final URL.
                    if (res.type === 'opaqueredirect') {
                        return res;
                    }
                    // Don't cache failures or pages that ended on a
                    // bypassed path. Cache under the final URL when
                    // fetch() followed redirects internally.
                    const finalPath =
                        new URL(res.url || req.url).pathname;
                    if (
                        res.ok &&
                        !BYPASS_PATHS.some(p => finalPath.startsWith(p))
                    ) {
                        const copy = res.clone();
                        const key = res.url || req;
                        caches.open(CACHE_NAME).then(
                            c => c.put(key, copy)
                        );
                    }
                    return res;
                })
                .catch(() =>
                    caches.match(req).then(
                        cached => cached || caches.match('/')
                    )
                )
        );
        return;
    }

    // Static assets: stale-while-revalidate.
    if (url.pathname.startsWith(STATIC_URL)) {
        event.respondWith(
            caches.match(req).then(cached => {
                const fetching = fetch(req).then(res => {
                    const copy = res.clone();
                    caches.open(CACHE_NAME).then(c => c.put(req, copy));
                    return res;
                }).catch(() => cached);
                return cached || fetching;
            })
        );
    }
});
