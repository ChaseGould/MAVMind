"""Run the vehicle service in a background thread for integration tests."""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from pathlib import Path

import httpx
import uvicorn
import yaml

from conftest import free_port


def write_profile(tmp: Path, name: str, source: dict) -> str:
    path = tmp / f"{name}.yaml"
    path.write_text(yaml.safe_dump({"name": name, "description": "test", "source": source}))
    return str(path)


@contextmanager
def serve(app, port: int | None = None):
    port = port or free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", ws="websockets-sansio")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            if httpx.get(url + "/health", timeout=0.5).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.05)
    else:
        raise RuntimeError("server did not start")
    try:
        yield url
    finally:
        server.should_exit = True
        thread.join(10)


def wait_for(pred, timeout: float = 10.0, interval: float = 0.05):
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = pred()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("condition not met in time")
