#!/usr/bin/env python3
"""Minimal local executor service for Magatron operator mode."""

import logging
import os
import subprocess
import sys
from pathlib import Path

from flask import Flask, request, jsonify, send_from_directory

# ── Config ────────────────────────────────────────────────────────────────────

TOKEN = os.environ.get("EXECUTOR_TOKEN", "")
HOST = os.environ.get("EXECUTOR_HOST", "127.0.0.1")
PORT = int(os.environ.get("EXECUTOR_PORT", "8787"))
ARTIFACTS_DIR = Path(os.environ.get("EXECUTOR_ARTIFACTS_DIR", "./artifacts"))
DEBUG = os.environ.get("EXECUTOR_DEBUG", "").lower() in ("true", "1", "yes")

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.DEBUG if DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("executor")

# ── App ───────────────────────────────────────────────────────────────────────

app = Flask(__name__)


@app.after_request
def _log_request(response):
    log.info("%s %s -> %s", request.method, request.path, response.status_code)
    return response


# ── Auth ──────────────────────────────────────────────────────────────────────

def _check_token():
    """Return a 403 Response if the token is missing/wrong, else None."""
    if request.headers.get("X-Executor-Token") != TOKEN:
        return jsonify({"ok": False, "error": "unauthorized"}), 403
    return None


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return jsonify({"ok": True})


_MAX_OUTPUT = 32 * 1024  # 32 KB per stdout/stderr


def _truncate(text: str) -> str:
    if len(text) > _MAX_OUTPUT:
        return text[:_MAX_OUTPUT] + "...(truncated)"
    return text


def _exec_step(i: int, step: dict) -> dict:
    step_type = step.get("type")

    if step_type != "shell":
        return {"i": i, "type": step_type, "error": "unknown step type"}

    cmd = step.get("cmd", "")
    if not cmd:
        return {"i": i, "type": "shell", "cmd": cmd, "error": "empty cmd"}

    try:
        proc = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=10,
        )
        return {
            "i": i,
            "type": "shell",
            "cmd": cmd,
            "returncode": proc.returncode,
            "stdout": _truncate(proc.stdout),
            "stderr": _truncate(proc.stderr),
        }
    except subprocess.TimeoutExpired:
        return {
            "i": i,
            "type": "shell",
            "cmd": cmd,
            "returncode": -1,
            "stdout": "",
            "stderr": "timeout",
        }


@app.post("/run")
def run():
    err = _check_token()
    if err:
        return err

    payload = request.get_json(silent=True) or {}
    steps = payload.get("steps", [])
    log.info("/run received %d step(s)", len(steps))
    if DEBUG:
        log.debug("/run payload: %s", payload)

    results = [_exec_step(i, step) for i, step in enumerate(steps)]

    return jsonify({
        "ok": True,
        "steps_count": len(steps),
        "results": results,
        "artifacts": [],
    })


@app.get("/artifacts/<path:filename>")
def get_artifact(filename):
    err = _check_token()
    if err:
        return err

    safe_name = Path(filename).name
    file_path = ARTIFACTS_DIR / safe_name
    if not file_path.is_file():
        return jsonify({"ok": False, "error": "not_found"}), 404

    return send_from_directory(str(ARTIFACTS_DIR), safe_name)


@app.post("/artifacts/<path:filename>")
def upload_artifact(filename):
    err = _check_token()
    if err:
        return err

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename).name
    file_path = ARTIFACTS_DIR / safe_name

    data = request.get_data()
    if not data:
        return jsonify({"ok": False, "error": "empty body"}), 400

    file_path.write_bytes(data)
    log.info("saved artifact %s (%d bytes)", safe_name, len(data))

    return jsonify({"ok": True, "filename": safe_name, "size": len(data)})


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if not TOKEN:
        print("FATAL: EXECUTOR_TOKEN is not set. Export it before running:", file=sys.stderr)
        print('  export EXECUTOR_TOKEN="your-secret-token"', file=sys.stderr)
        sys.exit(1)

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    log.info("executor starting on %s:%d  artifacts=%s  debug=%s", HOST, PORT, ARTIFACTS_DIR, DEBUG)
    app.run(host=HOST, port=PORT, debug=DEBUG)
