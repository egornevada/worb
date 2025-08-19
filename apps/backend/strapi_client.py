from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

# Load environment variables once
load_dotenv()

# Base config
STRAPI_URL: str = os.getenv("STRAPI_URL", "http://localhost:1337").rstrip("/")
# Accept either STRAPI_TOKEN or STRAPI_API_TOKEN
STRAPI_TOKEN: Optional[str] = os.getenv("STRAPI_TOKEN") or os.getenv("STRAPI_API_TOKEN")

# Shared requests session
_session = requests.Session()
if STRAPI_TOKEN:
    _session.headers.update({
        "Authorization": f"Bearer {STRAPI_TOKEN}",
        "Content-Type": "application/json",
    })


def _get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Helper to GET from Strapi and return JSON (raises on HTTP errors)."""
    url = f"{STRAPI_URL}{path if path.startswith('/') else '/' + path}"
    r = _session.get(url, params=params)
    r.raise_for_status()
    return r.json()


def get_lesson(lesson_id: int) -> Dict[str, Any]:
    """Fetch one lesson by numeric id, with cover and words populated.
    Returns the *entry object* (not wrapped), i.e. shape compatible with `to_divkit_lesson`.
    """
    params = {
        # Note: `$eq` is the correct operator key
        "filters[id][$eq]": lesson_id,
        # Populate cover media and words (+word image)
        "populate[0]": "cover",
        "populate[1]": "words",
        "populate[2]": "words.image",
        # We expect exactly one match
        "pagination[pageSize]": 1,
    }
    data = _get("/api/lessons", params=params)
    items = data.get("data") or []
    if not items:
        raise LookupError(f"Lesson id={lesson_id} not found")
    # Strapi v5 returns an object directly in the list
    return items[0]


def get_lesson_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    """Fetch one lesson by slug (first match), with relations populated."""
    params = {
        "filters[slug][$eq]": slug,
        "populate[0]": "cover",
        "populate[1]": "words",
        "populate[2]": "words.image",
        "pagination[pageSize]": 1,
    }
    data = _get("/api/lessons", params=params)
    items = data.get("data") or []
    return items[0] if items else None


def to_divkit_lesson(lesson_entry: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a Strapi lesson entry (with populated relations) to a compact
    structure that our Flask routes can further map into DivKit JSON.

    Supports both Strapi v4 shape (entry['attributes'] + media under .data.attributes)
    and Strapi v5 shape (attributes flattened at top-level, media/relations returned directly).
    """
    # Strapi may return either a wrapped object (v4) or a plain entry (v5)
    entry = lesson_entry.get("data") if isinstance(lesson_entry, dict) and "data" in lesson_entry else lesson_entry
    if not entry:
        return {}

    # In v4, attributes live under entry["attributes"]. In v5 they're flattened.
    attrs = entry.get("attributes") or entry

    # --- Cover image URL ---
    cover_url: Optional[str] = None
    cover = attrs.get("cover")
    if isinstance(cover, dict):
        # v5: cover is a dict with `url` (or occasionally nested under `attributes`)
        cover_url = cover.get("url") or cover.get("attributes", {}).get("url")
        # v4: cover is { data: { attributes: { url } } }
        if not cover_url and "data" in cover:
            cover_url = (cover.get("data") or {}).get("attributes", {}).get("url")

    # --- Related words ---
    words: List[Dict[str, Any]] = []
    rel = attrs.get("words")
    # v5: populated many-to-many returns a list of word entries
    # v4: populated relation returns { data: [ ... ] }
    if isinstance(rel, list):
        rel_items = rel
    elif isinstance(rel, dict):
        rel_items = rel.get("data") or []
    else:
        rel_items = []

    for w in rel_items:
        wa = w.get("attributes") or w  # v4 vs v5
        # word image (optional)
        image_url: Optional[str] = None
        img = wa.get("image")
        if isinstance(img, dict):
            image_url = img.get("url") or img.get("attributes", {}).get("url")
            if not image_url and "data" in img:
                image_url = (img.get("data") or {}).get("attributes", {}).get("url")
        words.append({
            "term": wa.get("term"),
            "translation": wa.get("translation"),
            "distractor1": wa.get("distractor1"),
            "image_url": image_url,
        })

    return {
        "id": entry.get("id"),
        "title": attrs.get("title"),
        "slug": attrs.get("slug"),
        "cover_url": cover_url,
        "words": words,
    }


if __name__ == "__main__":
    # Simple manual test runner
    test_id = os.getenv("TEST_LESSON_ID")
    test_slug = os.getenv("TEST_LESSON_SLUG")

    try:
        if test_id:
            raw = get_lesson(int(test_id))
        elif test_slug:
            raw = get_lesson_by_slug(test_slug) or {}
        else:
            raise SystemExit("Set TEST_LESSON_ID or TEST_LESSON_SLUG to test.")

        print("Raw lesson keys:", list((raw or {}).keys()))
        simplified = to_divkit_lesson(raw)
        import json
        print(json.dumps(simplified, ensure_ascii=False, indent=2))
    except Exception as e:
        print("Strapi client test failed:", e)
