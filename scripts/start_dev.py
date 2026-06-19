#!/usr/bin/env python3
"""Start API and GUI dev servers using ports from config/config.yaml."""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent.parent


def _load_settings():
    sys.path.insert(0, str(ROOT))
    from src.config.settings import load_config

    return load_config(str(ROOT / "config" / "config.yaml"))


def _wait_for_url(url: str, timeout_s: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=2) as resp:
                if 200 <= resp.status < 400:
                    return True
        except (URLError, TimeoutError, OSError):
            pass
        time.sleep(0.25)
    return False


def _wait_for_api(port: int, timeout_s: float = 30.0) -> bool:
    return _wait_for_url(f"http://127.0.0.1:{port}/api/v1/health/precheck", timeout_s)


def _wait_for_gui(port: int, timeout_s: float = 60.0) -> bool:
    deadline = time.monotonic() + timeout_s
    url = _gui_base_url(port)
    while time.monotonic() < deadline:
        if _port_in_use(port):
            if _wait_for_url(url, timeout_s=2.0):
                return True
        time.sleep(0.25)
    return False


def _open_browser(url: str) -> None:
    print(f"Opening {url}")
    if sys.platform == "darwin":
        subprocess.run(["open", url], check=False)
    else:
        import webbrowser

        webbrowser.open(url)


def _port_in_use(port: int) -> bool:
    import socket

    checks: list[tuple[int, str]] = [
        (socket.AF_INET, "127.0.0.1"),
        (socket.AF_INET6, "::1"),
    ]
    for family, host in checks:
        try:
            with socket.socket(family, socket.SOCK_STREAM) as sock:
                sock.settimeout(0.5)
                if sock.connect_ex((host, port)) == 0:
                    return True
        except OSError:
            continue
    return False


def _gui_base_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/"


def _ensure_gui_deps() -> None:
    if (ROOT / "gui" / "node_modules").is_dir():
        return
    print("Installing GUI dependencies (npm install)...")
    subprocess.run(["npm", "install"], cwd=ROOT / "gui", check=True)


def _spawn(cmd: list[str], *, cwd: Path | None = None, env: dict | None = None) -> subprocess.Popen:
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.Popen(
        cmd,
        cwd=cwd or ROOT,
        env=merged,
        start_new_session=True,
    )


def _terminate(procs: list[subprocess.Popen]) -> None:
    for proc in procs:
        if proc.poll() is not None:
            continue
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            proc.terminate()
    deadline = time.monotonic() + 5.0
    for proc in procs:
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.1)
    for proc in procs:
        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                proc.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description="Start knowledge-graph dev servers")
    parser.add_argument("--api-only", action="store_true", help="Start API only")
    parser.add_argument("--gui-only", action="store_true", help="Start GUI only (API must already be running)")
    parser.add_argument("--skip-health-wait", action="store_true", help="Do not wait for API health check")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the GUI in a browser")
    args = parser.parse_args()

    cfg = _load_settings()
    api_port = cfg.n8n.port
    gui_port = cfg.gui.port
    gui_url = _gui_base_url(gui_port)
    procs: list[subprocess.Popen] = []

    def shutdown(_signum=None, _frame=None) -> None:
        print("\nStopping dev servers...")
        _terminate(procs)
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    start_api = not args.gui_only
    start_gui = not args.api_only

    if start_api:
        if _port_in_use(api_port):
            print(f"API port {api_port} already in use — assuming API is running.")
        else:
            print(f"Starting API on http://127.0.0.1:{api_port} ...")
            procs.append(
                _spawn(
                    ["uv", "run", "python", "main.py", "server"],
                )
            )
            if not args.skip_health_wait and not _wait_for_api(api_port):
                print(f"API did not become ready on port {api_port} within timeout.", file=sys.stderr)
                _terminate(procs)
                return 1
            print(f"API ready: http://127.0.0.1:{api_port}/api/v1")

    if start_gui:
        if _port_in_use(gui_port):
            print(f"GUI port {gui_port} already in use — skipping GUI start.")
        else:
            _ensure_gui_deps()
            api_target = f"http://127.0.0.1:{api_port}"
            print(f"Starting GUI on http://127.0.0.1:{gui_port} (proxy /api -> {api_target}) ...")
            procs.append(
                _spawn(
                    ["npm", "run", "dev", "--", "--port", str(gui_port), "--strictPort"],
                    cwd=ROOT / "gui",
                    env={
                        "KGS_API_PORT": str(api_port),
                        "KGS_GUI_PORT": str(gui_port),
                    },
                )
            )
            print(f"GUI: {gui_url}")

    if start_gui and not args.no_browser:
        print(f"Waiting for GUI at {gui_url} ...", flush=True)
        if not _wait_for_gui(gui_port):
            print(f"GUI not reachable at {gui_url} — skipping browser open.", file=sys.stderr, flush=True)
        else:
            _open_browser(gui_url)

    if not procs:
        print("Nothing started (ports already in use or nothing requested).")
        return 0

    print("Press Ctrl+C to stop.")
    try:
        while True:
            for proc in procs:
                code = proc.poll()
                if code is not None:
                    print(f"Process exited with code {code}.", file=sys.stderr)
                    _terminate(procs)
                    return code or 1
            time.sleep(0.5)
    except KeyboardInterrupt:
        shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
