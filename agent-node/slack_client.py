"""
slack_client.py — Thin shared Slack helpers (chat.postMessage etc.).

Replaces the copies of these functions that previously lived in
run_agent.py / run_pipeline.py.
"""

import logging
import os

import requests

log = logging.getLogger(__name__)

TOKEN   = os.environ.get("SLACK_BOT_TOKEN", "")
CHANNEL = os.environ.get("SLACK_CHANNEL", "")

_HEADERS = {"Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json"}


def post(text: str, thread_ts: str = None, channel: str = None):
    """Post a message. Returns (ts, ok)."""
    payload = {"channel": channel or CHANNEL, "text": text}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    try:
        data = requests.post("https://slack.com/api/chat.postMessage",
                             headers=_HEADERS, json=payload, timeout=10).json()
        if not data.get("ok"):
            log.warning("slack post failed: %s", data.get("error"))
        return data.get("ts"), data.get("ok", False)
    except Exception as e:
        log.warning("slack post error: %s", e)
        return None, False


def update(ts: str, text: str, channel: str = None):
    try:
        requests.post("https://slack.com/api/chat.update", headers=_HEADERS,
                      json={"channel": channel or CHANNEL, "ts": ts,
                            "text": text}, timeout=10)
    except Exception as e:
        log.warning("slack update error: %s", e)


def add_reaction(ts: str, emoji: str, channel: str = None):
    try:
        requests.post("https://slack.com/api/reactions.add", headers=_HEADERS,
                      json={"channel": channel or CHANNEL, "timestamp": ts,
                            "name": emoji}, timeout=10)
    except Exception as e:
        log.debug("slack reaction error: %s", e)


def get_reactions(ts: str, channel: str = None) -> list:
    try:
        data = requests.get(
            "https://slack.com/api/reactions.get",
            headers={"Authorization": f"Bearer {TOKEN}"},
            params={"channel": channel or CHANNEL, "timestamp": ts},
            timeout=10).json()
        if not data.get("ok"):
            return []
        return [r["name"] for r in data.get("message", {}).get("reactions", [])]
    except Exception:
        return []
