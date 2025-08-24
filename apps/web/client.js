// apps/web/client.js
// Single‑page client for DivKit: interprets browser URL under /view/*,
// fetches corresponding JSON from backend (/home, /lesson/<id>?i=...),
// renders it with DivKit and handles in‑app navigation via action events.

(function () {
  const root = document.getElementById('root');
  let div = null; // DivKit instance created on first render

  // --------------------- prefetch cache (next step) ----------------------
  const CARD_CACHE_MAX = 8;
  const cardCache = new Map(); // key: API URL (/home, /lesson/2?i=1), value: JSON

  function fetchCardWithCache(apiPath) {
    if (cardCache.has(apiPath)) {
      // return a safe clone (avoid accidental mutations)
      return Promise.resolve(structuredClone(cardCache.get(apiPath)));
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
        return structuredClone(json);
      });
  }

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
      urls.forEach((src) => { try { const img = new Image(); img.src = src; } catch (_) {} });
    } catch (_) {}
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
    // /view/lesson/slug/my-lesson?i=1 -> { slug:"my-lesson", i:1 }
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
        cardCache.set(api, json);
        prewarmImagesFromCard(json);
      })
      .catch(() => {});
  }

  // ----------------------------- utils -----------------------------------
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

  // Extract action object from onAction/onStat payloads of different shapes
  function extractAction(obj) {
    if (!obj || typeof obj !== 'object') return null;
    if (obj.url || obj.href || obj.log_id || obj.payload) return obj; // already action-like
    if (obj.action) return extractAction(obj.action);
    if (obj.stat && obj.stat.action) return extractAction(obj.stat.action);
    if (obj.data && obj.data.action) return extractAction(obj.data.action);
    if (obj.event && obj.event.action) return extractAction(obj.event.action);
    return null;
  }

  // Convert anything action-like to a string URL if possible
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

    // semantic shortcuts
    if (url === '#go_home') return '/home';
    if (url === '#open_lesson') return '/lesson';

    if (!url.startsWith('/')) url = '/' + url;
    return url;
  }

  // --------------------------- routing layer ------------------------------
  // Map browser route (/view/...) to backend JSON endpoint
  function routeToApi(viewPath) {
    const qIndex = viewPath.indexOf('?');
    const pathname = qIndex >= 0 ? viewPath.slice(0, qIndex) : viewPath;
    const search = qIndex >= 0 ? viewPath.slice(qIndex) : '';

    if (pathname === '/' || pathname === '/view' || pathname === '/view/' || pathname === '/view/home') {
      return '/home';
    }

    // support short form: /view/<slug> -> /lesson/by/<slug>
    const mShort = pathname.match(/^\/view\/([a-z0-9-]+)\/?$/i);
    if (mShort) {
      return `/lesson/by/${encodeURIComponent(mShort[1])}${search}`;
    }

    const m = pathname.match(/^\/view\/lesson\/(\d+)\/?$/);
    if (m) {
      return `/lesson/${m[1]}${search}`;
    }
    const mSlug = pathname.match(/^\/view\/lesson\/slug\/([^\/]+)\/?$/);
    if (mSlug) {
      return `/lesson/by/${encodeURIComponent(mSlug[1])}${search}`;
    }
    const mBy = pathname.match(/^\/view\/lesson\/by\/([^\/]+)\/?$/);
    if (mBy) {
      return `/lesson/by/${encodeURIComponent(mBy[1])}${search}`;
    }

    if (pathname.startsWith('/view/')) {
      const tail = pathname.replace(/^\/view\//, '');
      return `/ui/pages/${tail}.json`;
    }

    // direct API path fallback (e.g. /home or /lesson/2?i=1)
    return viewPath;
  }

  async function fetchCard(viewPath) {
    const api = routeToApi(viewPath);
    const json = await fetchCardWithCache(api);
    render(json);

    // prefetch next step for lessons
    const nextView = nextViewUrl(viewPath);
    if (nextView) {
      preloadViewUrl(nextView);
    }
  }

  function render(json) {
    const DivKit = window.Ya && window.Ya.DivKit;
    if (!DivKit) {
      root.textContent = 'DivKit bundle не найден. Проверь подключение Ya.DivKit.';
      console.error('DivKit not found at window.Ya.DivKit');
      return;
    }

    if (!div) {
      div = DivKit.render({
        id: 'demo',
        target: root,
        json,
        onError: (e) => console.error('DivKit error:', e),
        onAction: handleAction,
        onStat: handleAction, // обратная совместимость
      });
    } else {
      div.setData(json);
    }
  }

  // ------------------------- navigation handlers --------------------------
  async function handleAction(evt) {
    try {
      const a = extractAction(evt) || evt?.action || evt;
      if (!a) return false;
      postLog(a);

      // semantic actions
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

      // url-based actions (support /lesson/.. and /home)
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
  }

  // ------------------------------ bootstrap -------------------------------
  const start = (location.pathname + (location.search || '')) || '/view/home';
  fetchCard(start);

  window.addEventListener('popstate', () => {
    fetchCard(location.pathname + (location.search || ''));
  });
})();