"""Structured JSON logs + request IDs + security headers.

Every log line is one JSON object, so CloudWatch Logs Insights can query fields directly, e.g.
    fields @timestamp, path, status, duration_ms | filter event = "http_request" and status >= 500
"""
import json
import logging
import sys
import time
import uuid
from datetime import datetime, timezone

from flask import g, has_request_context, request
from flask_login import current_user

_EXTRA_FIELDS = ("event", "method", "path", "status", "duration_ms", "user_id", "role", "action")


class JsonFormatter(logging.Formatter):
    def format(self, record):
        payload = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "msg": record.getMessage(),
        }
        if has_request_context():
            payload["request_id"] = getattr(g, "request_id", None)
        for field in _EXTRA_FIELDS:
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(app):
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    app.logger.handlers = [handler]
    app.logger.setLevel(logging.INFO)
    app.logger.propagate = False

    @app.before_request
    def _start_timer():
        # The ALB adds X-Amzn-Trace-Id; reuse it so logs line up with ALB access logs.
        g.request_id = request.headers.get("X-Amzn-Trace-Id") or uuid.uuid4().hex
        g.t0 = time.perf_counter()

    @app.after_request
    def _finish(response):
        if request.path != "/health" and not request.path.startswith("/static/"):
            authed = current_user.is_authenticated
            app.logger.info("request", extra={
                "event": "http_request",
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "duration_ms": round((time.perf_counter() - g.get("t0", time.perf_counter())) * 1000, 1),
                "user_id": current_user.id if authed else None,
                "role": current_user.role if authed else None,
            })
        response.headers["X-Request-ID"] = g.get("request_id", "")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response
