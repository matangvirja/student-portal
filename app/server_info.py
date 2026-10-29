"""Identify which container served a request — used to demo the load balancer."""
import json
import os
import socket
import urllib.request
from functools import lru_cache


@lru_cache(maxsize=1)
def server_info() -> dict:
    info = {"hostname": socket.gethostname(), "task_id": None, "az": None}
    # ECS sets this env var inside every task; the endpoint returns task metadata.
    uri = os.environ.get("ECS_CONTAINER_METADATA_URI_V4")
    if uri:
        try:
            with urllib.request.urlopen(f"{uri}/task", timeout=1) as resp:
                data = json.load(resp)
            info["task_id"] = data.get("TaskARN", "").rsplit("/", 1)[-1][:12] or None
            info["az"] = data.get("AvailabilityZone")
        except Exception:
            pass
    return info
