from pathlib import Path
import json
from flask import Flask, request, send_from_directory

# Paths
APP_FILE = Path(__file__).resolve()
WEB_DIR = APP_FILE.parent.parent / "web"
UI_DIR  = WEB_DIR / "ui"

app = Flask(__name__, static_folder=None)

# ----- Web: статика для демо-страницы -----
@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")

@app.get("/client.js")
def client_js():
    return send_from_directory(WEB_DIR, "client.js", mimetype="application/javascript")

@app.get("/ui/<path:filename>")
def ui_static(filename: str):
    return send_from_directory(UI_DIR, filename)

@app.get("/health")
def health():
    return {"status": "ok"}

# ----- DivKit данные -----
@app.get("/lesson/<int:lesson_id>")
def get_lesson(lesson_id: int):
    # Базовая карточка
    card = {
        "card": {
            "log_id": f"lesson_{lesson_id}",
            "states": [
                {
                    "state_id": 0,
                    "div": {
                        "type": "container",
                        "items": [
                            {"type": "text", "text": f"Урок #{lesson_id}: привет из Flask + DivKit JSON"},
                            {
                                # В веб-билде DivKit нет нативной button — делаем контейнер-кнопку
                                "type": "container",
                                "paddings": {"top": 8, "bottom": 8, "left": 16, "right": 16},
                                "background": [{"type": "solid", "color": "#1a73e8"}],
                                "border": {"corner_radius": 12},
                                "alignment_vertical": "center",
                                "action": {
                                    "log_id": "start_clicked",
                                    "url": "div-action://none",
                                    "payload": {"lesson_id": str(lesson_id)}
                                },
                                "items": [
                                    {"type": "text", "text": "Начать", "text_color": "#FFFFFF", "font_weight": "medium"}
                                ]
                            }
                        ]
                    }
                }
            ]
        }
    }

    # Инжектим хедер из apps/web/ui/components/header.json (если есть)
    try:
        header_path = UI_DIR / "components" / "header.json"
        with open(header_path, "r", encoding="utf-8") as f:
            header_block = json.load(f)  # один Div-узел
        root_items = card["card"]["states"][0]["div"].setdefault("items", [])
        root_items.insert(0, header_block)
    except Exception as e:
        print("[WARN] header.json not injected:", e)

    return card

# ----- Логирование кликов из DivKit -----
@app.post("/log")
def log_action_post():
    data = request.get_json(silent=True) or {}
    print(">> DivKit action (POST):", data)
    return {"ok": True}

if __name__ == "__main__":
    print("WEB_DIR =", WEB_DIR, "| exists:", WEB_DIR.exists())
    app.run(debug=True, host="127.0.0.1", port=5050, use_reloader=False)