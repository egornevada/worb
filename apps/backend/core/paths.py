from pathlib import Path
CORE_DIR = Path(__file__).resolve().parent          # apps/backend/core
BACKEND_DIR = CORE_DIR.parent                       # apps/backend
APPS_DIR = BACKEND_DIR.parent                       # apps
ROOT_DIR = APPS_DIR.parent                          # проект (Worb)

WEB_DIR = APPS_DIR / "web"                          # apps/web
UI_DIR = WEB_DIR / "ui"                             # apps/web/ui

__all__ = ["ROOT_DIR", "APPS_DIR", "BACKEND_DIR", "CORE_DIR", "WEB_DIR", "UI_DIR"]
