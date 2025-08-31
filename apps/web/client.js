// apps/web/client.js
// SPA client for DivKit: routes /view/* to backend JSON, renders via DivKit,
// supports state switching (SDK and JSON fallback), simple prefetch cache.

(function () {
  'use strict';

  // --- safe deep clone (Safari/old browsers may lack structuredClone) ---
  function deepClone(obj) {
    try {
      if (typeof structuredClone === 'function') return structuredClone(obj);
    } catch (_) {}
    try {
      return JSON.parse(JSON.stringify(obj));
    } catch (_) {
      // last resort: return as-is (mutations will be unsafe)
      return obj;
    }
  }

  const root = document.getElementById('root');
  let div = null;           // DivKit instance
  let currentJson = null;   // last rendered JSON (for fallback state change)

  // ----------------------------- small cache ------------------------------
  const CARD_CACHE_MAX = 8;
  const cardCache = new Map(); // key: API URL, value: JSON

  function prewarmImagesFromCard(cardJson) {
    try {
      const urls = [];
      (function walk(n) {
        if (!n || typeof n !== 'object') return;
        if (Array.isArray(n)) { n.forEach(walk); return; }
        if (n.type === 'image' && typeof n.image_url === 'string') {
          urls.push(n.image_url);
        }
        Object.values(n).forEach(walk);
      })(cardJson);
      urls.forEach((src) => { try { const i = new Image(); i.src = src; } catch (_) {} });
    } catch (_) {}
  }

  function fetchCardWithCache(apiPath) {
    if (cardCache.has(apiPath)) {
      return Promise.resolve(deepClone(cardCache.get(apiPath)));
    }
    return fetch(apiPath, { headers: { Accept: 'application/json' } })
      .then((res) => {
        if (!res.ok) throw new Error(`${apiPath} -> ${res.status}`);
        return res.json();
      })
      .then((json) => {
        if (cardCache.size >= CARD_CACHE_MAX) {
          const firstKey = cardCache.keys().next().value;
          cardCache.delete(firstKey);
        }
        cardCache.set(apiPath, json);
        prewarmImagesFromCard(json);
        return deepClone(json);
      });
  }

  function preloadViewUrl(viewPath) {
    const api = routeToApi(viewPath);
    if (cardCache.has(api)) return;
    fetch(api, { headers: { Accept: 'application/json' } })
      .then((res) => (res.ok ? res.json() : null))
      .then((json) => {
        if (!json) return;
        if (cardCache.size >= CARD_CACHE_MAX) {
          const firstKey = cardCache.keys().next().value;
          cardCache.delete(firstKey);
        }
        prewarmImagesFromCard(json);
        cardCache.set(api, deepClone(json));
      })
      .catch(() => {});
  }

  // ------------------------------- utils ----------------------------------
  function postLog(action) {
    try {
      fetch('/log', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          event: action?.log_id || 'click',
          payload: action?.payload || {},
          ts: Date.now(),
        }),
      }).catch(() => {});
    } catch (_) {}
  }

  function extractAction(obj) {
    if (!obj || typeof obj !== 'object') return null;
    if (obj.url || obj.href || obj.log_id || obj.payload || obj.set_state) return obj;
    if (obj.action) return extractAction(obj.action);
    if (obj.stat && obj.stat.action) return extractAction(obj.stat.action);
    if (obj.data && obj.data.action) return extractAction(obj.data.action);
    if (obj.event && obj.event.action) return extractAction(obj.event.action);
    return null;
  }

  function resolveUrlLike(obj) {
    const pick = (o) => {
      if (!o) return null;
      if (typeof o === 'string') return o;
      if (typeof o.url === 'string') return o.url;
      if (o.url && typeof o.url.url === 'string') return o.url.url;
      if (typeof o.href === 'string') return o.href;
      if (typeof o.path === 'string') return o.path;
      if (typeof o.route === 'string') return o.route;
      return null;
    };

    let url =
      pick(obj) ||
      pick(obj?.payload) ||
      pick(obj?.stat) ||
      pick(obj?.data) ||
      pick(obj?.event);

    if (!url) return null;
    url = String(url).trim();
    if (!url) return null;

    if (url === '#go_home') return '/home';
    if (url === '#open_lesson') return '/lesson';

    if (!url.startsWith('/')) url = '/' + url;
    return url;
  }

  // --------------------------- routing layer ------------------------------
  // Map /view/* to backend API endpoint
  function routeToApi(viewPath) {
    const qIndex = viewPath.indexOf('?');
    const pathname = qIndex >= 0 ? viewPath.slice(0, qIndex) : viewPath;
    const search = qIndex >= 0 ? viewPath.slice(qIndex) : '';

    // Home
    if (
      pathname === '/' ||
      pathname === '/view' ||
      pathname === '/view/' ||
      pathname === '/view/home'
    ) {
      return '/home' + (search || '');
    }

    // Lesson by numeric id
    let m = pathname.match(/^\/view\/lesson\/(\d+)\/?$/);
    if (m) {
      return `/lesson/${m[1]}${search}`;
    }

    // Lesson by slug
    const mSlug = pathname.match(/^\/view\/lesson\/slug\/([^\/]+)\/?$/);
    if (mSlug) {
      return `/lesson/by/${encodeURIComponent(mSlug[1])}${search}`;
    }
    const mBy = pathname.match(/^\/view\/lesson\/by\/([^\/]+)\/?$/);
    if (mBy) {
      return `/lesson/by/${encodeURIComponent(mBy[1])}${search}`;
    }

    // Explicit page alias: /view/page/<name> -> /page/<name>
    const mPage = pathname.match(/^\/view\/page\/([^\/]+)\/?$/);
    if (mPage) {
      return `/page/${encodeURIComponent(mPage[1])}${search}`;
    }

    // Generic: anything under /view/*
    if (pathname.startsWith('/view/')) {
      const tail = pathname.replace(/^\/view\//, '');
      // If user typed "/view/ui/pages/xxx.json" don't add ".json" again
      if (tail.startsWith('ui/')) {
        return `/${tail}${search}`;
      }
      // If tail already ends with .json, don't double-append
      if (tail.endsWith('.json')) {
        return `/ui/pages/${tail}${search}`;
      }
      // Normal case: "/view/test" -> "/ui/pages/test.json"
      return `/ui/pages/${tail}.json${search}`;
    }

    return viewPath; // direct API path
  }

  function parseViewLesson(viewPath) {
    // /view/lesson/2?i=1 -> { id:2, i:1 }
    const url = new URL(viewPath, location.origin);
    const m = url.pathname.match(/^\/view\/lesson\/(\d+)\/?$/);
    if (!m) return null;
    const id = Number(m[1]);
    const i = url.searchParams.has('i') ? Number(url.searchParams.get('i')) : 0;
    return { id, i };
  }

  function parseViewLessonSlug(viewPath) {
    const url = new URL(viewPath, location.origin);
    const m = url.pathname.match(/^\/view\/lesson\/slug\/([^\/]+)\/?$/);
    if (!m) return null;
    const slug = decodeURIComponent(m[1]);
    const i = url.searchParams.has('i') ? Number(url.searchParams.get('i')) : 0;
    return { slug, i };
  }

  function nextViewUrl(viewPath) {
    const pId = parseViewLesson(viewPath);
    if (pId) {
      const nextI = (pId.i ?? 0) + 1;
      return `/view/lesson/${pId.id}?i=${nextI}`;
    }
    const pSlug = parseViewLessonSlug(viewPath);
    if (pSlug) {
      const nextI = (pSlug.i ?? 0) + 1;
      return `/view/lesson/slug/${encodeURIComponent(pSlug.slug)}?i=${nextI}`;
    }
    return null;
  }

  // Helper: detect home routes for graceful fallback
  function isHomeView(viewPath) {
    const qIndex = viewPath.indexOf('?');
    const pathname = qIndex >= 0 ? viewPath.slice(0, qIndex) : viewPath;
    return (
      pathname === '/' ||
      pathname === '/view' ||
      pathname === '/view/' ||
      pathname === '/view/home'
    );
  }

  async function fetchCard(viewPath) {
    const api = routeToApi(viewPath);
    try {
      const json = await fetchCardWithCache(api);
      render(json);
    } catch (e) {
      console.error('fetchCard failed for', api, e);
      // If API /home not available, try static UI page as a graceful fallback
      if (isHomeView(viewPath)) {
        try {
          const json = await fetchCardWithCache('/ui/pages/home.json');
          render(json);
          return;
        } catch (e2) {
          console.error('home.json fallback failed', e2);
        }
      }
      // Last resort: show a small placeholder instead of a blank screen
      render({
        card: {
          log_id: 'error',
          states: [{
            state_id: 0,
            div: {
              type: 'text',
              text: 'Не удалось загрузить страницу',
              width: { type: 'match_parent' },
              margins: { top: 24, left: 16, right: 16 }
            }
          }]
        }
      });
      return;
    }
  
    // prefetch next step for lessons
    const nextView = nextViewUrl(viewPath);
    if (nextView) preloadViewUrl(nextView);
  }

  function render(json) {
    currentJson = json;
    const DivKit = window.Ya && window.Ya.DivKit;
    const mount = root || document.getElementById('root');
    if (!DivKit || !mount) {
      if (mount) {
        mount.textContent = 'DivKit bundle не найден. Проверь подключение Ya.DivKit.';
      } else {
        console.error('Mount element #root not found');
      }
      if (!DivKit) console.error('DivKit not found at window.Ya.DivKit');
      return;
    }

    if (!div) {
      div = DivKit.render({
        id: 'demo',
        target: mount,
        json,
        onError: (e) => console.error('DivKit error:', e),
        onAction: handleAction,
        onStat: handleAction,
      });
    } else {
      div.setData(json);
    }
  }

  // ---- fallback: switch state by mutating JSON when SDK setState is unavailable
  function setStateInJson(targetId, stateId) {
    try {
      if (!currentJson) return false;
      const clone = deepClone(currentJson);
      let found = false;
      (function walk(n) {
        if (!n || typeof n !== 'object') return;
        if (Array.isArray(n)) { n.forEach(walk); return; }
        if (n.type === 'state' && (n.id === targetId || (!n.id && targetId === 'lesson_card_state'))) {
          n.state_id = stateId;
          n._rev = (n._rev || 0) + 1; // provoke rerender
          found = true;
          return;
        }
        Object.values(n).forEach(walk);
      })(clone);
      if (!found) return false;
      currentJson = clone;
      if (div && typeof div.setData === 'function') {
        div.setData(clone);
      }
      return true;
    } catch (_) {
      return false;
    }
  }

  function applyStateChange(targetId, next) {
    // try several SDK signatures, fall back to JSON mutation
    try {
      if (div && typeof div.setState === 'function') {
        try { div.setState({ id: targetId, state_id: next }); return true; } catch (_) {}
        try { div.setState({ id: targetId, stateId: next });  return true; } catch (_) {}
        try { div.setState(targetId, next);                   return true; } catch (_) {}
      }
    } catch (_) {}
    return setStateInJson(targetId, next);
  }

  // ------------------------- navigation & actions -------------------------
  async function handleAction(evt) {
    try {
      const a = extractAction(evt) || evt?.action || evt;
      if (!a) return false;
      postLog(a);

      // 1) generic state change (supports both a.set_state and a.payload.set_state)
      const maybeSet = a.set_state || a?.payload?.set_state;
      if (maybeSet && typeof maybeSet === 'object') {
        const targetId = maybeSet.id || maybeSet.component_id || 'lesson_card_state';
        const next = maybeSet.state_id ?? maybeSet.stateId ?? maybeSet.state ?? 'brand';
        applyStateChange(targetId, next);
        return true;
      }

      // 2) legacy custom action by log_id
      if (a.log_id === 'lesson_card_set_state') {
        const targetId = a?.payload?.id || 'lesson_card_state';
        const next = a?.payload?.state_id ?? a?.payload?.stateId ?? 'brand';
        applyStateChange(targetId, next);
        return true;
      }

      // 3) semantic navigation
      if (a.log_id === 'go_home') {
        await go('/view/home');
        return true;
      }
      if (a.log_id === 'open_lesson') {
        const id = a?.payload?.lesson_id || a?.payload?.id;
        const slug = a?.payload?.lesson_slug || a?.payload?.slug;
        if (id != null) {
          await go(`/view/lesson/${id}?i=0`);
          return true;
        }
        if (slug) {
          await go(`/view/lesson/slug/${encodeURIComponent(slug)}?i=0`);
          return true;
        }
      }

      // 4) url-based navigation
      const url = resolveUrlLike(a) || resolveUrlLike(a?.payload);
      if (url) {
        let viewUrl = url;
        // fallback: treat a bare "/<slug>" as a lesson slug
        if (
          /^\/[a-z0-9-]+(\?.*)?$/i.test(url) &&
          !url.startsWith('/lesson') &&
          !url.startsWith('/home') &&
          !url.startsWith('/ui/') &&
          !url.startsWith('/view/')
        ) {
          const q = url.indexOf('?');
          const slug = url.slice(1, q >= 0 ? q : undefined);
          const search = q >= 0 ? url.slice(q) : '';
          viewUrl = `/view/lesson/slug/${encodeURIComponent(slug)}${search}`;
          await go(viewUrl);
          return true;
        }
        if (url.startsWith('/lesson/by/')) {
          const q = url.indexOf('?');
          const slug = url.slice('/lesson/by/'.length, q >= 0 ? q : undefined);
          const search = q >= 0 ? url.slice(q) : '';
          viewUrl = `/view/lesson/slug/${encodeURIComponent(slug)}${search}`;
        } else if (url.startsWith('/lesson')) {
          viewUrl = '/view' + url;
        } else if (url === '/home') {
          viewUrl = '/view/home';
        }
        await go(viewUrl);
        return true;
      }
    } catch (e) {
      console.error('handleAction error:', e);
    }
    return false;
  }

  async function go(viewUrl) {
    history.pushState({}, '', viewUrl);

    // optional: clear cache if navigating away from lessons to keep memory small
    const isLesson = /^\/view\/lesson\/(\d+|slug\/.+)/.test(viewUrl);
    if (!isLesson) cardCache.clear();

    await fetchCard(viewUrl);

    // ensure we start at the top after navigation
    try { window.requestAnimationFrame(() => window.scrollTo(0, 0)); } catch (_) { window.scrollTo(0, 0); }
  }

  // ------------------------------ bootstrap -------------------------------
  function boot() {
    const start = (location.pathname + (location.search || '')) || '/view/home';
    fetchCard(start);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot, { once: true });
  } else {
    boot();
  }

  window.addEventListener('popstate', () => {
    fetchCard(location.pathname + (location.search || ''));
  });
})();