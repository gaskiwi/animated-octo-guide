"""
slack_logger.py — Centralized Slack logging for all openclaw runners.

Provides SlackLogger: a class that manages a single Slack thread per job,
with a live-updating status message, heartbeat, timing, and error capture.

Usage in any runner:
    from slack_logger import SlackLogger

    log = SlackLogger(token=SLACK_BOT_TOKEN, channel=SLACK_CHANNEL)
    log.start("🏗️ /build", task="make a todo API", model="qwen")

    log.step("Generating code structure")          # new message in thread
    log.thinking("qwen writing authentication module...")  # updates status bar
    log.step("Code complete — 3 files generated")

    log.done("Build finished", result="Here is your code...")
    # or
    log.error("qwen timed out after 120s")

Design:
  - ONE thread per job (all messages are replies under the opening post)
  - ONE live status message that edits in-place (no spam)
  - Heartbeat thread: if no update for HEARTBEAT_INTERVAL seconds, posts
    "⏳ Still running... (Xm elapsed)" so you know it's alive
  - All uncaught exceptions routed to Slack via wrap_runner()
  - Every message shows elapsed time
"""

import os
import time
import threading
import traceback
import logging
from datetime import datetime
from typing import Optional
import requests

log = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 300   # 5 minutes of silence → post heartbeat
MAX_TEXT_LENGTH    = 2800  # Slack block text limit


class SlackLogger:
    def __init__(self, token: str, channel: str):
        self.token    = token
        self.channel  = channel
        self.thread_ts: Optional[str] = None   # parent message ts
        self.status_ts: Optional[str] = None   # the live-updating status message ts
        self.start_time = time.time()
        self._last_update = time.time()
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._stop_heartbeat = threading.Event()
        self._lock = threading.Lock()

        # Job metadata for display
        self.job_title  = ""
        self.job_task   = ""
        self.job_model  = ""
        self.current_stage = ""

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self, title: str, task: str = "", model: str = "qwen"):
        """
        Post the opening job card and start the heartbeat.
        Returns self for chaining.
        """
        self.job_title = title
        self.job_task  = task[:200]
        self.job_model = model
        self.start_time = time.time()

        body = self._opening_block()
        self.thread_ts = self._post(body)
        if not self.thread_ts:
            log.error("SlackLogger: could not post opening message")
            return self

        # Post initial status message (will be edited in place)
        self.status_ts = self._post("⏳ Starting up…", thread=True)
        self._last_update = time.time()

        # Start heartbeat
        self._stop_heartbeat.clear()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True
        )
        self._heartbeat_thread.start()

        return self

    def step(self, message: str, detail: str = ""):
        """
        Post a new permanent milestone message in the thread.
        Use for stage transitions and important checkpoints.
        """
        elapsed = self._elapsed()
        text = f"*{message}*"
        if detail:
            text += f"\n_{detail[:400]}_"
        text += f"  `{elapsed}`"
        self._post(text, thread=True)
        self._touch()

    def thinking(self, what: str):
        """
        Update the live status bar (edits in place) to show what model is doing.
        Use frequently inside a stage so the user can track progress.
        """
        elapsed = self._elapsed()
        text = (
            f"🧠 *{self.job_model}* — {what}\n"
            f"_{self.current_stage}_  `{elapsed} elapsed`"
        )
        self._update_status(text)
        self._touch()

    def progress(self, stage: str, detail: str = ""):
        """
        Mark entering a new named stage. Updates status bar with stage context.
        """
        self.current_stage = stage
        elapsed = self._elapsed()
        text = (
            f"▶️ *{stage}*\n"
            + (f"_{detail[:300]}_\n" if detail else "")
            + f"`{elapsed} elapsed`"
        )
        self._update_status(text)
        self._touch()

    def warn(self, message: str):
        """Post a warning (non-fatal) in thread."""
        self._post(f"⚠️ {message}  `{self._elapsed()}`", thread=True)
        self._touch()

    def error(self, message: str, exc: Exception = None):
        """Post an error card in thread and stop the heartbeat."""
        self._stop_heartbeat.set()
        elapsed = self._elapsed()
        text = f"❌ *Error* — {message}  `{elapsed}`"
        if exc:
            tb = traceback.format_exc()[-600:]
            text += f"\n```{tb}```"
        self._post(text, thread=True)
        self._update_status(f"❌ Failed at: {self.current_stage}  `{elapsed}`")

    def done(self, summary: str, result: str = ""):
        """
        Post the final success card and stop the heartbeat.
        `result` is the output text (truncated if long).
        """
        self._stop_heartbeat.set()
        elapsed = self._elapsed()

        # Final status update
        self._update_status(f"✅ *Complete*  `{elapsed}`")

        # Summary post
        text = f"✅ *{summary}*  `{elapsed}`"
        if result:
            preview = result if len(result) <= 1200 else result[:1200] + "\n…_(truncated — full output in state file)_"
            text += f"\n\n```{preview}```"
        self._post(text, thread=True)

    def wrap_runner(self, fn, *args, **kwargs):
        """
        Run fn(*args, **kwargs) and catch any uncaught exception,
        routing it to Slack via self.error().
        """
        try:
            fn(*args, **kwargs)
        except Exception as e:
            self.error(f"Uncaught exception in runner: {e}", exc=e)
            raise

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _opening_block(self) -> str:
        ts = datetime.now().strftime("%b %-d, %Y at %-I:%M %p")
        lines = [
            f"*{self.job_title}*",
            f"_{self.job_task}_" if self.job_task else "",
            f"Model: `{self.job_model}` · Started: {ts}",
        ]
        return "\n".join(l for l in lines if l)

    def _elapsed(self) -> str:
        secs = int(time.time() - self.start_time)
        if secs < 60:
            return f"{secs}s"
        elif secs < 3600:
            return f"{secs // 60}m {secs % 60}s"
        else:
            h = secs // 3600
            m = (secs % 3600) // 60
            return f"{h}h {m}m"

    def _touch(self):
        with self._lock:
            self._last_update = time.time()

    def _heartbeat_loop(self):
        """Background thread: post a heartbeat if silent for HEARTBEAT_INTERVAL."""
        while not self._stop_heartbeat.wait(timeout=30):
            with self._lock:
                silent_for = time.time() - self._last_update
            if silent_for >= HEARTBEAT_INTERVAL:
                elapsed = self._elapsed()
                self._post(
                    f"⏳ *Still running…* `{elapsed} elapsed`\n"
                    f"_{self.current_stage or 'Working'} in progress — no action needed_",
                    thread=True
                )
                self._touch()

    def _post(self, text: str, thread: bool = False) -> Optional[str]:
        payload = {
            "channel": self.channel,
            "text":    text[:MAX_TEXT_LENGTH],
        }
        if thread and self.thread_ts:
            payload["thread_ts"] = self.thread_ts
        try:
            resp = requests.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {self.token}",
                         "Content-Type": "application/json"},
                json=payload, timeout=10
            )
            data = resp.json()
            if not data.get("ok"):
                log.warning("Slack post error: %s", data.get("error"))
                return None
            return data.get("ts")
        except Exception as e:
            log.error("Slack post failed: %s", e)
            return None

    def _update_status(self, text: str):
        """Edit the live status message in place."""
        if not self.status_ts:
            self.status_ts = self._post(text, thread=True)
            return
        payload = {
            "channel": self.channel,
            "ts":      self.status_ts,
            "text":    text[:MAX_TEXT_LENGTH],
        }
        try:
            requests.post(
                "https://slack.com/api/chat.update",
                headers={"Authorization": f"Bearer {self.token}",
                         "Content-Type": "application/json"},
                json=payload, timeout=10
            )
        except Exception as e:
            log.error("Slack update failed: %s", e)


# ── Convenience: module-level logger (configured once per process) ─────────────
_global_logger: Optional[SlackLogger] = None

def get_logger() -> Optional[SlackLogger]:
    return _global_logger

def init_logger(token: str, channel: str) -> SlackLogger:
    global _global_logger
    _global_logger = SlackLogger(token=token, channel=channel)
    return _global_logger
