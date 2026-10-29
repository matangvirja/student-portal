"""Cross-cutting security helpers: audit trail, client IP, safe redirects."""
from flask import current_app, request
from flask_login import current_user

from .extensions import db
from .models import AuditLog


def client_ip() -> str:
    # Behind the ALB the real client is the first entry of X-Forwarded-For.
    forwarded = request.headers.get("X-Forwarded-For", "")
    ip = forwarded.split(",")[0].strip() if forwarded else (request.remote_addr or "")
    return ip[:64]


def audit(action: str, detail: str = "", user_id=None) -> None:
    """Record an action. The caller's db.session.commit() persists it atomically with the change."""
    if user_id is None and current_user.is_authenticated:
        user_id = current_user.id
    db.session.add(AuditLog(user_id=user_id, action=action, detail=(detail or "")[:500], ip=client_ip()))
    current_app.logger.info(action, extra={"event": "audit", "action": action, "user_id": user_id})


def safe_next(target):
    """Only allow relative redirects on this site (prevents open-redirect phishing)."""
    if target and target.startswith("/") and not target.startswith("//") and "\\" not in target:
        return target
    return None
