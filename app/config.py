"""App configuration, read from environment variables (12-factor style).

On AWS (ECS Fargate) the task definition injects:
  DB_HOST, DB_PORT, DB_NAME                              -> from the RDS instance
  DB_USER, DB_PASSWORD, SECRET_KEY, TEACHER_INVITE_CODE  -> from AWS Secrets Manager
  S3_BUCKET, AWS_REGION, APP_TIMEZONE                    -> from the CloudFormation stack
Locally, with none of these set, the app falls back to SQLite + a local uploads folder.
"""
import os
from urllib.parse import quote_plus


def _database_url(instance_path: str) -> str:
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]

    host = os.environ.get("DB_HOST")
    if host:
        user = quote_plus(os.environ["DB_USER"])
        password = quote_plus(os.environ["DB_PASSWORD"])
        port = os.environ.get("DB_PORT", "5432")
        name = os.environ.get("DB_NAME", "portal")
        # RDS for PostgreSQL 15+ enforces SSL by default.
        sslmode = os.environ.get("DB_SSLMODE", "require")
        return f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{name}?sslmode={sslmode}"

    return "sqlite:///" + os.path.join(instance_path, "portal.db")


def _flag(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).lower() == "true"


def build_config(instance_path: str) -> dict:
    return {
        "SECRET_KEY": os.environ.get("SECRET_KEY", "dev-only-insecure-key"),
        # Faculty accounts can only be created with this code (shared by the department).
        "TEACHER_INVITE_CODE": os.environ.get("TEACHER_INVITE_CODE", "FACULTY-DEV"),
        "APP_TIMEZONE": os.environ.get("APP_TIMEZONE", "Asia/Kolkata"),
        "SQLALCHEMY_DATABASE_URI": _database_url(instance_path),
        "SQLALCHEMY_ENGINE_OPTIONS": {"pool_pre_ping": True},
        "MAX_CONTENT_LENGTH": 10 * 1024 * 1024,  # 10 MB upload limit
        "S3_BUCKET": os.environ.get("S3_BUCKET") or None,
        "AWS_REGION": os.environ.get("AWS_REGION", "ap-south-1"),
        "UPLOAD_DIR": os.environ.get("UPLOAD_DIR", os.path.join(instance_path, "uploads")),
        "ENABLE_LOAD_ENDPOINT": _flag("ENABLE_LOAD_ENDPOINT"),
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        # Set COOKIE_SECURE=true once HTTPS (ACM certificate) is on the load balancer.
        "SESSION_COOKIE_SECURE": _flag("COOKIE_SECURE"),
        "REMEMBER_COOKIE_SECURE": _flag("COOKIE_SECURE"),
        "REMEMBER_COOKIE_HTTPONLY": True,
    }
