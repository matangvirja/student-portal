"""Object storage abstraction: Amazon S3 when S3_BUCKET is set, otherwise a local folder.

The rest of the app only calls save / download_response / delete, so the storage
backend can be swapped without touching business logic.
"""
import os
import shutil

import boto3
from botocore.config import Config
from flask import current_app, redirect, send_file

_s3_client = None
PRESIGNED_URL_TTL_SECONDS = 300


def _s3():
    global _s3_client
    if _s3_client is None:
        # On ECS, credentials come automatically from the task IAM role (no keys in code).
        _s3_client = boto3.client(
            "s3",
            region_name=current_app.config["AWS_REGION"],
            config=Config(signature_version="s3v4", retries={"max_attempts": 5, "mode": "adaptive"}),
        )
    return _s3_client


def using_s3() -> bool:
    return bool(current_app.config.get("S3_BUCKET"))


def _local_path(key: str) -> str:
    base = os.path.abspath(current_app.config["UPLOAD_DIR"])
    path = os.path.abspath(os.path.join(base, key))
    if not path.startswith(base + os.sep):  # path traversal guard
        raise ValueError("Invalid storage key")
    return path


def save(fileobj, key: str, content_type: str = None) -> None:
    if using_s3():
        _s3().upload_fileobj(
            fileobj,
            current_app.config["S3_BUCKET"],
            key,
            ExtraArgs={
                "ContentType": content_type or "application/octet-stream",
                "ServerSideEncryption": "AES256",
            },
        )
    else:
        path = _local_path(key)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as out:
            shutil.copyfileobj(fileobj, out)


def download_response(key: str, download_name: str):
    if using_s3():
        # Short-lived presigned URL: the browser downloads straight from S3 and the
        # bucket stays private. App servers never stream large files themselves.
        safe_name = download_name.replace('"', "")
        url = _s3().generate_presigned_url(
            "get_object",
            Params={
                "Bucket": current_app.config["S3_BUCKET"],
                "Key": key,
                "ResponseContentDisposition": f'attachment; filename="{safe_name}"',
            },
            ExpiresIn=PRESIGNED_URL_TTL_SECONDS,
        )
        return redirect(url)
    return send_file(_local_path(key), as_attachment=True, download_name=download_name)


def delete(key: str) -> None:
    if not key:
        return
    if using_s3():
        _s3().delete_object(Bucket=current_app.config["S3_BUCKET"], Key=key)
    else:
        try:
            os.remove(_local_path(key))
        except FileNotFoundError:
            pass
