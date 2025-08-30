from __future__ import annotations
from flask import Blueprint, request

bp = Blueprint("log", __name__)

@bp.post("/log")
def log_action_post():
    data = request.get_json(silent=True) or {}
    print(">> DivKit action (POST):", data)
    return {"ok": True}