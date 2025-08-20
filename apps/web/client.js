// apps/web/client.js
// Single‑page client for DivKit: interprets browser URL under /view/*,
// fetches corresponding JSON from backend (/home, /lesson/<id>?i=...),
// renders it with DivKit and handles in‑app navigation via action events.

(function () {
  const root = document.getElementById('root');
  let div = null; // DivKit instance created on first render

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

    const m = pathname.match(/^\/view\/lesson\/(\d+)$/);
    if (m) {
      return `/lesson/${m[1]}${search}`;
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
    const res = await fetch(api, { headers: { Accept: 'application/json' } });
    if (!res.ok) throw new Error(`${api} -> ${res.status}`);
    const json = await res.json();
    render(json);
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
        if (id) {
          await go(`/view/lesson/${id}`);
          return true;
        }
      }

      // url-based actions (support /lesson/.. and /home)
      const url = resolveUrlLike(a) || resolveUrlLike(a?.payload);
      if (url) {
        let viewUrl = url;
        if (url.startsWith('/lesson')) viewUrl = '/view' + url;
        if (url === '/home') viewUrl = '/view/home';
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
    await fetchCard(viewUrl);
  }

  // ------------------------------ bootstrap -------------------------------
  const start = (location.pathname + (location.search || '')) || '/view/home';
  fetchCard(start);

  window.addEventListener('popstate', () => {
    fetchCard(location.pathname + (location.search || ''));
  });
})();