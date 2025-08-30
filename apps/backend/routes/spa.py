from __future__ import annotations
from flask import Blueprint, send_from_directory, jsonify
from core.paths import WEB_DIR, UI_DIR
from pathlib import Path
import json

from core.ui import resolve_includes, apply_design_tokens, load_tokens


bp = Blueprint("spa", __name__)

# Serve SPA index.html at root
@bp.get("/")
def root_index():
    return send_from_directory(WEB_DIR, "index.html")

# Serve static assets from /web
@bp.get("/client.js")
def client_js():
    return send_from_directory(WEB_DIR, "client.js", mimetype="application/javascript")

@bp.get("/client.css")
def client_css():
    return send_from_directory(WEB_DIR, "client.css", mimetype="text/css")

@bp.get("/favicon.ico")
def favicon():
    return send_from_directory(WEB_DIR, "favicon.ico")

# Generic UI static route
@bp.get("/ui/<path:filename>")
def ui_static(filename: str):
    return send_from_directory(UI_DIR, filename)


@bp.get("/page/<path:page_name>")
def get_ui_page(page_name: str):
    if page_name.endswith(".json"):
        page_name = page_name[:-5]
    raw_path = (UI_DIR / "pages" / f"{page_name}.json").resolve()

    try:
        inside = raw_path.is_relative_to(UI_DIR / "pages")
    except AttributeError:
        inside = str(raw_path).startswith(str(UI_DIR / "pages"))
    if not inside or not raw_path.exists():
        return jsonify({
            "card": {
                "log_id": page_name or "page",
                "states": [
                    {"state_id": 0, "div": {
                        "type": "container",
                        "items": [
                            {
                                "type": "text",
                                "text": f"page '{page_name}' not found",
                                "text_alignment_horizontal": "center",
                                "paddings": {"top": 16, "bottom": 16}
                            }
                        ]
                    }}
                ]
            }
        })

    with open(raw_path, "r", encoding="utf-8") as f:
        card = json.load(f)
    card = resolve_includes(card)
    card = apply_design_tokens(card, load_tokens("light"))
    return jsonify(card)

# SPA deep links
@bp.get("/view")
@bp.get("/view/")
@bp.get("/view/<path:subpath>")
def view_entry(subpath: str = ""):
    return send_from_directory(WEB_DIR, "index.html")

# convenience: direct JSON for /ui/pages/*
@bp.get("/ui/pages/<path:page_name>.json")
def ui_pages_compat(page_name: str):
    return get_ui_page(page_name)

# test page
@bp.get("/test")
def test_page():
    raw = (UI_DIR / "pages" / "test.json")
    try:
        with open(raw, "r", encoding="utf-8") as f:
            card = json.load(f)
        card = resolve_includes(card)
        card = apply_design_tokens(card, load_tokens("light"))
        return jsonify(card)
    except Exception:
        return jsonify({
            "card": {
                "log_id": "test",
                "states": [
                    {"state_id": 0, "div": {
                        "type": "container",
                        "items": [
                            {
                                "type": "text",
                                "text": "test.json не найден",
                                "text_alignment_horizontal": "center",
                                "paddings": {"top": 16, "bottom": 16}
                            }
                        ]
                    }}
                ]
            }
        })