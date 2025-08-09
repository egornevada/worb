from flask import Flask, request, jsonify, send_from_directory
from pathlib import Path

# Paths
APP_FILE = Path(__file__).resolve()
WEB_DIR = APP_FILE.parent.parent / "web"

app = Flask(__name__)

# ---- Web (serves the static demo page)
@app.get("/")
def index():
    return send_from_directory(WEB_DIR, "index.html")

@app.get("/client.js")
def client_js():
    return send_from_directory(WEB_DIR, "client.js", mimetype="application/javascript")

# ---- Healthcheck
@app.get("/health")
def health():
    return {"status": "ok"}

@app.get('/favicon.ico')
def favicon():
    return ("", 204)

# ---- DivKit data
@app.get("/lesson/<int:lesson_id>")
def get_lesson(lesson_id: int):
    # Minimal, valid DivKit card for WEB: emulate a button using a container
    return {
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
                                # Web build of DivKit doesn't have a native `button` component.
                                # We style a container as a button and put the action on it.
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
                                    {
                                        "type": "text",
                                        "text": "Начать",
                                        "text_color": "#FFFFFF",
                                        "font_weight": "medium"
                                    }
                                ]
                            }
                        ]
                    }
                }
            ]
        }
    }

# ---- Logging endpoint (POST)
@app.post("/log")
def log_action_post():
    data = request.get_json(silent=True) or {}
    print(">> DivKit action (POST):", data)
    return {"ok": True}


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5050, use_reloader=False)