from __future__ import annotations
from flask import Blueprint, jsonify, send_from_directory, request
from core.paths import UI_DIR, WEB_DIR
from core.ui import resolve_includes, apply_design_tokens, load_tokens, patch_by_id
from strapi_client import get_lesson as fetch_lesson, get_lesson_by_slug, to_divkit_lesson
from pathlib import Path
import json, os, random

# local recursive patcher: patch all nodes with given id (not just first one)
def _patch_all_by_id(node, target_id, patch):
    if isinstance(node, dict):
        if node.get("id") == target_id and isinstance(patch, dict):
            node.update(patch)
        # walk nested structures
        for k, v in list(node.items()):
            if k in ("items", "states") and isinstance(v, list):
                for child in v:
                    # state item could be {"state_id":..., "div": {...}}
                    if isinstance(child, dict) and "div" in child and isinstance(child["div"], dict):
                        _patch_all_by_id(child["div"], target_id, patch)
                    else:
                        _patch_all_by_id(child, target_id, patch)
            elif isinstance(v, dict):
                _patch_all_by_id(v, target_id, patch)
            elif isinstance(v, list):
                for child in v:
                    _patch_all_by_id(child, target_id, patch)

# fully replace first node with given id (clear + update)
def _replace_node_by_id(node, target_id, replacement) -> bool:
    if isinstance(node, dict):
        if node.get("id") == target_id and isinstance(replacement, dict):
            node.clear()
            node.update(replacement)
            return True
        # walk nested structures
        for k, v in list(node.items()):
            if k in ("items", "states") and isinstance(v, list):
                for child in v:
                    # state item could be {"state_id":..., "div": {...}}
                    if isinstance(child, dict) and "div" in child and isinstance(child["div"], dict):
                        if _replace_node_by_id(child["div"], target_id, replacement):
                            return True
                    else:
                        if _replace_node_by_id(child, target_id, replacement):
                            return True
            elif isinstance(v, dict):
                if _replace_node_by_id(v, target_id, replacement):
                    return True
            elif isinstance(v, list):
                for child in v:
                    if _replace_node_by_id(child, target_id, replacement):
                        return True
    elif isinstance(node, list):
        for child in node:
            if _replace_node_by_id(child, target_id, replacement):
                return True
    return False

# find first node with given id (read-only search)
def _find_first_by_id(node, target_id):
    if isinstance(node, dict):
        if node.get("id") == target_id:
            return node
        for k, v in list(node.items()):
            if k in ("items", "states") and isinstance(v, list):
                for child in v:
                    if isinstance(child, dict) and "div" in child and isinstance(child["div"], dict):
                        found = _find_first_by_id(child["div"], target_id)
                        if found is not None:
                            return found
                    else:
                        found = _find_first_by_id(child, target_id)
                        if found is not None:
                            return found
            elif isinstance(v, dict):
                found = _find_first_by_id(v, target_id)
                if found is not None:
                    return found
            elif isinstance(v, list):
                for child in v:
                    found = _find_first_by_id(child, target_id)
                    if found is not None:
                        return found
    elif isinstance(node, list):
        for child in node:
            found = _find_first_by_id(child, target_id)
            if found is not None:
                return found
    return None

def _merge_card_variables(card_root: dict, values: dict):
    """Merge/update DivKit card-level variables.
    DivKit expects variables on the **card** node, not at the top level.
    """
    # find the actual card node
    card_node = card_root.get("card") if isinstance(card_root, dict) and "card" in card_root else card_root
    if not isinstance(card_node, dict):
        return

    vars_list = card_node.setdefault("variables", [])
    # turn list to dict for easy update
    by_name = {v.get("name"): v for v in vars_list if isinstance(v, dict) and v.get("name")}
    for name, val in values.items():
        entry = by_name.get(name)
        vtype = "number" if isinstance(val, (int, float)) else "string"
        if entry is not None:
            entry["type"] = vtype
            entry["value"] = val
        else:
            vars_list.append({"name": name, "type": vtype, "value": val})

def _hard_set_progress_bar(card_root: dict, done: int, total: int) -> None:
    """Hard-replace the node with id=progress_bar by a weighted two-segment bar.
    Works in DivKit/SDUI because weights are applied inside a horizontal container.
    """
    try:
        # clamp values
        total = max(int(total or 0), 1)
        done = max(min(int(done or 0), total), 0)
        rest = max(total - done, 0)

        progress_node = {
            "type": "container",
            "id": "progress_bar",
            "orientation": "horizontal",
            "width": {"type": "match_parent"},
            "height": {"type": "fixed", "value": 8},
            "weight": 1,  # let header allocate the remaining space
            "clip_to_bounds": True,
            "border": {"corner_radius": 4},
            "background": [{"type": "solid", "color": "#E5E7EB"}],
            "items": [
                {
                    "type": "container",
                    "id": "progress_done",
                    "height": {"type": "match_parent"},
                    "weight": done,
                    "background": [{"type": "solid", "color": "#46B100"}],
                },
                {
                    "type": "container",
                    "id": "progress_rest",
                    "height": {"type": "match_parent"},
                    "weight": rest
                }
            ]
        }

        # fully replace the node to avoid mixing with any previous structure
        if not _replace_node_by_id(card_root, "progress_bar", progress_node):
            patch_by_id(card_root, "progress_bar", progress_node)
    except Exception as e:
        print("hard progress build failed:", e)

bp = Blueprint("lessons", __name__)

def _make_progress_node(total: int, done: int) -> dict:
    """Build a progress bar node (try to use /ui/components/progress_bar.json if present).
    We patch weights for "progress_done" and "progress_rest" and wrap with paddings.
    """
    try:
        rest = max(total - done, 0)
        # Try to load a reusable component if it exists
        comp_path = UI_DIR / "components" / "progress_bar.json"
        if comp_path.exists():
            with open(comp_path, "r", encoding="utf-8") as f:
                node = json.load(f)
            node = resolve_includes(node)
            # Patch weights inside the loaded component
            patch_by_id(node, "progress_done", {"weight": done})
            patch_by_id(node, "progress_rest", {"weight": rest})
        else:
            # Fallback: inline simple progress bar (two weighted segments in a horizontal container)
            node = {
                "type": "container",
                "width": {"type": "match_parent"},
                "height": {"type": "fixed", "value": 8},
                "border": {"corner_radius": 4},
                "clip_to_bounds": True,
                "background": [{"type": "solid", "color": "#E0E0E0"}],
                "items": [{
                    "type": "container",
                    "orientation": "horizontal",
                    "width": {"type": "match_parent"},
                    "height": {"type": "match_parent"},
                    "items": [
                        {
                            "type": "container",
                            "height": {"type": "match_parent"},
                            "weight": max(done, 0),
                            "background": [{"type": "solid", "color": "#1a73e8"}]
                        },
                        {
                            "type": "container",
                            "height": {"type": "match_parent"},
                            "weight": max(rest, 0),
                            "background": [{"type": "solid", "color": "#D9D9D9"}]
                        }
                    ]
                }]
            }
    except Exception:
        # If anything goes wrong, show a tiny neutral bar to avoid breaking rendering
        node = {
            "type": "container",
            "width": {"type": "match_parent"},
            "height": {"type": "fixed", "value": 8},
            "border": {"corner_radius": 4},
            "clip_to_bounds": True,
            "background": [{"type": "solid", "color": "#E0E0E0"}],
        }

    # Common wrapper with paddings
    return {
        "type": "container",
        "width": {"type": "match_parent"},
        "paddings": {"left": 16, "right": 16, "top": 8, "bottom": 8},
        "items": [node]
    }

# view wrappers (SPA)
@bp.get("/view/lesson/<int:lesson_id>")
def view_lesson(lesson_id: int):  # noqa: ARG001
    return send_from_directory(WEB_DIR, "index.html")

@bp.get("/view/lesson/slug/<string:slug>")
def view_lesson_slug(slug: str):  # noqa: ARG001
    return send_from_directory(WEB_DIR, "index.html")

# lesson by id
@bp.get("/lesson/<int:lesson_id>")
def get_lesson(lesson_id: int):
    step = request.args.get("i", default=0, type=int)

    template = UI_DIR / "pages" / "lesson.json"
    try:
        with open(template, "r", encoding="utf-8") as f:
            card = json.load(f)
        card = resolve_includes(card)
        card = apply_design_tokens(card, load_tokens("light"))
    except Exception as e:
        print("Template load error:", e)
        with open(UI_DIR / "pages" / "home.json", "r", encoding="utf-8") as f:
            home = json.load(f)
        return jsonify(resolve_includes(home))

    try:
        raw = fetch_lesson(lesson_id)
        simplified = to_divkit_lesson(raw)
        words = (simplified.get("words", []) or [])[:10]  # cap to 10 words per lesson
    except Exception as e:
        print("Strapi fetch failed:", e)
        words = []

    if not words:
        return jsonify(card)

    if step < 0: step = 0
    if step >= len(words):
        with open(UI_DIR / "pages" / "home.json", "r", encoding="utf-8") as f:
            home = json.load(f)
        return jsonify(resolve_includes(home))

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

    if random.random() < 0.5:
        left_text, right_text = correct, wrong
        left_url,  right_url  = next_url, None
    else:
        left_text, right_text = wrong, correct
        left_url,  right_url  = None, next_url

    patch_by_id(card, "word_term",  {"text": term})
    patch_by_id(card, "word_image", {
        "image_url": image_url or "https://dummyimage.com/600x600/eeeeee/aaaaaa.png?text=img",
        # тянем картинку на всю доступную ширину/высоту секции со словами
        "width":  {"type": "match_parent"},
        "height": {"type": "match_parent"},
        # вписываем изображение целиком без обрезания
        "content_mode": "scale_to_fit",
    })
    patch_by_id(card, "choice_left_text",  {"text": left_text})
    patch_by_id(card, "choice_right_text", {"text": right_text})

    patch_by_id(card, "choice_left",  {"action": {"log_id": "next_word", "url": left_url} if left_url else None})
    patch_by_id(card, "choice_right", {"action": {"log_id": "next_word", "url": right_url} if right_url else None})

    # --- progress bar (deterministic) ---
    try:
        total = min(len(words), 10) or 1
        done = min(step + 1, total)
        rest = max(total - done, 0)

        _merge_card_variables(card, {
            "total": total,
            "correct": done,
            "done": done,
            "rest": rest,
        })

        # Always build a concrete weighted bar to avoid component/ids mismatches
        _hard_set_progress_bar(card, done, total)
        print(f"[progress] lesson_id={lesson_id} step={step} done={done}/{total}")
    except Exception as e:
        print("Progress patch failed:", e)

    return jsonify(card)

# compatibility JSON endpoint to support /lesson/slug/<slug>
@bp.get("/lesson/slug/<string:slug>")
def get_lesson_by_slug_compat(slug: str):
    # Delegate to the existing handler so query params (like ?i=) keep working
    return get_lesson_by_slug_route(slug)

# lesson by slug
@bp.get("/lesson/by/<string:slug>")
def get_lesson_by_slug_route(slug: str):
    step = request.args.get("i", default=0, type=int)

    template = UI_DIR / "pages" / "lesson.json"
    try:
        with open(template, "r", encoding="utf-8") as f:
            card = json.load(f)
        card = resolve_includes(card)
        card = apply_design_tokens(card, load_tokens("light"))
    except Exception as e:
        print("Template load error (slug):", e)
        with open(UI_DIR / "pages" / "home.json", "r", encoding="utf-8") as f:
            home = json.load(f)
        return jsonify(resolve_includes(home))

    try:
        raw = get_lesson_by_slug(slug)
        simplified = to_divkit_lesson(raw)
        words = (simplified.get("words", []) or [])[:10]  # cap to 10 words per lesson
    except Exception as e:
        print("Strapi fetch failed (slug):", e)
        words = []

    if not words:
        return jsonify(card)

    if step < 0: step = 0
    if step >= len(words):
        with open(UI_DIR / "pages" / "home.json", "r", encoding="utf-8") as f:
            home = json.load(f)
        return jsonify(resolve_includes(home))

    w = words[step] or {}
    term      = (w.get("term") or "").strip()
    image_url = (w.get("image_url") or "").strip()
    if image_url.startswith("/"):
        base = os.getenv("STRAPI_URL", "http://localhost:1337").rstrip("/")
        image_url = f"{base}{image_url}"
    correct = (w.get("translation") or "").strip()
    wrong   = (w.get("distractor1") or "").strip()

    is_last  = (step + 1 >= len(words))
    next_url = "/view/home" if is_last else f"/view/lesson/slug/{slug}?i={step + 1}"

    if random.random() < 0.5:
        left_text, right_text = correct, wrong
        left_url,  right_url  = next_url, None
    else:
        left_text, right_text = wrong, correct
        left_url,  right_url  = None, next_url

    patch_by_id(card, "word_term",  {"text": term})
    patch_by_id(card, "word_image", {
        "image_url": image_url or "https://dummyimage.com/600x600/eeeeee/aaaaaa.png?text=img",
        "width":  {"type": "match_parent"},
        "height": {"type": "match_parent"},
        "content_mode": "scale_to_fit",
    })
    patch_by_id(card, "choice_left_text",  {"text": left_text})
    patch_by_id(card, "choice_right_text", {"text": right_text})
    patch_by_id(card, "choice_left",  {"action": {"log_id": "next_word", "url": left_url} if left_url else None})
    patch_by_id(card, "choice_right", {"action": {"log_id": "next_word", "url": right_url} if right_url else None})

    # --- progress bar (deterministic) ---
    try:
        total = min(len(words), 10) or 1
        done = min(step + 1, total)
        rest = max(total - done, 0)

        _merge_card_variables(card, {
            "total": total,
            "correct": done,
            "done": done,
            "rest": rest,
        })

        _hard_set_progress_bar(card, done, total)
        print(f"[progress] slug={slug} step={step} done={done}/{total}")
    except Exception as e:
        print("Progress patch failed (slug):", e)

    return jsonify(card)