"""Servers for tests that drive the frontend: a uvicorn app in a thread and
the Vite dev server in a subprocess, proxying backend routes to it."""

import os
import signal
import socket
import subprocess
import threading
import time
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, cast

import uvicorn
from fastapi import FastAPI
from uvicorn.config import WSProtocolType

ROOT = Path(__file__).resolve().parents[2]
VITE = ROOT / "frontend" / "node_modules" / ".bin" / "vite"
READY_TIMEOUT_S = 90  # the first start pre-bundles the frontend's dependencies


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return cast(int, sock.getsockname()[1])


def wait_for(url: str, process: "subprocess.Popen[bytes] | None" = None) -> None:
    deadline = time.monotonic() + READY_TIMEOUT_S
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise RuntimeError(f"{url}: the server exited with {process.returncode}")
        try:
            with urllib.request.urlopen(url, timeout=2):
                return
        except OSError:
            time.sleep(0.2)
    raise TimeoutError(f"{url} did not come up within {READY_TIMEOUT_S} s")


@contextmanager
def serve_app(app: FastAPI, ready_path: str, ws: WSProtocolType = "none") -> Iterator[str]:
    """Run `app` on a free port in a thread (its own event loop)."""
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", ws=ws))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{port}"
    try:
        wait_for(f"{url}{ready_path}")
        yield url
    finally:
        server.should_exit = True
        thread.join(timeout=15)


@contextmanager
def vite_dev_server(backend_url: str, ready_path: str = "/") -> Iterator[str]:
    """The frontend's dev server, proxying /api, /generate-code, /local-assets
    and /rn-runtime to `backend_url` (frontend/vite.config.ts)."""
    port = free_port()
    process = subprocess.Popen(
        [str(VITE), "--host", "127.0.0.1", "--port", str(port), "--strictPort"],
        cwd=ROOT / "frontend",
        env={**os.environ, "PROXY_CODEGEN_BACKEND": backend_url},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,  # its own process group, so teardown stops esbuild and the type checker too
    )
    url = f"http://127.0.0.1:{port}"
    try:
        wait_for(f"{url}{ready_path}", process)
        yield url
    finally:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=10)
