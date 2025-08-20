from pathlib import Path
import json
import os
import random
from typing import Any, Dict, Optional
from flask import Flask, request, jsonify, send_from_directory

# Strapi helpers
from strapi_client import (
    get_lesson as fetch_lesson,
    get_lesson_by_slug,
    to_divkit_lesson,
)

APP_FILE = Path(__file__).resolve()
WEB_DIR  = APP_FILE.parent.parent / "web"
UI_DIR   = WEB_DIR / "ui"

app = Flask(__name__)

# ---------- Static (index + client.js) ----------
@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")

@app.get("/client.js")
def client_js():
    return send_from_directory(WEB_DIR, "client.js", mimetype="application/javascript")

# Чтобы по «прямой» ссылке тоже открывалась страница (а не JSON),
# добавляем вью-маршрут, который отдаёт index.html.
@app.get("/view/lesson/<int:lesson_id>")
def view_lesson(lesson_id: int):
    # JS прочитает путь и запросит JSON /lesson/<id>?i=0
    return send_from_directory(WEB_DIR, "index.html")

# SPA deep-link support: отдаём index.html для любых путей под /view/*
@app.get("/view")
@app.get("/view/")
@app.get("/view/home")
@app.get("/view/<path:subpath>")
def view_entry(subpath: str = ""):
    # Любой адрес вида /view/... открывает SPA,
    # клиентский JS сам подгрузит соответствующий JSON (/home, /lesson/<id>?i=...)
    return send_from_directory(WEB_DIR, "index.html")

# Раздача ассетов из ui/
@app.get("/ui/<path:filename>")
def ui_static(filename: str):
    return send_from_directory(UI_DIR, filename)

# ---------- Include resolver ----------
def _resolve_includes(node: Any, *, base_dir: Optional[Path] = None) -> Any:
    if base_dir is None:
        base_dir = UI_DIR

    if isinstance(node, dict):
        if "$include" in node and isinstance(node["$include"], str):
            inc_str = node["$include"].lstrip("/")
            if inc_str.startswith(("components/", "pages/")):
                inc_path = (UI_DIR / inc_str).resolve()
            else:
                inc_path = (base_dir / inc_str).resolve()

            # без выхода за пределы UI_DIR
            try:
                inside = inc_path.is_relative_to(UI_DIR)  # py3.9+
            except AttributeError:
                inside = str(inc_path).startswith(str(UI_DIR))
            if not inside:
                raise ValueError(f"$include escapes UI dir: {inc_path}")

            with open(inc_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            return _resolve_includes(loaded, base_dir=inc_path.parent)

        # обычный словарь — обходим рекурсивно
        return {k: _resolve_includes(v, base_dir=base_dir) for k, v in node.items()}

    if isinstance(node, list):
        return [_resolve_includes(x, base_dir=base_dir) for x in node]

    return node

# ---------- JSON patch by id ----------
def _patch_by_id(tree: Any, target_id: str, updates: Dict[str, Any]) -> None:
    """
    Находит узел вида {"id": "<target_id>", ...} и применяет updates.
    Спец-обработка ключа 'action': если updates['action'] is None — удаляем action.
    """
    if isinstance(tree, dict):
        if tree.get("id") == target_id:
            for k, v in updates.items():
                if k == "action" and v is None:
                    tree.pop("action", None)
                else:
                    tree[k] = v
        # рекурсивно обходим словарь
        for v in list(tree.values()):
            _patch_by_id(v, target_id, updates)
    elif isinstance(tree, list):
        for item in tree:
            _patch_by_id(item, target_id, updates)

# ---------- API ----------
@app.get("/lesson/<int:lesson_id>")
def get_lesson(lesson_id: int):
    """
    Отдаём страницу урока на базе шаблона /ui/pages/lesson.json с подстановкой данных:
      - query param `i` — индекс слова (0..N-1), по умолчанию 0.
      - правильный ответ (translation) ведёт на следующее слово,
        неверный (distractor1) — без действия.
      - на последнем слове переход ведёт на /view/home.
    Фолбэк: если Strapi/данные недоступны — отдаём статический lesson.json как есть.
    """
    step = request.args.get("i", default=0, type=int)

    # 1) Загружаем шаблон и разворачиваем include'ы
    template_path = UI_DIR / "pages" / "lesson.json"
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            card = json.load(f)
        card = _resolve_includes(card)
    except Exception as e:
        print("Template load error:", e)
        # если вообще не удалось — отправим home
        with open(UI_DIR / "pages" / "home.json", "r", encoding="utf-8") as f:
            home = json.load(f)
        return jsonify(_resolve_includes(home))

    # 2) Пробуем достать данные урока из Strapi
    try:
        raw        = fetch_lesson(lesson_id)
        simplified = to_divkit_lesson(raw)
        words      = simplified.get("words", [])
    except Exception as e:
        print("Strapi fetch failed:", e)
        words = []

    if not words:
        # Нет данных — отдаём шаблон как есть (плейсхолдеры)
        return jsonify(card)

    # Корректный индекс шага
    if step < 0: step = 0
    if step >= len(words):  # все прошли — отправим на home
        with open(UI_DIR / "pages" / "home.json", "r", encoding="utf-8") as f:
            home = json.load(f)
        return jsonify(_resolve_includes(home))

    w = words[step] or {}
    term      = (w.get("term") or "").strip()
    image_url = (w.get("image_url") or "").strip()
    if image_url.startswith("/"):
        base = os.getenv("STRAPI_URL", "http://localhost:1337").rstrip("/")
        image_url = f"{base}{image_url}"

    correct = (w.get("translation") or "").strip()
    wrong   = (w.get("distractor1") or "").strip()

    # Следующий шаг
    is_last  = (step + 1 >= len(words))
    next_url = "/view/home" if is_last else f"/view/lesson/{lesson_id}?i={step + 1}"

    # Случайно кладём правильный влево/вправо
    if random.random() < 0.5:
        left_text, right_text = correct, wrong
        left_url,  right_url  = next_url, None
    else:
        left_text, right_text = wrong, correct
        left_url,  right_url  = None, next_url

    # 3) Патчим якоря в карточке
    # Эти id должны быть в ui/components/*
    _patch_by_id(card, "word_term",  {"text": term})
    _patch_by_id(card, "word_image", {"image_url": image_url or "https://dummyimage.com/220x220/eeeeee/aaaaaa.png&text=img"})

    # Тексты на кнопках живут на текстовых узлах
    _patch_by_id(card, "choice_left_text",  {"text": left_text})
    _patch_by_id(card, "choice_right_text", {"text": right_text})

    # А кликабельность/переход — на контейнерах-кнопках
    left_updates  = {"action": {"log_id": "next_word", "url": left_url} if left_url else None}
    right_updates = {"action": {"log_id": "next_word", "url": right_url} if right_url else None}
    _patch_by_id(card, "choice_left",  left_updates)
    _patch_by_id(card, "choice_right", right_updates)

    return jsonify(card)

@app.get("/home")
def get_home():
    page_path = UI_DIR / "pages" / "home.json"
    with open(page_path, "r", encoding="utf-8") as f:
        card = json.load(f)
    card = _resolve_includes(card)
    return jsonify(card)

@app.post("/log")
def log_action_post():
    data = request.get_json(silent=True) or {}
    print(">> DivKit action (POST):", data)
    return {"ok": True}

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5050, use_reloader=False)