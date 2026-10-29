"""Validation shared by every upload path (materials, assignment briefs, submissions)."""
import os
import uuid

from werkzeug.utils import secure_filename

ALLOWED_EXTENSIONS = {
    "pdf", "txt", "md", "csv", "png", "jpg", "jpeg",
    "doc", "docx", "ppt", "pptx", "xls", "xlsx", "zip", "ipynb", "py", "java", "c", "cpp",
}


class UploadError(ValueError):
    pass


def read_upload(file):
    """Validate a werkzeug FileStorage. Returns (safe_filename, size_bytes)."""
    if file is None or not file.filename:
        raise UploadError("Choose a file to upload.")

    filename = secure_filename(file.filename)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if not filename or ext not in ALLOWED_EXTENSIONS:
        raise UploadError(
            "That file type isn't allowed. Use PDF, Office, image, text, code, notebook or ZIP files."
        )

    file.stream.seek(0, os.SEEK_END)
    size = file.stream.tell()
    file.stream.seek(0)
    if size == 0:
        raise UploadError("That file is empty.")
    return filename, size


def build_key(prefix: str, filename: str) -> str:
    # A random segment keeps keys unguessable and avoids overwriting same-named files.
    return f"{prefix}/{uuid.uuid4().hex}/{filename}"
