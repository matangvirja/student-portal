"""Application factory.

Blueprints (one per bounded context):
  auth     public landing page, signup (student / faculty), login, logout
  teacher  /teacher/*  Faculty Console  (role-guarded)
  student  /student/*  Student Hub      (role-guarded)
  files    /files/*    downloads with per-object authorization
  ops      /health, /health/db, /api/server, /load  (infrastructure & demo endpoints)
"""
import os

from flask import Flask, render_template

from .config import build_config
from .extensions import csrf, db, login_manager
from .logging_setup import configure_logging


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)

    app.config.update(build_config(app.instance_path))
    if test_config:
        app.config.update(test_config)

    configure_logging(app)
    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please sign in to continue."
    login_manager.login_message_category = "info"

    from . import models  # noqa: F401  (registers models + user_loader)
    from .auth import bp as auth_bp
    from .cli import register_cli
    from .files import bp as files_bp
    from .ops import bp as ops_bp
    from .server_info import server_info
    from .student import bp as student_bp
    from .teacher import bp as teacher_bp
    from .timeutil import due_in, to_local

    for bp in (auth_bp, teacher_bp, student_bp, files_bp, ops_bp):
        app.register_blueprint(bp)
    register_cli(app)

    @app.context_processor
    def inject_globals():
        # Footer shows which ECS task / AZ served the page (load-balancing demo).
        return {"server": server_info()}

    @app.template_filter("localdt")
    def localdt(dt, fmt="%d %b %Y, %I:%M %p"):
        return to_local(dt).strftime(fmt) if dt else "—"

    app.add_template_filter(due_in, "due_in")

    @app.template_filter("filesize")
    def filesize(num):
        num = float(num or 0)
        for unit in ("B", "KB", "MB", "GB"):
            if num < 1024 or unit == "GB":
                return f"{num:.0f} {unit}" if unit == "B" else f"{num:.1f} {unit}"
            num /= 1024

    @app.template_filter("marks")
    def marks(value):
        return "—" if value is None else f"{value:g}"

    def error_page(code, title, message):
        return render_template("errors/error.html", code=code, title=title, message=message), code

    app.register_error_handler(403, lambda e: error_page(
        403, "Not available for your role", "This area belongs to a different kind of account."))
    app.register_error_handler(404, lambda e: error_page(
        404, "Page not found", "It may have been removed, or you may not have access to it."))
    app.register_error_handler(413, lambda e: error_page(
        413, "File too large", "Uploads are limited to 10 MB."))

    with app.app_context():
        try:
            db.create_all()
        except Exception:  # another task may be creating the tables at the same moment
            app.logger.exception("Could not create tables on startup")

    return app
