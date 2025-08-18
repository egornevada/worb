// apps/web/client.js
// Загружаем DivKit-карту и рендерим через глобальный API window.Ya.DivKit.render.
// Клики по элементам с "action" ловим в onStat и отправляем POST на бэкенд.

(async function () {
  const root = document.getElementById('root');

  function postLog(action) {
    // action: { log_id?, payload? }
    fetch('/log', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        event: action?.log_id || 'click',
        payload: action?.payload || {},
        ts: Date.now(),
      }),
    }).catch((err) => console.error('POST /log failed:', err));
  }

  // Пытаемся достать action из разных форматов onStat
  function extractAction(obj) {
    if (!obj || typeof obj !== 'object') return null;
    if (obj.url || obj.log_id || obj.payload) return obj;
    if (obj.action) return extractAction(obj.action);
    if (obj.stat && obj.stat.action) return extractAction(obj.stat.action);
    if (obj.data && obj.data.action) return extractAction(obj.data.action);
    if (obj.event && obj.event.action) return extractAction(obj.event.action);
    return null;
  }
  // Унифицируем вытягивание URL из разных форматов action (строка или объект)
  function resolveUrl(a) {
    if (!a) return null;

    let url = null;
    // 1) Строка: "/lesson/1" или "lesson/1" или "#open_lesson"
    if (typeof a.url === 'string') url = a.url;
    // 2) Объект DivKit LinkAction: { url: "/lesson/1" }
    else if (a.url && typeof a.url.url === 'string') url = a.url.url;
    // 3) Иногда встречается `href`
    else if (typeof a.href === 'string') url = a.href;

    // Если URL так и не нашли, но есть семантика
    if (!url && a.log_id === 'open_lesson') url = '/lesson';

    if (!url) return null;

    url = url.trim();
    if (!url.startsWith('/')) url = '/' + url; // поддерживаем 'lesson/1'

    // Алиасы из песочницы/шаблонов
    if (url === '#go_home') url = '/home';
    if (url === '#open_lesson') url = '/lesson';

    return url;
  }

  // Загружает JSON со стороны бэка и перерисовывает DivKit
  async function load(path) {
    const res = await fetch(path);
    if (!res.ok) throw new Error(`GET ${path} -> ${res.status}`);
    const json = await res.json();

    // очищаем контейнер перед новым рендером
    root.innerHTML = '';

    renderJson(json);
  }

  // Один общий рендер с подпиской на клики
  function renderJson(json) {
    window.Ya.DivKit.render({
      id: 'demo',
      target: root,
      json,
      onError: (e) => console.error('DivKit error:', e),
      // Навигация и логирование по action (надёжнее, чем ловить это через onStat)
      onAction: (a) => {
        try {
          if (!a) return;
          // лог
          postLog(a);

          // Прямой обработчик возврата на главную по семантике
          if (a && a.log_id === 'go_home') {
            load('/home');
            return;
          }

          // Нормализуем url, если он есть
          const nav = resolveUrl(a);
          if (nav) {
            console.debug('navigate(onAction):', nav, a.payload || {});
            if (nav === '/home') {
              load('/home');
              return;
            }
            if (nav === '/lesson' || nav.startsWith('/lesson/')) {
              const id =
                (a.payload && (a.payload.lesson_id || a.payload.id)) ||
                nav.split('/')[2] ||
                '1';
              load(`/lesson/${id}`);
              return;
            }
          }

          // Вариант навигации по log_id без url
          if (a.log_id === 'open_lesson') {
            const id = (a.payload && (a.payload.lesson_id || a.payload.id)) || '1';
            load(`/lesson/${id}`);
          }
        } catch (err) {
          console.error('onAction handler error:', err);
        }
      },
      // Аналитика (оставляем для дебага), навигацию делает onAction
      onStat: (details) => {
        try {
          // Смотрим, что реально прилетает
          console.debug('DivKit onStat:', details);

          // Универсально извлекаем action (поддержка разных форматов DivKit)
          const a = extractAction(details);
          if (!a) return; // чужие события игнорим

          postLog(a);

          // Прямой обработчик возврата на главную по семантике
          if (a && a.log_id === 'go_home') {
            load('/home');
            return;
          }

          // 1) Явная навигация по URL (терпим разные формы)
          const nav = resolveUrl(a);
          if (nav) {
            console.debug('navigate(onStat):', nav, a.payload || {});
            if (nav === '/home') {
              load('/home');
              return;
            }
            if (nav === '/lesson' || nav.startsWith('/lesson/')) {
              const id =
                (a.payload && (a.payload.lesson_id || a.payload.id)) ||
                nav.split('/')[2] ||
                '1';
              load(`/lesson/${id}`);
              return;
            }
          }

          // 2) Семантический вариант
          if (a.log_id === 'open_lesson') {
            const id = (a.payload && (a.payload.lesson_id || a.payload.id)) || '1';
            load(`/lesson/${id}`);
            return;
          }
        } catch (err) {
          console.error('onStat handler error:', err);
        }
      },
    });
  }

  try {
    if (!window.Ya || !window.Ya.DivKit) {
      console.error('DivKit not found at window.Ya.DivKit');
      root.textContent = 'DivKit bundle не загрузился — см. консоль';
      return;
    }

    // Стартуем с загрузки первой страницы (домашней/урока)
    try {
      await load('/home');
    } catch (e2) {
      console.warn('GET /home failed, fallback to /lesson/1:', e2);
      await load('/lesson/1');
    }
  } catch (e) {
    console.error('Load error:', e);
    root.textContent = 'чето не так, смотри консоль';
  }
})();