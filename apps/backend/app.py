from pathlib import Path
import json
import os
import random
from typing import Any, Dict, List, Optional
from flask import Flask, request, jsonify, send_from_directory, abort

import re

# ---------------- Strapi helpers ----------------
# ВАЖНО: имена импорта совпадают с текущими в проекте
from strapi_client import (
    get_lesson as fetch_lesson,
    get_lesson_by_slug,
    to_divkit_lesson,
    get_categories,  # для вкладок на /home
)

# ---------------- Paths ----------------
APP_FILE = Path(__file__).resolve()
WEB_DIR  = APP_FILE.parent.parent / "web"
UI_DIR   = WEB_DIR / "ui"

app = Flask(__name__)

# ---------------- Static (index + client.js) ----------------
@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")

@app.get("/client.js")
def client_js():
    return send_from_directory(WEB_DIR, "client.js", mimetype="application/javascript")

# Раздача ассетов из ui/
@app.get("/ui/<path:filename>")
def ui_static(filename: str):
    return send_from_directory(UI_DIR, filename)

# SPA deep-link support: любые пути под /view/* возвращают shell (index.html)
@app.get("/view")
@app.get("/view/")
@app.get("/view/<path:subpath>")
def view_entry(subpath: str = ""):
    return send_from_directory(WEB_DIR, "index.html")

# Специально для /view/lesson/<id>
@app.get("/view/lesson/<int:lesson_id>")
def view_lesson(lesson_id: int):  # noqa: ARG001
    return send_from_directory(WEB_DIR, "index.html")

@app.get("/view/lesson/slug/<string:slug>")
def view_lesson_slug(slug: str):  # noqa: ARG001
    return send_from_directory(WEB_DIR, "index.html")

# ---------------- Include resolver ----------------

def _resolve_includes(node: Any, *, base_dir: Optional[Path] = None) -> Any:
    """
    Разворачивает {"$include": "components/xxx.json"}.
    Пути без "/" трактуются относительно base_dir, с "components/" или "pages/" — от корня UI_DIR.
    Не даём выйти за пределы UI_DIR.
    """
    if base_dir is None:
        base_dir = UI_DIR

    if isinstance(node, dict):
        if "$include" in node and isinstance(node["$include"], str):
            inc_str = node["$include"].lstrip("/")
            if inc_str.startswith(("components/", "pages/")):
                inc_path = (UI_DIR / inc_str).resolve()
            else:
                inc_path = (base_dir / inc_str).resolve()

            # безопасность: не выходим за пределы UI_DIR
            try:
                inside = inc_path.is_relative_to(UI_DIR)  # py3.9+
            except AttributeError:
                inside = str(inc_path).startswith(str(UI_DIR))
            if not inside:
                raise ValueError(f"$include path escapes UI dir: {inc_path}")

            with open(inc_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            return _resolve_includes(loaded, base_dir=inc_path.parent)

        return {k: _resolve_includes(v, base_dir=base_dir) for k, v in node.items()}

    if isinstance(node, list):
        return [_resolve_includes(x, base_dir=base_dir) for x in node]

    return node

# ---------------- JSON patch by id ----------------

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
        for v in list(tree.values()):
            _patch_by_id(v, target_id, updates)
    elif isinstance(tree, list):
        for item in tree:
            _patch_by_id(item, target_id, updates)

# ---------------- Design tokens (colors) ----------------
TOKENS_CACHE: Dict[str, Any] = {}

def _deep_get(d: Dict[str, Any], dotted: str, default: Any = None) -> Any:
    cur: Any = d
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur

def _load_tokens(theme: str = "light") -> Dict[str, Any]:
    """
    Loads tokens from web/ui/tokens/colors.<theme>.json.
    If file is missing or invalid, returns {} (no fallback palette hardcoded here).
    """
    key = f"colors.{theme}"
    if key in TOKENS_CACHE:
        return TOKENS_CACHE[key]

    tokens_path = UI_DIR / "tokens" / f"colors.{theme}.json"
    try:
        with open(tokens_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        # Keep silent but trace to console for debugging; return empty mapping.
        print(f"Tokens load failed: {tokens_path} -> {e}")
        data = {}

    TOKENS_CACHE[key] = data
    return data

def _apply_design_tokens(node: Any, tokens: Dict[str, Any]) -> Any:
    """
    Recursively replaces string values like '@color.page_bg' with token values
    from provided tokens mapping. Unknown tokens are left as-is.
    """
    if isinstance(node, dict):
        out = {}
        for k, v in node.items():
            out[k] = _apply_design_tokens(v, tokens)
        return out
    if isinstance(node, list):
        return [_apply_design_tokens(x, tokens) for x in node]
    if isinstance(node, str) and node.startswith("@"):
        # strip leading '@' and resolve as dotted path, e.g. 'color.background'
        resolved = _deep_get(tokens, node[1:], None)
        return resolved if resolved is not None else node
    return node

# ---------------- Helpers for tabs ----------------

def _attrs(n: Any) -> Dict[str, Any]:
    """Унификация attributes для Strapi v4/v5."""
    if not isinstance(n, dict):
        return {}
    if "data" in n and isinstance(n["data"], dict):
        return n["data"].get("attributes") or {}
    return n.get("attributes") or n



def _replace_node_by_id(node: Any, node_id: str, replacement: Dict[str, Any]) -> bool:
    """Заменить первый узел с {"id": node_id} на replacement. Возвращает True/False."""
    if isinstance(node, dict):
        if node.get("id") == node_id:
            node.clear()
            node.update(replacement)
            return True
        for k, v in list(node.items()):
            if _replace_node_by_id(v, node_id, replacement):
                return True
    elif isinstance(node, list):
        for i, item in enumerate(list(node)):
            if isinstance(item, dict) and item.get("id") == node_id:
                node[i] = replacement
                return True
            if _replace_node_by_id(item, node_id, replacement):
                return True
    return False

# --- Utilities --------------------------------------------------------------

def _extract_id_from_strapi_response(raw: Any) -> Optional[int]:
    """Try to pull numeric lesson id from various Strapi response shapes.
    Returns int id or None if not found.
    Supported shapes:
      {"data": {"id": 7, ...}}
      {"data": [{"id": 7, ...}, ...]}
      {"data": [{"data": {"id": 7, ...}}]}
    """
    try:
        if isinstance(raw, dict):
            d = raw.get("data")
            if isinstance(d, dict):
                _id = d.get("id")
                if isinstance(_id, int):
                    return _id
            if isinstance(d, list) and d:
                first = d[0]
                if isinstance(first, dict):
                    _id = first.get("id")
                    if isinstance(_id, int):
                        return _id
                    inner = first.get("data")
                    if isinstance(inner, dict):
                        inner_id = inner.get("id")
                        if isinstance(inner_id, int):
                            return inner_id
    except Exception:
        pass
    return None

def _lesson_deeplink(step: int, *, slug: Optional[str] = None, lesson_id: Optional[int] = None) -> str:
    if slug:
        return f"/view/lesson/slug/{slug}?i={step}"
    if lesson_id is not None:
        return f"/view/lesson/{lesson_id}?i={step}"
    return "/view/home"

def _lesson_item(title: str, lesson_id: Optional[int], slug: Optional[str]) -> Dict[str, Any]:
    """Мини-карта урока для списка во вкладке."""
    path = _lesson_deeplink(0, slug=slug, lesson_id=lesson_id)
    payload: Dict[str, Any] = {"path": path}
    if lesson_id is not None:
        payload["id"] = int(lesson_id)
    if slug:
        payload["slug"] = slug

    return {
        "type": "text",
        "text": title,
        "paddings": {"top": 12, "bottom": 12, "left": 16, "right": 16},
        "background": [{"type": "solid", "color": "#F3F3F3"}],
        "border": {"corner_radius": 12},
        "margins": {"bottom": 10},
        "action": {
            "log_id": "open_lesson",
            "url": path,
            "payload": payload,
        },
        "text_alignment_horizontal": "left",
    }


def _build_home_tabs_from_strapi() -> Dict[str, Any]:
    """
    Собираем tabs с id=home_tabs из Strapi: категории -> вкладки, внутри — уроки.
    """
    raw = get_categories()
    data = raw.get("data") if isinstance(raw, dict) else raw
    categories = data or []

    items: List[Dict[str, Any]] = []

    for cat in categories:
        ca = _attrs(cat)
        title = (ca.get("title") or ca.get("name") or "Категория").strip()

        lessons_rel = ca.get("lessons") or {}
        if isinstance(lessons_rel, dict):
            l_items = lessons_rel.get("data") or []
        elif isinstance(lessons_rel, list):
            l_items = lessons_rel
        else:
            l_items = []

        lesson_views: List[Dict[str, Any]] = []
        for l in l_items:
            la = _attrs(l)
            lid = None
            if isinstance(l, dict):
                if "id" in l:
                    lid = l.get("id")
                elif "data" in l and isinstance(l["data"], dict):
                    lid = l["data"].get("id")

            slug = (la.get("slug") or "").strip() or None
            ltitle = (la.get("title") or f"Урок {lid or slug or ''}").strip()

            try:
                lid_int = int(lid) if lid is not None else None
            except Exception:
                lid_int = None

            lesson_views.append(_lesson_item(ltitle, lid_int, slug))

        if not lesson_views:
            lesson_views = [{
                "type": "text",
                "text": "Пока нет уроков",
                "paddings": {"top": 16, "bottom": 16},
                "text_alignment_horizontal": "center",
            }]

        items.append({
            "title": title,
            "div": {"type": "container", "items": lesson_views},
        })

    if not items:
        items = [{
            "title": "Категории",
            "div": {
                "type": "container",
                "items": [{
                    "type": "text",
                    "text": "Категории не найдены",
                    "paddings": {"top": 16, "bottom": 16},
                    "text_alignment_horizontal": "center",
                }],
            },
        }]

    return {
        "type": "tabs",
        "id": "home_tabs",
        "height": {"type": "wrap_content"},
        "tab_title_style": {"animation_type": "slide"},
        "items": items,
    }


# ---------------- API ----------------

# BACKWARD-COMPAT: handle /<slug>.json and /home.json requests.
@app.get("/<string:name>.json")
def legacy_json_entry(name: str):
    """
    BACKWARD-COMPAT: some client builds try to fetch `/<slug>.json`.
    If it's `home.json` — return the home page JSON.
    Otherwise treat <name> as a lesson slug and serve the lesson JSON by slug.
    """
    if name == "home":
        return get_home()
    # Pass through the current query string (?i=...) to the slug handler.
    return get_lesson_by_slug_route(name)



# Alias: support /lesson/slug/<slug> as a route to lesson by slug
@app.get("/lesson/slug/<string:slug>")
def get_lesson_by_slug_alias(slug: str):
    """Alias: serve lesson JSON by slug under /lesson/slug/<slug>?i=..."""
    return get_lesson_by_slug_route(slug)


# ---- Legacy catch-all for `/&lt;slug&gt;?i=...` -----------------------------
# Some older client builds request `/&lt;slug&gt;?i=0` directly.
# We proxy such requests to the slug-based lesson endpoint, but only if the
# slug looks safe and doesn't collide with known routes.
RESERVED_SLUGS = {
    "", "client.js", "ui", "view", "lesson", "home", "log",
    "favicon.ico", "index.html", "static"
}

@app.get("/<string:slug>")
def legacy_plain_slug(slug: str):
    # Reject reserved names or anything with a dot to avoid matching assets.
    if slug in RESERVED_SLUGS or "." in slug:
        abort(404)
    # Allow only simple URL-friendly slugs.
    if not re.fullmatch(r"[a-z0-9\-]+", slug):
        abort(404)
    # Delegate to the canonical slug handler:
    return get_lesson_by_slug_route(slug)



@app.get("/lesson/by/<string:slug>")
def get_lesson_by_slug_route(slug: str):
    step = request.args.get("i", default=0, type=int)

    template_path = UI_DIR / "pages" / "lesson.json"
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            card = json.load(f)
        card = _resolve_includes(card)
        card = _apply_design_tokens(card, _load_tokens("light"))
    except Exception as e:
        print("Template load error (slug):", e)
        with open(UI_DIR / "pages" / "home.json", "r", encoding="utf-8") as f:
            home = json.load(f)
        return jsonify(_resolve_includes(home))

    try:
        raw        = get_lesson_by_slug(slug)
        simplified = to_divkit_lesson(raw)
        words      = simplified.get("words", [])
        # Fallback: if slug response didn't include populated words, try resolving id
        if not words:
            lid = _extract_id_from_strapi_response(raw)
            if lid is not None:
                try:
                    raw_id = fetch_lesson(int(lid))
                    simplified = to_divkit_lesson(raw_id)
                    words = simplified.get("words", [])
                    print(f"[lesson:slug] fallback via id={lid}, words={len(words)}")
                except Exception as ee:
                    print("[lesson:slug] fallback fetch by id failed:", ee)
    except Exception as e:
        print("Strapi fetch failed (slug):", e)
        words = []

    if not words:
        return jsonify(card)

    if step < 0:
        step = 0
    if step >= len(words):
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

    is_last  = (step + 1 >= len(words))
    next_url = "/view/home" if is_last else _lesson_deeplink(step + 1, slug=slug, lesson_id=None)

    if random.random() < 0.5:
        left_text, right_text = correct, wrong
        left_url,  right_url  = next_url, None
    else:
        left_text, right_text = wrong, correct
        left_url,  right_url  = None, next_url

    _patch_by_id(card, "word_term",  {"text": term})
    _patch_by_id(card, "word_image", {"image_url": image_url or "https://dummyimage.com/220x220/eeeeee/aaaaaa.png&text=img"})
    _patch_by_id(card, "choice_left_text",  {"text": left_text})
    _patch_by_id(card, "choice_right_text", {"text": right_text})

    left_updates  = {"action": {"log_id": "next_word", "url": left_url} if left_url else None}
    right_updates = {"action": {"log_id": "next_word", "url": right_url} if right_url else None}
    _patch_by_id(card, "choice_left",  left_updates)
    _patch_by_id(card, "choice_right", right_updates)

    return jsonify(card)

@app.get("/lesson/<int:lesson_id>")
def get_lesson(lesson_id: int):
    """
    Отдаём страницу урока на базе шаблона /ui/pages/lesson.json с подстановкой данных.
    Правильный ответ ведёт на следующее слово, неверный — без действия.
    На последнем слове — редирект в SPA /view/home.
    """
    step = request.args.get("i", default=0, type=int)

    # 1) Загружаем шаблон и разворачиваем include'ы
    template_path = UI_DIR / "pages" / "lesson.json"
    try:
        with open(template_path, "r", encoding="utf-8") as f:
            card = json.load(f)
        card = _resolve_includes(card)
        card = _apply_design_tokens(card, _load_tokens("light"))
    except Exception as e:
        print("Template load error:", e)
        with open(UI_DIR / "pages" / "home.json", "r", encoding="utf-8") as f:
            home = json.load(f)
        return jsonify(_resolve_includes(home))

    # 2) Данные урока из Strapi
    try:
        raw        = fetch_lesson(lesson_id)
        simplified = to_divkit_lesson(raw)
        words      = simplified.get("words", [])
    except Exception as e:
        print("Strapi fetch failed:", e)
        words = []

    if not words:
        return jsonify(card)

    if step < 0:
        step = 0
    if step >= len(words):
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

    is_last  = (step + 1 >= len(words))
    next_url = "/view/home" if is_last else f"/view/lesson/{lesson_id}?i={step + 1}"

    # случайно раскладываем варианты
    if random.random() < 0.5:
        left_text, right_text = correct, wrong
        left_url,  right_url  = next_url, None
    else:
        left_text, right_text = wrong, correct
        left_url,  right_url  = None, next_url

    # Патчим привязанные узлы в шаблоне
    _patch_by_id(card, "word_term",  {"text": term})
    _patch_by_id(card, "word_image", {"image_url": image_url or "https://dummyimage.com/220x220/eeeeee/aaaaaa.png&text=img"})

    _patch_by_id(card, "choice_left_text",  {"text": left_text})
    _patch_by_id(card, "choice_right_text", {"text": right_text})

    left_updates  = {"action": {"log_id": "next_word", "url": left_url} if left_url else None}
    right_updates = {"action": {"log_id": "next_word", "url": right_url} if right_url else None}
    _patch_by_id(card, "choice_left",  left_updates)
    _patch_by_id(card, "choice_right", right_updates)

    return jsonify(card)


@app.get("/home")
def get_home():
    """Отдаём home + подменяем узел id="home_tabs" на данные из Strapi (если доступны)."""
    page_path = UI_DIR / "pages" / "home.json"
    with open(page_path, "r", encoding="utf-8") as f:
        card = json.load(f)

    card = _resolve_includes(card)
    card = _apply_design_tokens(card, _load_tokens("light"))

    try:
        tabs = _build_home_tabs_from_strapi()
        replaced = _replace_node_by_id(card, "home_tabs", tabs)
        if not replaced:
            print('WARN: node with id="home_tabs" not found in resolved home.json')
    except Exception as e:
        print("Build home tabs failed:", e)

    return jsonify(card)


@app.post("/log")
def log_action_post():
    data = request.get_json(silent=True) or {}
    print(">> DivKit action (POST):", data)
    return {"ok": True}


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5050, use_reloader=False)