# apps/backend/routes/home.py
from __future__ import annotations
from flask import Blueprint, jsonify, request
from core.paths import UI_DIR
from core.ui import (
    resolve_includes,
    apply_design_tokens,
    load_tokens,
    build_home_tabs_from_strapi,
    replace_node_by_id,
)
import json
from pathlib import Path

bp = Blueprint("home", __name__)

TABS_CONTAINER_IDS = [
    "home_tabs",          # новое id
    "home_lessons_tabs",  # старое id
    "home_lessons",       # контейнер со вкладками
    "tabs",
    "tabs_container",
]

def _replace_into_any(tree, ids, node) -> bool:
    for _id in ids:
        try:
            if replace_node_by_id(tree, _id, node):
                return True
        except Exception:
            pass
    return False

def _load_page(template: str | None) -> dict:
    """
    Загружаем шаблон страницы:
      - ?template=home_lessons => pages/home_lessons.json (если есть)
      - иначе pages/home.json, а если его нет — fallback на home_lessons.json.
    """
    candidates: list[Path] = []
    if template:
        candidates.append(UI_DIR / "pages" / f"{template}.json")
    candidates.append(UI_DIR / "pages" / "home.json")
    candidates.append(UI_DIR / "pages" / "home_lessons.json")

    for p in candidates:
        if p.exists():
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError("UI pages/home(.json) не найдён (и home_lessons.json тоже).")

@bp.get("/home")
def get_home():
    # параметры
    template = request.args.get("template")  # 'home' | 'home_lessons'
    theme = (request.args.get("theme") or "light").lower()
    active_tab = request.args.get("tab") or None

    # 1) читаем страницу БЕЗ токенов
    card = _load_page(template)

    # 2) раскрываем инклюды шаблона (чтобы найти контейнер для табов)
    card = resolve_includes(card)

    # 3) собираем табы из Strapi
    try:
        try:
            tabs = build_home_tabs_from_strapi(active_tab=active_tab)
        except TypeError:
            tabs = build_home_tabs_from_strapi()
    except Exception as e:
        print("Build home tabs failed:", e)
        tabs = {
            "type": "tabs",
            "items": [{
                "title": "Ошибка",
                "div": {
                    "type": "container",
                    "items": [{
                        "type": "text",
                        "text": "Не удалось загрузить категории",
                        "paddings": {"top": 16, "bottom": 16},
                        "text_alignment_horizontal": "center",
                    }],
                },
            }],
        }

    # 4) подставляем табы
    ok = _replace_into_any(card, TABS_CONTAINER_IDS, tabs)
    if not ok:
        print("WARN: Не нашли контейнер табов. Пробовали id:", ", ".join(TABS_CONTAINER_IDS))

    # 5) ЕЩЁ РАЗ раскрываем инклюды — уже с подставленными табами (внутри них есть $include)
    card = resolve_includes(card)

    # 6) применяем дизайн-токены ПОСЛЕ полной сборки дерева
    card = apply_design_tokens(card, load_tokens(theme))

    # 7) немного диагностики в лог
    try:
        # посчитаем кол-во карточек в первой вкладке, чтобы понимать, что реально пришло
        first_tab = None
        def _find_tabs(node):
            if isinstance(node, dict):
                if node.get("type") == "tabs" and node.get("items"):
                    return node
                for v in node.values():
                    found = _find_tabs(v)
                    if found: return found
            elif isinstance(node, list):
                for it in node:
                    found = _find_tabs(it)
                    if found: return found
            return None

        tnode = _find_tabs(card)
        if tnode and tnode.get("items"):
            first_tab = tnode["items"][0]
            grid = (first_tab.get("div") or {}).get("items") or []
            print(f"[home] tabs ok: tabs={len(tnode['items'])}, first_tab_children={len(grid)}")
        else:
            print("[home] tabs not found after injection")
    except Exception:
        pass

    return jsonify(card)