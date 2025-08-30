from __future__ import annotations
from flask import Blueprint, jsonify, request
from core.paths import UI_DIR
from core.ui import resolve_includes, apply_design_tokens, load_tokens, build_home_tabs_from_strapi, replace_node_by_id
import json


bp = Blueprint("home", __name__)

# Try to replace by any of the given ids; return True if replaced
def _replace_into_any(card, ids, node):
    for _id in ids:
        try:
            if replace_node_by_id(card, _id, node):
                return True
        except Exception:
            pass
    return False

@bp.get("/home")
def get_home():
    page_path = UI_DIR / "pages" / "home.json"
    with open(page_path, "r", encoding="utf-8") as f:
        card = json.load(f)
    card = resolve_includes(card)
    card = apply_design_tokens(card, load_tokens("light"))
    active_tab = request.args.get("tab") or None
    try:
        # Prefer API that accepts active_tab; fall back if the function has no such argument
        try:
            tabs = build_home_tabs_from_strapi(active_tab=active_tab)
        except TypeError:
            tabs = build_home_tabs_from_strapi()

        ok = _replace_into_any(
            card,
            [
                "home_tabs",            # новое id
                "home_lessons_tabs",    # старое id варианта компонента
                "home_lessons",         # ещё один возможный контейнер
                "tabs",
                "tabs_container",
            ],
            tabs,
        )
        if not ok:
            print('WARN: tabs container not found in home.json (tried ids: home_tabs, home_lessons_tabs, home_lessons, tabs, tabs_container)')
    except Exception as e:
        print("Build home tabs failed:", e)
    return jsonify(card)