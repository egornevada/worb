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

  try {
    const res = await fetch('/lesson/1');
    if (!res.ok) throw new Error(`GET /lesson/1 -> ${res.status}`);
    const json = await res.json();

    if (!window.Ya || !window.Ya.DivKit) {
      console.error('DivKit not found at window.Ya.DivKit');
      root.textContent = 'DivKit bundle не загрузился — см. консоль';
      return;
    }

    window.Ya.DivKit.render({
      id: 'demo',
      target: root,
      json, // ожидает объект вида { card, templates }
      onError: (e) => console.error('DivKit error:', e),
      // ВАЖНО: все клики по action приходят сюда
      onStat: (details) => {
        if (details?.type === 'click' && details.action) {
          // details.action = то, что ты положил в JSON в поле "action"
          postLog(details.action);
        }
      },
    });
  } catch (e) {
    console.error('Load error:', e);
    root.textContent = 'чето не так, смотри консоль';
  }
})();