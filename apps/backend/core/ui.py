# apps/backend/core/ui.py
from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Optional
from copy import deepcopy
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

def _safe_join(base: Path, rel: str) -> Path:
    p = (base / rel.lstrip("/")).resolve()
    try:
        inside = p.is_relative_to(UI_DIR)  # py3.9+
    except AttributeError:
        inside = str(p).startswith(str(UI_DIR))
    if not inside:
        raise ValueError(f"$include outside UI: {p}")
    return p

def _load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

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

    def _resolve_from_spec(inc_key: str, spec: Any) -> Any:
        soft = (inc_key == "$include_optional") or not _strict_includes()

        # Case 1: string include
        if isinstance(spec, str):
            inc_str = spec.lstrip("/")
            if inc_str.startswith(("components/", "pages/")):
                inc_path = _safe_join(UI_DIR, inc_str)
            else:
                inc_path = _safe_join(base_dir, inc_str)

            # migration fallback: components/header/*
            if not inc_path.exists() and inc_str.startswith("components/"):
                alt = (UI_DIR / "components" / "header" / Path(inc_str).name).resolve()
                if alt.exists():
                    inc_path = alt

            try:
                loaded = _load_json(inc_path)
                return resolve_includes(loaded, base_dir=inc_path.parent)
            except Exception:
                return _missing_component_node(spec) if soft else (_ for _ in ()).throw(
                    RuntimeError(f"include failed: {spec}")
                )

        # Case 2: object include {path, patch?}
        if isinstance(spec, dict):
            path_str = spec.get("path")
            if not isinstance(path_str, str):
                return _missing_component_node(spec) if soft else (_ for _ in ()).throw(
                    ValueError("$include object must contain 'path': str")
                )

            inc_str = path_str.lstrip("/")
            if inc_str.startswith(("components/", "pages/")):
                inc_path = _safe_join(UI_DIR, inc_str)
            else:
                inc_path = _safe_join(base_dir, inc_str)

            # migration fallback: components/header/*
            if not inc_path.exists() and inc_str.startswith("components/"):
                alt = (UI_DIR / "components" / "header" / Path(inc_str).name).resolve()
                if alt.exists():
                    inc_path = alt

            try:
                loaded = _load_json(inc_path)
                resolved = resolve_includes(loaded, base_dir=inc_path.parent)
            except Exception:
                return _missing_component_node(path_str) if soft else (_ for _ in ()).throw(
                    RuntimeError(f"include failed: {path_str}")
                )

            # optional patch list: [{ "id": "...", "set": {...} }, ...]
            patch_list = spec.get("patch") or []
            if isinstance(patch_list, list):
                for op in patch_list:
                    if not isinstance(op, dict):
                        continue
                    tid = op.get("id")
                    updates = op.get("set") or {}
                    if not isinstance(updates, dict):
                        continue

                    applied = False
                    if isinstance(tid, str) and tid:
                        applied = patch_by_id(resolved, tid, updates)

                    # Fallbacks:
                    # - allow patching the root component when id is not provided or special
                    # - or when the root looks like a state component (type == "state")
                    if not applied and isinstance(resolved, dict):
                        if tid in (None, "", "*", "root") or resolved.get("type") == "state":
                            for k, v in updates.items():
                                if k == "action" and v is None:
                                    resolved.pop("action", None)
                                else:
                                    resolved[k] = v
                            applied = True

            # --- state handling on include ---
            _sentinel = object()
            req_sid = _sentinel
            for key in (
                "state_id", "state", "selected", "selected_id",
                "initial_state_id", "initial_state", "initial",
                "default", "value", "current",
            ):
                if key in spec:
                    req_sid = spec[key]
                    break

            # wrapper policy: keep wrapper only if explicitly requested
            keep_wrapper = bool(spec.get("keep_state") or spec.get("keep_wrapper"))
            explicit_flatten = bool(spec.get("flatten_state") or spec.get("unwrap") or spec.get("inline"))
            flatten = explicit_flatten or (req_sid is not _sentinel and not keep_wrapper)

            if isinstance(resolved, dict) and resolved.get("type") == "state":
                states = resolved.get("states")
                if isinstance(states, list) and states:
                    def _sid(s):
                        return s.get("state_id") if isinstance(s, dict) else None
                    def _eq(a, b):
                        return (a is not None and b is not None and str(a) == str(b))

                    # choose state: requested -> current -> first
                    chosen = None
                    if req_sid is not _sentinel:
                        chosen = next((s for s in states if _eq(_sid(s), req_sid)), None)
                    if chosen is None:
                        cur = resolved.get("state_id")
                        if cur is not None:
                            chosen = next((s for s in states if _eq(_sid(s), cur)), None)
                    if chosen is None:
                        chosen = states[0] if isinstance(states[0], dict) else None

                    # sync top-level state_id
                    sid_val = _sid(chosen)
                    if sid_val is not None:
                        resolved["state_id"] = sid_val

                    # move chosen first to please engines that rely on order
                    try:
                        idx = states.index(chosen)
                        if idx > 0:
                            states.insert(0, states.pop(idx))
                    except Exception:
                        pass

                    # --- Support div patching and aspect/square hints when flattening ---
                    div_patch = spec.get("patch_div") or spec.get("div_set") or {}
                    if not isinstance(div_patch, dict):
                        div_patch = {}
                    aspect_ratio = spec.get("aspect_ratio")
                    make_square = bool(spec.get("square") or spec.get("enforce_square"))
                    if make_square and aspect_ratio is None:
                        aspect_ratio = 1

                    # inline selected state's div when flatten is requested
                    if flatten and isinstance(chosen, dict) and "div" in chosen:
                        from copy import deepcopy
                        div_node = deepcopy(chosen["div"])
                        # Apply patch to div_node
                        for k, v in div_patch.items():
                            div_node[k] = v
                        # Apply aspect if given
                        if aspect_ratio is not None:
                            div_node["aspect"] = {"ratio": float(aspect_ratio)}
                        return resolve_includes(div_node, base_dir=inc_path.parent)

            return resolved

        # Unknown spec type
        return _missing_component_node(spec) if soft else (_ for _ in ()).throw(
            ValueError("$include must be string or object")
        )

    if isinstance(node, dict):
        if "$include" in node:
            return _resolve_from_spec("$include", node["$include"])
        if "$include_optional" in node:
            return _resolve_from_spec("$include_optional", node["$include_optional"])
        return {k: resolve_includes(v, base_dir=base_dir) for k, v in node.items()}

    if isinstance(node, list):
        return [resolve_includes(x, base_dir=base_dir) for x in node]

    return node

# ---------- helpers: patch/replace-by-id ----------

def patch_by_id(tree: Any, target_id: str, updates: Dict[str, Any]) -> bool:
    applied = False
    if isinstance(tree, dict):
        if tree.get("id") == target_id:
            for k, v in updates.items():
                if k == "action" and v is None:
                    tree.pop("action", None)
                else:
                    tree[k] = v
            applied = True
        for v in list(tree.values()):
            if patch_by_id(v, target_id, updates):
                applied = True
    elif isinstance(tree, list):
        for item in tree:
            if patch_by_id(item, target_id, updates):
                applied = True
    return applied

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

def _lesson_item(title: str, lid: Optional[int], slug: Optional[str], *, state: str = "0") -> Dict[str, Any]:
    """Карточка урока: визуал из components/lesson_card.json, данные из Strapi.
    Возвращаем уже РЕЗОЛВНУТЫЙ div выбранного состояния (flatten_state), без внешней обёртки,
    чтобы в финальном ответе не оставалось узлов `$include` (DivKit их не понимает).
    """
    path = lesson_deeplink(0, slug=slug, lesson_id=lid)
    payload: Dict[str, Any] = {"path": path}
    if lid is not None:
        payload["id"] = int(lid)
    if slug:
        payload["slug"] = slug

    # Готовим include-спеку для карточки и РЕШАЕМ её прямо здесь,
    # чтобы наружу вернуть чистый div без $include.
    include_spec = {
        "$include": {
            "path": "/components/lesson_card.json",
            "state_id": str(state),           # "0" | "1" | "2"
            "flatten_state": True,            # инлайн выбранного стейта
            # подменяем заголовки во всех вариантах
            "patch": [
                {"id": "lesson_title",           "set": {"text": title}},
                {"id": "lesson_title_brand",     "set": {"text": title}},
                {"id": "lesson_title_disabled",  "set": {"text": title}},
            ],
            # только клик на корневой div включённого state-а
            "div_set": {
                "action": {"log_id": "open_lesson", "url": path, "payload": payload},
                "width":  {"type": "match_parent"},
                "height": {"type": "match_parent"},
            },
        }
    }

    # База для относительного пути — папка `components`
    resolved = resolve_includes(include_spec, base_dir=UI_DIR / "components")
    # resolve_includes вернёт сам div (благодаря flatten_state). Нам нужно вернуть ровно его.
    return resolved

def build_home_tabs_from_strapi() -> Dict[str, Any]:
    raw = get_categories()
    data = raw.get("data") if isinstance(raw, dict) else raw
    categories = data or []

    def _grid_with_cards(cards: List[Dict[str, Any]]) -> Dict[str, Any]:
        # Каждую карточку заворачиваем в квадратную ячейку, чтобы не было конфликта
        # wrap_content (у грида) vs match_parent (у карточки).
        cells: List[Dict[str, Any]] = []
        for card in cards:
            cells.append({
                "type": "container",
                "width": {"type": "match_parent"},
                "aspect": {"ratio": 1},
                "margins": {"left": 4, "right": 4, "bottom": 4,"top": 4},
                "items": [card]
            })

        return {
            "type": "grid",
            "id": "category_grid",
            "width": {"type": "match_parent"},
            "height": {"type": "wrap_content"},
            "column_count": 2,
            # высоту ячейки задаём через aspect в самой ячейке, поэтому item_height не используем
            "items": cells,
        }

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

            raw_state = (
                la.get("state")
                or la.get("ui_state")
                or la.get("status")
                or la.get("uiState")
            )
            state_map = {
                "0": "0", "1": "1", "2": "2",
                "brand": "1", "success": "1", "ready": "1", "done": "1", "completed": "1",
                "disabled": "2", "locked": "2", "off": "2",
            }
            if isinstance(raw_state, bool):
                state_val = "1" if raw_state else "0"
            elif isinstance(raw_state, int):
                state_val = "2" if raw_state == 2 else ("1" if raw_state == 1 else "0")
            elif isinstance(raw_state, str):
                state_val = state_map.get(raw_state.strip().lower(), raw_state.strip())
            else:
                state_val = "0"

            lesson_views.append(_lesson_item(ltitle, lid_int, slug, state=state_val))

        if not lesson_views:
            # Пустая категория — дружелюбный плейсхолдер
            tab_div = {
                "type": "container",
                "items": [{
                    "type": "text",
                    "text": "Пока нет уроков",
                    "paddings": {"top": 16, "bottom": 16},
                    "text_alignment_horizontal": "center",
                }],
            }
        else:
            tab_div = _grid_with_cards(lesson_views)

        items.append({
            "title": title,
            "div": tab_div,
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

    tabs = {
        "type": "tabs",
        "id": "home_tabs",
        "height": {"type": "wrap_content"},
        "has_separator": False,
        "title_paddings": {"left": 16, "right": 16, "top": 0, "bottom": 0},
        "tab_title_style": {
            "animation_type": "slide",
            "item_spacing": 8,
            "corner_radius": 20,
            "paddings": {"left": 14, "right": 14, "top": 6, "bottom": 6},
            "font_size": 16,
            "active_font_weight": "medium",
            "inactive_font_weight": "regular",
            "active_text_color": "#FFFFFF",
            "inactive_text_color": "#808080",
            "active_background_color": "#222222",
            "inactive_background_color": "#00000000"
        },
        "items": items,
    }

    resolved = resolve_includes(deepcopy(tabs))
    tokens = load_tokens("light")
    resolved = apply_design_tokens(resolved, tokens)
    return resolved


def inject_home_lessons_tabs(card_tree: Dict[str, Any]) -> Dict[str, Any]:
    """Заменяет placeholder-узел с id `home_tabs` на реально собранные табы
    с сеткой уроков из Strapi. Если узла с таким id нет, заменяет первый
    встретившийся узел `type == "tabs"`.

    Вызывай эту функцию в обработчике /view/home после resolve_includes.
    """
    try:
        tabs = build_home_tabs_from_strapi()
    except Exception:
        # В случае проблем со Strapi — ничего не ломаем, просто возвращаем как есть
        return card_tree

    # 1) Пытаемся заменить по id
    if replace_node_by_id(card_tree, "home_tabs", tabs):
        return card_tree

    # 2) Фолбэк: найти первый узел type == 'tabs' и заменить его
    def _replace_first_tabs(node: Any) -> bool:
        if isinstance(node, dict):
            if node.get("type") == "tabs":
                node.clear()
                node.update(tabs)
                return True
            for v in list(node.values()):
                if _replace_first_tabs(v):
                    return True
        elif isinstance(node, list):
            for i in range(len(node)):
                if _replace_first_tabs(node[i]):
                    return True
        return False

    _replace_first_tabs(card_tree)
    return card_tree