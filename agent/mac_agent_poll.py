#!/usr/bin/env python3
"""
Mac agent polling script for Railway UI job queue.

Polls Railway GET /ui/next, executes jobs via local UI executor,
posts results to Railway POST /ui/result.

Usage (see agent/README.md):
  export RAILWAY_URL=... UI_AGENT_TOKEN=... LOCAL_UI_EXECUTOR_URL=... LOCAL_UI_EXECUTOR_TOKEN=...
  python agent/mac_agent_poll.py
"""

from __future__ import annotations

import base64
import json
import logging
import os
import socket
import sys
import time
from urllib.parse import urlencode

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger(__name__)


def _get_config() -> dict:
    railway_url = (os.getenv("RAILWAY_URL") or "").rstrip("/")
    ui_token = os.getenv("UI_AGENT_TOKEN", "")
    executor_url = (os.getenv("LOCAL_UI_EXECUTOR_URL") or "").rstrip("/")
    executor_token = os.getenv("LOCAL_UI_EXECUTOR_TOKEN", "")
    agent_id = os.getenv("AGENT_ID", socket.gethostname() or "macbook-air-vado")
    poll_interval = int(os.getenv("POLL_INTERVAL_SEC", "2"))
    local_connect = int(os.getenv("LOCAL_EXECUTOR_CONNECT_TIMEOUT", "5"))
    local_read = int(os.getenv("LOCAL_EXECUTOR_READ_TIMEOUT", "120"))
    railway_connect = int(os.getenv("RAILWAY_CONNECT_TIMEOUT", "5"))
    railway_read = int(os.getenv("RAILWAY_READ_TIMEOUT", "30"))
    max_retries = int(os.getenv("MAX_RETRIES", "3"))
    backoff_base = int(os.getenv("BACKOFF_BASE_SEC", "1"))

    return {
        "railway_url": railway_url,
        "ui_token": ui_token,
        "executor_url": executor_url,
        "executor_token": executor_token,
        "agent_id": agent_id,
        "poll_interval": poll_interval,
        "local_timeout": (local_connect, local_read),
        "railway_timeout": (railway_connect, railway_read),
        "max_retries": max_retries,
        "backoff_base": backoff_base,
    }


def _request_with_retry(
    method: str,
    url: str,
    *,
    headers: dict,
    json_data: dict | None = None,
    timeout: tuple[int, int],
    retries: int,
    backoff_base: int,
) -> requests.Response | None:
    for attempt in range(retries):
        try:
            if method == "GET":
                r = requests.get(url, headers=headers, timeout=timeout)
            else:
                r = requests.post(url, headers=headers, json=json_data, timeout=timeout)
            return r
        except (requests.ConnectionError, requests.Timeout) as exc:
            delay = backoff_base * (2**attempt)
            log.warning(
                "Request failed (attempt %d/%d): %s. Retry in %ds",
                attempt + 1,
                retries,
                exc.__class__.__name__,
                delay,
            )
            time.sleep(delay)
    return None


def _fetch_job(cfg: dict) -> dict | None:
    url = f"{cfg['railway_url']}/ui/next?{urlencode({'agent_id': cfg['agent_id']})}"
    headers = {"X-UI-Agent-Token": cfg["ui_token"]}

    r = _request_with_retry(
        "GET",
        url,
        headers=headers,
        timeout=cfg["railway_timeout"],
        retries=cfg["max_retries"],
        backoff_base=cfg["backoff_base"],
    )
    if r is None:
        return None
    if r.status_code == 204:
        return None
    if r.status_code == 403:
        log.error("Auth rejected (403). Check UI_AGENT_TOKEN.")
        return None
    r.raise_for_status()
    try:
        return r.json()
    except json.JSONDecodeError:
        log.error("Invalid JSON from /ui/next")
        return None


def _run_executor(cfg: dict, steps: list) -> dict | None:
    url = f"{cfg['executor_url']}/run"
    headers = {"Content-Type": "application/json"}
    if cfg["executor_token"]:
        headers["X-Executor-Token"] = cfg["executor_token"]

    r = _request_with_retry(
        "POST",
        url,
        headers=headers,
        json_data={"steps": steps},
        timeout=cfg["local_timeout"],
        retries=cfg["max_retries"],
        backoff_base=cfg["backoff_base"],
    )
    if r is None:
        return None
    if r.status_code == 403:
        log.error("Executor auth rejected (403). Check LOCAL_UI_EXECUTOR_TOKEN.")
        return None
    r.raise_for_status()
    try:
        return r.json()
    except json.JSONDecodeError:
        log.error("Invalid JSON from executor /run")
        return None


def _fetch_artifact(cfg: dict, filename: str) -> bytes | None:
    url = f"{cfg['executor_url']}/artifacts/{filename}"
    headers = {}
    if cfg["executor_token"]:
        headers["X-Executor-Token"] = cfg["executor_token"]

    r = _request_with_retry(
        "GET",
        url,
        headers=headers,
        timeout=cfg["local_timeout"],
        retries=cfg["max_retries"],
        backoff_base=cfg["backoff_base"],
    )
    if r is None or r.status_code == 404:
        return None
    r.raise_for_status()
    return r.content


def _post_result(
    cfg: dict,
    job_id: str,
    ok: bool,
    results: list,
    artifacts: list,
) -> bool:
    url = f"{cfg['railway_url']}/ui/result"
    headers = {"Content-Type": "application/json", "X-UI-Agent-Token": cfg["ui_token"]}
    payload = {
        "job_id": job_id,
        "ok": ok,
        "results": results,
        "artifacts": artifacts,
    }

    r = _request_with_retry(
        "POST",
        url,
        headers=headers,
        json_data=payload,
        timeout=cfg["railway_timeout"],
        retries=cfg["max_retries"],
        backoff_base=cfg["backoff_base"],
    )
    if r is None:
        return False
    r.raise_for_status()
    data = r.json()
    return data.get("ok", False)


def _process_job(cfg: dict, job: dict) -> None:
    job_id = job.get("job_id", "")
    steps = job.get("steps", [])
    if not steps:
        log.warning("Job %s has no steps", job_id)
        _post_result(cfg, job_id, False, [{"error": "no steps"}], [])
        return

    log.info("Executing job %s with %d step(s)", job_id, len(steps))

    try:
        data = _run_executor(cfg, steps)
    except Exception as exc:
        error_detail = str(exc)[:300]
        log.error("Executor failed for job %s: %s", job_id, error_detail)
        _post_result(
            cfg,
            job_id,
            False,
            [{"error": error_detail, "type": "executor_error"}],
            [],
        )
        return

    if data is None:
        _post_result(
            cfg,
            job_id,
            False,
            [{"error": "executor failed (connection/retry exhausted)"}],
            [],
        )
        return

    ok = data.get("ok", False)
    results = data.get("results", [])
    artifact_names = data.get("artifacts", [])

    artifacts_payload: list[dict] = []
    for entry in artifact_names:
        if isinstance(entry, dict):
            name = entry.get("name") or entry.get("filename", "")
        elif isinstance(entry, str):
            name = entry
        else:
            continue
        if not name:
            continue
        raw = _fetch_artifact(cfg, name)
        if raw:
            artifacts_payload.append({"name": name, "data": base64.b64encode(raw).decode("ascii")})

    _post_result(cfg, job_id, ok, results, artifacts_payload)
    log.info(
        "Job %s completed ok=%s artifacts=%d",
        job_id,
        ok,
        len(artifacts_payload),
    )


def main() -> int:
    cfg = _get_config()
    if not cfg["railway_url"]:
        log.error("RAILWAY_URL required")
        return 1
    if not cfg["ui_token"]:
        log.error("UI_AGENT_TOKEN required")
        return 1
    if not cfg["executor_url"]:
        log.error("LOCAL_UI_EXECUTOR_URL required")
        return 1

    log.info(
        "Starting mac agent poll railway=%s executor=%s agent_id=%s poll_interval=%ds",
        cfg["railway_url"],
        cfg["executor_url"],
        cfg["agent_id"],
        cfg["poll_interval"],
    )

    try:
        while True:
            job = _fetch_job(cfg)
            if job:
                _process_job(cfg, job)
            else:
                time.sleep(cfg["poll_interval"])
    except KeyboardInterrupt:
        log.info("Stopped by user")
    return 0


if __name__ == "__main__":
    sys.exit(main())
