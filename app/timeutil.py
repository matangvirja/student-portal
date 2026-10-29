"""Time handling.

All timestamps are stored in UTC. They are converted to the institute's local time zone
(APP_TIMEZONE, default Asia/Kolkata) only when shown to users or read from a form.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import current_app


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(dt):
    """SQLite returns naive datetimes; PostgreSQL returns aware ones. Normalise both to aware UTC."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def local_tz() -> ZoneInfo:
    return ZoneInfo(current_app.config["APP_TIMEZONE"])


def to_local(dt):
    return as_utc(dt).astimezone(local_tz()) if dt else None


def parse_local(value: str) -> datetime:
    """Parse an <input type="datetime-local"> value entered in local time; return aware UTC."""
    naive = datetime.strptime(value.strip(), "%Y-%m-%dT%H:%M")
    return naive.replace(tzinfo=local_tz()).astimezone(timezone.utc)


def due_in(dt) -> str:
    """Human-friendly relative time: 'in 3 days', '5 h ago'."""
    seconds = (as_utc(dt) - utcnow()).total_seconds()
    past, s = seconds < 0, abs(seconds)
    if s < 3600:
        text = f"{max(int(s // 60), 1)} min"
    elif s < 86400:
        text = f"{int(s // 3600)} h"
    else:
        days = int(s // 86400)
        text = f"{days} day{'s' if days != 1 else ''}"
    return f"{text} ago" if past else f"in {text}"
