from flask import Flask, send_file, request
from pathlib import Path

# Пути проекта
APP_FILE = Path(__file__).resolve()
BASE_DIR = APP_FILE.parent.parent          # .../apps
WEB_DIR = BASE_DIR / "web"                 # .../apps/web

# Flask
app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="/web")

print("APP_FILE =", APP_FILE)
print("WEB_DIR  =", WEB_DIR, "| exists:", WEB_DIR.exists())

@app.post("/log")
def log_action_post():
    data = request.get_json(silent=True) or {}
    print(">> DivKit action (POST):", data)
    return {"ok": True}

# ---- служебные эндпоинты ----
@app.get("/__debug")
def debug_info():
    return {
        "app_file": str(APP_FILE),
        "cwd": str(Path.cwd()),
        "web_dir": str(WEB_DIR),
        "web_exists": WEB_DIR.exists(),
        "web_contents": [p.name for p in WEB_DIR.glob("*")] if WEB_DIR.exists() else [],
    }

@app.get("/health")
def health():
    return {"status": "ok"}

# ---- логирование действий ----
@app.post("/log")
def log_action_post():
    data = request.get_json(silent=True) or {}
    print(">> DivKit action (POST):", data)
    return {"ok": True}

@app.get("/log")
def log_action_get():
    # Простой и надёжный способ зафиксировать клик через переход по URL
    print(">> DivKit action (GET):", dict(request.args))
    # Вернём пользователя назад, чтобы страница не «уезжала»
    return "<script>history.back();</script>"

# ---- данные для DivKit ----
@app.get("/lesson/<int:lesson_id>")
def get_lesson(lesson_id: int):
    # Важно: корневой ключ "card"
    return {
        "card": {
            "log_id": f"lesson_{lesson_id}",
            "states": [{
                "state_id": 0,
                "div": {
                    "type": "container",
                    "items": [
                        {
                            "type": "text",
                            "text": f"Урок #{lesson_id}: привет из Flask + DivKit JSON",
                            "margins": {"bottom": 12}
                        },
                        {
                            # Кликабельная «кнопка» на контейнере
                            "type": "container",
                            "paddings": {"top": 10, "bottom": 10, "left": 16, "right": 16},
                            "border": {"corner_radius": 12},
                            "background": [{"type": "solid", "color": "#1a73e8"}],
                            "alignment_vertical": "center",
                            "items": [
                                {
                                    "type": "text",
                                    "text": "Начать",
                                    "text_color": "#FFFFFF",
                                    "font_weight": "medium"
                                }
                            ],
                            # Пока логируем через обычный GET переход
                            "action": {
                                "log_id": "start_clicked",
                                "url": f"/log?event=start_clicked&lesson_id={lesson_id}"
                            }
                        }
                    ]
                }
            }]
        }
    }

# ---- корень: отдать HTML ----
@app.get("/")
def index():
    return send_file(WEB_DIR / "index.html")

# ---- запуск ----
if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5050, use_reloader=False)