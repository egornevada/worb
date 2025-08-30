from __future__ import annotations
from pathlib import Path
from typing import Any, Optional, Dict
import json
cat > apps/backend/core/json_utils.py << 'PY'
from __future__ import annotations
from pathlib import Path
from typing import Any, Optional, Dict
import json

from .paths import UI_DIR

def _resolve_includes(node: Any, *, base_dir: Optional[Path] = None) -> Any:
    """
    Разворачивает {"$include": "<path>.json"} рекурсивно.
    Путь "components/..."/"pages/..." ищется от корня UI_DIR.
    Относительный путь — от base_dir (папка файла, где встретился include).
    """
    if base_dir is None:
        base_dir = UI_DIR

    if isinstance(node, dict):
        inc = node.get("$include")
        if isinstance(inc, str):
            inc_str = inc.lstrip("/")
            if inc_str.startswith(("components/", "pages/")):
                inc_path = (UI_DIR / inc_str).resolve()
            else:
                inc_path = (base_dir / inc_str).resolve()

            # безопасность: не выходим за пределы UI_DIR
            try:
                inside = inc_path.is_relative_to(UI_DIR)  # py3.9+
            except AttributeError:
                inside = str(inc_path).startswith(str(UI_DIR))
            if not inside:
                raise ValueError(f"$include path escapes UI dir: {inc_path}")

            with open(inc_path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            return _resolve_includes(loaded, base_dir=inc_path.parent)

        # обычный словарь
        return {k: _resolve_includes(v, base_dir=base_dir) for k, v in node.items()}

    if isinstance(node, list):
        return [_resolve_includes(x, base_dir=base_dir) for x in node]

    return node

def _patch_by_id(tree: Any, target_id: str, updates: Dict[str, Any]) -> None:
    """
    Ищет узлы вида {"id": "<target_id>", ...} и применяет updates in-place.
    Особый случай: если updates содержит {"action": None} — удаляем ключ action.
    """
    if isinstance(tree, dict):
        if tree.get("id") == target_id:
            for k, v in updates.items():
                if k == "action" and v is None:
                    tree.pop("action", None)
                else:
                    tree[k] = v
        for v in list(tree.values()):
            _patch_by_id(v, target_id, updates)

    elif isinstance(tree, list):
        for item in tree:
            _patch_by_id(item, target_id, updates)

__all__ = ["_resolve_includes", "_patch_by_id"]
