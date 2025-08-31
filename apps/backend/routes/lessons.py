from __future__ import annotations
from flask import Blueprint, jsonify, send_from_directory, request
from core.paths import UI_DIR, WEB_DIR
from core.ui import resolve_includes, apply_design_tokens, load_tokens, patch_by_id
from strapi_client import get_lesson as fetch_lesson, get_lesson_by_slug, to_divkit_lesson
from pathlib import Path
import json, os, random

bp = Blueprint("lessons", __name__)

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
        words = simplified.get("words", [])
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
        "scale": "fit",
        "content_mode": "scale_to_fit",
    })
    patch_by_id(card, "choice_left_text",  {"text": left_text})
    patch_by_id(card, "choice_right_text", {"text": right_text})

    patch_by_id(card, "choice_left",  {"action": {"log_id": "next_word", "url": left_url} if left_url else None})
    patch_by_id(card, "choice_right", {"action": {"log_id": "next_word", "url": right_url} if right_url else None})

    return jsonify(card)

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
        words = simplified.get("words", [])
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
        "scale": "fit",
        "content_mode": "scale_to_fit",
    })
    patch_by_id(card, "choice_left_text",  {"text": left_text})
    patch_by_id(card, "choice_right_text", {"text": right_text})
    patch_by_id(card, "choice_left",  {"action": {"log_id": "next_word", "url": left_url} if left_url else None})
    patch_by_id(card, "choice_right", {"action": {"log_id": "next_word", "url": right_url} if right_url else None})

    return jsonify(card)