# apps/backend/app.py
from flask import Flask
from importlib import import_module


def create_app() -> Flask:
    """Create Flask app and register blueprints.
    Держим app.py минимальным: все роуты в routes/*.py, утилиты в core/*.
    """
    app = Flask(__name__, static_folder=None)

    # отключаем кэш браузера для JSON во время разработки
    @app.after_request
    def _no_cache(resp):
        resp.headers.setdefault("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        resp.headers.setdefault("Pragma", "no-cache")
        return resp

    # Helper: try several attribute names to find a blueprint object in a module
    def _bp(mod_name: str, *candidates):
        mod = import_module(mod_name)
        for name in candidates:
            obj = getattr(mod, name, None)
            if obj is not None:
                return obj
        raise ImportError(f"{mod_name} has no blueprint among {candidates}")

    # ---- Регистрируем блюпринты ----
    spa_bp = _bp('routes.spa', 'bp', 'spa_bp')              # /, /client.js, /view/*, /page/*
    health_bp = _bp('routes.health', 'bp', 'health_bp')     # /health
    home_bp = _bp('routes.home', 'bp', 'home_bp')           # /home, /test, /test.json
    lessons_bp = _bp('routes.lessons', 'bp', 'lessons_bp')  # /lesson/<id>, /lesson/slug/<slug>, /<name>.json
    log_bp = _bp('routes.log', 'bp', 'log_bp')              # /log

    app.register_blueprint(spa_bp)
    app.register_blueprint(health_bp)
    app.register_blueprint(home_bp)
    app.register_blueprint(lessons_bp)
    app.register_blueprint(log_bp)

    return app


# WSGI entry
app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5050, use_reloader=False)