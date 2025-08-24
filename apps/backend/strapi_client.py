# apps/backend/strapi_client.py
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

# ---- env / base config -------------------------------------------------------
load_dotenv()

STRAPI_URL: str = os.getenv("STRAPI_URL", "http://localhost:1337").rstrip("/")
# Поддержим и STRAPI_TOKEN, и STRAPI_API_TOKEN
STRAPI_TOKEN: Optional[str] = os.getenv("STRAPI_TOKEN") or os.getenv("STRAPI_API_TOKEN")

_session = requests.Session()
_session.headers.setdefault("Accept", "application/json")
if STRAPI_TOKEN:
    _session.headers.update({
        "Authorization": f"Bearer {STRAPI_TOKEN}",
        "Content-Type": "application/json",
    })


# ---- helpers -----------------------------------------------------------------
def _get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """GET в Strapi + .json() (бросает HTTPError на 4xx/5xx)."""
    url = f"{STRAPI_URL}{path if path.startswith('/') else '/' + path}"
    r = _session.get(url, params=params, timeout=15)
    r.raise_for_status()
    return r.json()

def _abs_url(url: Optional[str]) -> str:
    """Сделать url абсолютным, если начинается с '/'."""
    if not url:
        return ""
    return f"{STRAPI_URL}{url}" if isinstance(url, str) and url.startswith("/") else url

def _attrs(node: Any) -> Dict[str, Any]:
    """Вернуть attributes для v4 ({data:{attributes}}) и v5 (плоская)."""
    if not isinstance(node, dict):
        return {}
    if "data" in node and isinstance(node.get("data"), dict):
        # v4 relation/media
        return (node.get("data") or {}).get("attributes") or {}
    # v5
    return node.get("attributes") or node

def _media_url(node: Any) -> str:
    """Достать url из media (v4/v5) и вернуть абсолютный."""
    if not node or not isinstance(node, dict):
        return ""
    url = node.get("url") or (node.get("attributes") or {}).get("url")
    if not url and "data" in node:
        inner = node.get("data") or {}
        if isinstance(inner, dict):
            url = (inner.get("attributes") or {}).get("url")
    return _abs_url(url)


# ---- lessons -----------------------------------------------------------------
def get_lesson(lesson_id: int) -> Dict[str, Any]:
    """Урок по id (title, slug, cover, category, words с image+level)."""
    params = {
        "filters[id][$eq]": lesson_id,
        "pagination[pageSize]": 1,

        "fields[0]": "title",
        "fields[1]": "slug",

        "populate[cover]": "true",
        "populate[category]": "true",

        "populate[words][fields][0]": "term",
        "populate[words][fields][1]": "translation",
        "populate[words][fields][2]": "distractor1",
        "populate[words][fields][3]": "level",
        "populate[words][populate]": "image",
    }
    data = _get("/api/lessons", params=params)
    items = data.get("data") or []
    if not items:
        raise LookupError(f"Lesson id={lesson_id} not found")
    return items[0]

def get_lesson_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    """Урок по slug (те же populate)."""
    params = {
        "filters[slug][$eq]": slug,
        "pagination[pageSize]": 1,

        "fields[0]": "title",
        "fields[1]": "slug",

        "populate[cover]": "true",
        "populate[category]": "true",

        "populate[words][fields][0]": "term",
        "populate[words][fields][1]": "translation",
        "populate[words][fields][2]": "distractor1",
        "populate[words][fields][3]": "level",
        "populate[words][populate]": "image",
    }
    data = _get("/api/lessons", params=params)
    items = data.get("data") or []
    return items[0] if items else None

def to_divkit_lesson(lesson_entry: Dict[str, Any]) -> Dict[str, Any]:
    """Превратить entry из Strapi в компактный словарь для DivKit."""
    entry = lesson_entry.get("data") if isinstance(lesson_entry, dict) and "data" in lesson_entry else lesson_entry
    if not entry:
        return {"words": []}

    attrs = entry.get("attributes") or entry  # v4 vs v5

    cover_url = _media_url(attrs.get("cover"))

    cat_node = attrs.get("category")
    cat_attrs = _attrs(cat_node) if cat_node else {}
    category = {
        "title": (cat_attrs.get("title") or "").strip() if isinstance(cat_attrs, dict) else "",
        "slug": (cat_attrs.get("slug") or "").strip() if isinstance(cat_attrs, dict) else "",
        "order": cat_attrs.get("order") if isinstance(cat_attrs, dict) else 0,
        "icon_url": _media_url(cat_attrs.get("icon")) if isinstance(cat_attrs, dict) else "",
    }

    # words
    words_rel = attrs.get("words") or {}
    if isinstance(words_rel, list):
        rel_items = words_rel
    elif isinstance(words_rel, dict):
        rel_items = words_rel.get("data") or []
    else:
        rel_items = []

    words: List[Dict[str, Any]] = []
    for w in rel_items:
        wa = _attrs(w)
        words.append({
            "term": (wa.get("term") or "").strip(),
            "translation": (wa.get("translation") or "").strip(),
            "distractor1": (wa.get("distractor1") or "").strip(),
            "level": (wa.get("level") or "").strip(),
            "image_url": _media_url(wa.get("image")),
        })

    return {
        "id": entry.get("id"),
        "title": (attrs.get("title") or "").strip(),
        "slug": (attrs.get("slug") or "").strip(),
        "cover_url": cover_url,
        "category": category,
        "words": words,
    }


# ---- categories (для Home) ---------------------------------------------------
def get_categories() -> Dict[str, Any]:
    """Сырые категории из Strapi с нужными полями (для внутреннего использования)."""
    params = {
        "fields[0]": "title",
        "fields[1]": "slug",
        "fields[2]": "order",
        "populate[icon]": "true",

        "populate[lessons][fields][0]": "title",
        "populate[lessons][fields][1]": "slug",
        "populate[lessons][populate]": "cover",

        "sort[0]": "order:asc",
        "pagination[pageSize]": 100,
    }
    return _get("/api/categories", params=params)

def list_categories_with_lessons() -> List[Dict[str, Any]]:
    """Готовые категории для Home (устойчивая форма, абсолютные URL)."""
    raw = get_categories()
    data = raw.get("data") or []

    categories: List[Dict[str, Any]] = []

    for item in data:
        # v4: {id, attributes:{...}}, v5: плоская
        if not isinstance(item, dict):
            continue
        attrs = item.get("attributes") or item

        icon_url = _media_url(attrs.get("icon"))
        title = (attrs.get("title") or "").strip()
        slug = (attrs.get("slug") or "").strip()
        order = attrs.get("order") or 0

        # lessons relation
        lessons_rel = attrs.get("lessons") or {}
        if isinstance(lessons_rel, list):
            lesson_nodes = lessons_rel
        elif isinstance(lessons_rel, dict):
            lesson_nodes = lessons_rel.get("data") or []
        else:
            lesson_nodes = []

        lessons: List[Dict[str, Any]] = []
        for ln in lesson_nodes:
            la = _attrs(ln)
            lessons.append({
                "id": ln.get("id") if isinstance(ln, dict) else None,
                "title": (la.get("title") or "").strip(),
                "slug": (la.get("slug") or "").strip(),
                "cover_url": _media_url(la.get("cover")),
            })

        categories.append({
            "id": item.get("id") if isinstance(item, dict) else None,
            "title": title,
            "slug": slug,
            "order": order,
            "icon_url": icon_url,
            "lessons": lessons,
        })

    # финальная сортировка на всякий пожарный
    categories.sort(key=lambda c: (c.get("order") or 0, c.get("title") or ""))
    return categories


# ---- tiny manual test --------------------------------------------------------
if __name__ == "__main__":
    # Запуск: TEST_LESSON_ID=2 python strapi_client.py
    test_id = os.getenv("TEST_LESSON_ID")
    test_slug = os.getenv("TEST_LESSON_SLUG")

    try:
        if test_id:
            raw = get_lesson(int(test_id))
            from pprint import pprint
            print("Lesson ok"); pprint(to_divkit_lesson(raw))
        elif test_slug:
            raw = get_lesson_by_slug(test_slug) or {}
            from pprint import pprint
            print("Lesson by slug ok"); pprint(to_divkit_lesson(raw))
        else:
            cats = list_categories_with_lessons()
            from pprint import pprint
            print("Categories ok"); pprint(cats[:2])
    except Exception as e:
        print("Strapi client test failed:", e)