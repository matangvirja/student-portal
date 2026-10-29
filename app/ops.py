"""Operational endpoints: health checks for the ALB, and demo endpoints for load balancing / scaling."""
import time

from flask import Blueprint, abort, current_app, jsonify, request
from sqlalchemy import text

from .extensions import db
from .server_info import server_info

bp = Blueprint("ops", __name__)


@bp.get("/health")
def health():
    # Liveness check used by the ALB target group. Deliberately does NOT touch the database,
    # so a short RDS blip doesn't make the load balancer drain every task at once.
    return jsonify(status="ok")


@bp.get("/health/db")
def health_db():
    try:
        started = time.perf_counter()
        db.session.execute(text("SELECT 1"))
        return jsonify(status="ok", database="reachable",
                       latency_ms=round((time.perf_counter() - started) * 1000, 2))
    except Exception:
        current_app.logger.exception("Database health check failed")
        return jsonify(status="error", database="unreachable"), 503


@bp.get("/api/server")
def api_server():
    """curl this in a loop to watch the ALB spread requests across tasks and AZs."""
    return jsonify(server_info())


@bp.get("/load")
def load():
    """Burns CPU for ?ms= milliseconds so auto scaling can be triggered on demand."""
    if not current_app.config["ENABLE_LOAD_ENDPOINT"]:
        abort(404)
    ms = min(max(request.args.get("ms", 200, type=int), 1), 2000)
    deadline = time.perf_counter() + ms / 1000
    work = 0
    while time.perf_counter() < deadline:
        work += sum(i * i for i in range(1000))
    return jsonify(burned_ms=ms, server=server_info())
