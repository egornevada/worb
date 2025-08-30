from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import os

from core.paths import UI_DIR
from strapi_client import get_categories  # только для вкладок на /home

# ---------- helpers: tokens ----------

_TOKENS_CACHE: Dict[str, Any] = {}

def _deep_get(d: Dict[str, Any], dotted: str, default: Any = None) -> Any:
    cur: Any = d
    for part in dotted.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur

def load_tokens(theme: str = "light") -> Dict[str, Any]:
    key = f"colors.{theme}"
    if key in _TOKENS_CACHE:
        return _TOKENS_CACHE[key]
    tokens_path = UI_DIR / "tokens" / f"colors.{theme}.json"
    try:
        with open(tokens_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    _TOKENS_CACHE[key] = data
    return data

def apply_design_tokens(node: Any, tokens: Dict[str, Any]) -> Any:
    if isinstance(node, dict):
        return {k: apply_design_tokens(v, tokens) for k, v in node.items()}
    if isinstance(node, list):
        return [apply_design_tokens(x, tokens) for x in node]
    if isinstance(node, str) and node.startswith("@"):
        resolved = _deep_get(tokens, node[1:], None)
        return resolved if resolved is not None else node
    return node

# ---------- helpers: includes ----------

def _missing_component_node(path: "Path|str") -> Dict[str, Any]:
    return {
        "type": "container",
        "width": {"type": "match_parent"},
        "items": [{
            "type": "text",
            "text": f"Компонент не найден: {path}",
            "text_alignment_horizontal": "center",
            "paddings": {"top": 8, "bottom": 8},
        }],
        "background": [{"type": "solid", "color": "#FFF0B3"}],
        "border": {"corner_radius": 8},
        "margins": {"top": 4, "bottom": 4},
    }

def _strict_includes() -> bool:
    return str(os.getenv("STRICT_INCLUDES", "")).lower() in ("1", "true", "yes", "on")

def resolve_includes(node: Any, *, base_dir: Optional[Path] = None) -> Any:
    if base_dir is None:
        base_dir = UI_DIR

    def _resolve_one(inc_key: str, inc_value: str) -> Any:
        soft = (inc_key == "$include_optional") or not _strict_includes()
        inc_str = inc_value.lstrip("/")
        if inc_str.startswith(("components/", "pages/")):
            inc_path = (UI_DIR / inc_str).resolve()
        else:
            inc_path = (base_dir / inc_str).resolve()

        try:
            inside = inc_path.is_relative_to(UI_DIR)  # py3.9+
        except AttributeError:
            inside = str(inc_path).startswith(str(UI_DIR))
        if not inside:
            return _missing_component_node(inc_value) if soft else (_ for _ in ()).throw(
                ValueError(f"$include outside UI: {inc_path}")
            )

        if not inc_path.exists() and inc_str.startswith("components/"):
            # миграционное правило: components/header/*
            alt = (UI_DIR / "components" / "header" / inc_path.name).resolve()
            if alt.exists():
                inc_path = alt

        try:
            with open(inc_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            return resolve_includes(loaded, base_dir=inc_path.parent)
        except Exception:
            return _missing_component_node(inc_value) if soft else (_ for _ in ()).throw(
                RuntimeError(f"include failed: {inc_value}")
            )

    if isinstance(node, dict):
        if "$include" in node and isinstance(node["$include"], str):
            return _resolve_one("$include", node["$include"])
        if "$include_optional" in node and isinstance(node["$include_optional"], str):
            return _resolve_one("$include_optional", node["$include_optional"])
        return {k: resolve_includes(v, base_dir=base_dir) for k, v in node.items()}
    if isinstance(node, list):
        return [resolve_includes(x, base_dir=base_dir) for x in node]
    return node

# ---------- helpers: patch/replace-by-id ----------

def patch_by_id(tree: Any, target_id: str, updates: Dict[str, Any]) -> None:
    if isinstance(tree, dict):
        if tree.get("id") == target_id:
            for k, v in updates.items():
                if k == "action" and v is None:
                    tree.pop("action", None)
                else:
                    tree[k] = v
        for v in list(tree.values()):
            patch_by_id(v, target_id, updates)
    elif isinstance(tree, list):
        for item in tree:
            patch_by_id(item, target_id, updates)

def replace_node_by_id(node: Any, node_id: str, replacement: Dict[str, Any]) -> bool:
    if isinstance(node, dict):
        if node.get("id") == node_id:
            node.clear()
            node.update(replacement)
            return True
        for k, v in list(node.items()):
            if replace_node_by_id(v, node_id, replacement):
                return True
    elif isinstance(node, list):
        for i, item in enumerate(list(node)):
            if isinstance(item, dict) and item.get("id") == node_id:
                node[i] = replacement
                return True
            if replace_node_by_id(item, node_id, replacement):
                return True
    return False

# ---------- helpers: strapi shapes + tabs ----------

def _attrs(n: Any) -> Dict[str, Any]:
    if not isinstance(n, dict):
        return {}
    if "data" in n and isinstance(n["data"], dict):
        return n["data"].get("attributes") or {}
    return n.get("attributes") or n

def lesson_deeplink(step: int, *, slug: Optional[str] = None, lesson_id: Optional[int] = None) -> str:
    if slug:
        return f"/view/lesson/slug/{slug}?i={step}"
    if lesson_id is not None:
        return f"/view/lesson/{lesson_id}?i={step}"
    return "/view/home"

def _lesson_item(title: str, lid: Optional[int], slug: Optional[str]) -> Dict[str, Any]:
    path = lesson_deeplink(0, slug=slug, lesson_id=lid)
    payload: Dict[str, Any] = {"path": path}
    if lid is not None:
        payload["id"] = int(lid)
    if slug:
        payload["slug"] = slug
    return {
        "type": "text",
        "text": title,
        "paddings": {"top": 12, "bottom": 12, "left": 16, "right": 16},
        "background": [{"type": "solid", "color": "#F3F3F3"}],
        "border": {"corner_radius": 12},
        "margins": {"bottom": 10},
        "action": {"log_id": "open_lesson", "url": path, "payload": payload},
        "text_alignment_horizontal": "left",
    }

def build_home_tabs_from_strapi() -> Dict[str, Any]:
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