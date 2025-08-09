# apps/backend/app.py
from pathlib import Path
import json
from flask import Flask, request, jsonify, send_from_directory

# Paths
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

# (опционально, если надо раздавать картинки/иконки из ui/)
@app.get("/ui/<path:filename>")
def ui_static(filename: str):
    return send_from_directory(UI_DIR, filename)

# ---------- Helpers ----------
def _resolve_includes(node, *, base_dir: Path | None = None):
    """
    Разворачивает {"$include": "<path>.json"}.
    - Путь без ведущего слэша трактуем как относительный к base_dir.
    - Путь, начинающийся на "components/" или "pages/", резолвим от корня UI_DIR.
    - Для вложенных include'ов base_dir становится папкой включённого файла.
    - Не даём выйти за пределы UI_DIR.
    """
    if base_dir is None:
        base_dir = UI_DIR

    # dict
    if isinstance(node, dict):
        # узел-include
        if "$include" in node and isinstance(node["$include"], str):
            inc_str = node["$include"].lstrip("/")  # лечим "/components/..."
            # абсолютный (от корня ui) include
            if inc_str.startswith(("components/", "pages/")):
                inc_path = (UI_DIR / inc_str).resolve()
            else:
                inc_path = (base_dir / inc_str).resolve()

            # безопасность: include должен лежать внутри UI_DIR
            try:
                inside = inc_path.is_relative_to(UI_DIR)
            except AttributeError:  # для Python <3.9
                inside = str(inc_path).startswith(str(UI_DIR))
            if not inside:
                raise ValueError(f"$include path escapes UI dir: {inc_path}")

            with open(inc_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)

            # вложенные include'ы — относительно директории включённого файла
            return _resolve_includes(loaded, base_dir=inc_path.parent)

        # обычный словарь — обходим детей
        return {k: _resolve_includes(v, base_dir=base_dir) for k, v in node.items()}

    # list
    if isinstance(node, list):
        return [_resolve_includes(x, base_dir=base_dir) for x in node]

    # скаляры
    return node

# ---------- API ----------
@app.get("/lesson/<int:lesson_id>")
def get_lesson(lesson_id: int):
    """
    Всегда отдаём домашний экран из /apps/web/ui/pages/home.json
    (внутри него могут быть $include'ы, их разворачиваем).
    """
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
    # убедись, что сервер слушает 127.0.0.1:5050 (как в твоём фронте)
    app.run(debug=True, host="127.0.0.1", port=5050, use_reloader=False)