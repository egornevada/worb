from __future__ import annotations
from pathlib import Path
from typing import Any, Optional, Dict, List
import json
from copy import deepcopy

from .paths import UI_DIR


# ------------------------- small helpers -------------------------

def _is_inside(child: Path, base: Path) -> bool:
    """True if `child` is inside `base` (protection from path escape)."""
    try:
        return child.resolve().is_relative_to(base.resolve())  # py3.9+
    except AttributeError:
        return str(child.resolve()).startswith(str(base.resolve()))


def _load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _patch_by_id(tree: Any, target_id: str, updates: Dict[str, Any], unset: List[str] | None = None) -> None:
    """Modify all nodes with {"id": target_id} in-place.
    - set keys from `updates`
    - remove keys listed in `unset`
    """
    if unset is None:
        unset = []

    if isinstance(tree, dict):
        if tree.get("id") == target_id:
            for k in unset:
                tree.pop(k, None)
            for k, v in updates.items():
                tree[k] = v
        for v in list(tree.values()):
            _patch_by_id(v, target_id, updates, unset)

    elif isinstance(tree, list):
        for item in tree:
            _patch_by_id(item, target_id, updates, unset)


# ------------------------- include resolver ----------------------

def _resolve_includes(node: Any, *, base_dir: Optional[Path] = None) -> Any:
    """Expand `$include` recursively.

    Forms supported:
      1) String include:  {"$include": "/components/lesson_card.json"}
      2) Object include:  {"$include": {"path": "/components/lesson_card.json",
                                          "patch": [{"id":"...","set":{...},"unset":[...] }],
                                          "state_id": "1",            # optional state choose for type:"state"
                                          "flatten_state": true,        # inline chosen state's `div`
                                          "keep_state": false }}        # keep wrapper instead of inlining
    """
    if base_dir is None:
        base_dir = UI_DIR

    # dict node
    if isinstance(node, dict):
        if "$include" in node:
            inc = node["$include"]

            # --- A) string include ---
            if isinstance(inc, str):
                inc_str = inc.lstrip("/")
                if inc_str.startswith(("components/", "pages/")):
                    inc_path = (UI_DIR / inc_str).resolve()
                else:
                    inc_path = (base_dir / inc_str).resolve()

                if not _is_inside(inc_path, UI_DIR):
                    raise ValueError(f"$include path escapes UI dir: {inc_path}")

                loaded = _load_json(inc_path)
                return _resolve_includes(loaded, base_dir=inc_path.parent)

            # --- B) object include with optional patch/state handling ---
            if isinstance(inc, dict):
                inc_path_str = (inc.get("path") or inc.get("src") or inc.get("file") or "").lstrip("/")
                if not inc_path_str:
                    raise ValueError("$include object must contain 'path'/'src'/'file'")

                if inc_path_str.startswith(("components/", "pages/")):
                    inc_path = (UI_DIR / inc_path_str).resolve()
                else:
                    inc_path = (base_dir / inc_path_str).resolve()

                if not _is_inside(inc_path, UI_DIR):
                    raise ValueError(f"$include path escapes UI dir: {inc_path}")

                loaded = _load_json(inc_path)
                loaded = _resolve_includes(loaded, base_dir=inc_path.parent)

                # --- optional patches ---
                patches = inc.get("patch") or inc.get("patches") or []
                if isinstance(patches, dict):
                    patches = [patches]
                for patch in patches:
                    if not isinstance(patch, dict):
                        continue
                    target_id = patch.get("id")
                    set_map = patch.get("set") or patch.get("update") or {}
                    unset = patch.get("unset") or []
                    if target_id:
                        _patch_by_id(loaded, target_id, set_map, unset)
                    elif isinstance(loaded, dict):
                        for k in unset:
                            loaded.pop(k, None)
                        for k, v in set_map.items():
                            loaded[k] = v

                # --- state components: choose state and optionally inline ---
                req_sid = inc.get("state_id", None)
                keep_wrapper = bool(inc.get("keep_state") or inc.get("keep_wrapper"))
                flatten = bool(inc.get("flatten_state") or inc.get("unwrap") or inc.get("inline")) and not keep_wrapper

                if isinstance(loaded, dict) and loaded.get("type") == "state":
                    states = loaded.get("states")
                    if isinstance(states, list) and states:
                        def sid_of(s: Any) -> Any:
                            return s.get("state_id") if isinstance(s, dict) else None

                        chosen = None
                        if req_sid is not None:
                            req_sid_str = str(req_sid)
                            chosen = next((s for s in states if str(sid_of(s)) == req_sid_str), None)
                        if chosen is None:
                            cur = loaded.get("state_id")
                            if cur is not None:
                                cur_str = str(cur)
                                chosen = next((s for s in states if str(sid_of(s)) == cur_str), None)
                        if chosen is None:
                            chosen = states[0] if isinstance(states[0], dict) else None

                        if chosen is not None:
                            chosen_sid = sid_of(chosen)
                            if chosen_sid is not None:
                                loaded["state_id"] = chosen_sid
                            try:
                                idx = states.index(chosen)
                            except ValueError:
                                idx = -1
                            if idx > 0:
                                states.insert(0, states.pop(idx))

                            if flatten and "div" in chosen and isinstance(chosen["div"], (dict, list)):
                                return _resolve_includes(deepcopy(chosen["div"]), base_dir=inc_path.parent)

                    return loaded

        # regular dict: recurse
        return {k: _resolve_includes(v, base_dir=base_dir) for k, v in node.items()}

    # list node
    if isinstance(node, list):
        return [_resolve_includes(x, base_dir=base_dir) for x in node]

    # scalars
    return node


__all__ = ["_resolve_includes", "_patch_by_id"]
