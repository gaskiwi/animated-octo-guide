"""
loop_daemon.py — The looping layer: agents that run until verified done.

Implements loop engineering on top of the existing runners:
  trigger → act → VERIFY (real command, not LLM opinion) → feed failure
  back → act again → ... until verify passes or budget exhausted → escalate.

Loops are defined as YAML files in /app/loops/*.yaml:

  name: fix-tests                  # unique id
  goal: |                          # what the agent should accomplish
    Make the test suite in /workspace/myproj pass.
  verify:
    command: "cd /workspace/myproj && pytest -q"   # exit 0 == done
    timeout: 300
  runner: claude-code              # claude-code | dynamic | misc | none
  runner_flags: ""                 # extra flags for dynamic/misc
  trigger:
    schedule: "0 6 * * *"          # cron (UTC) — or:
    # interval_minutes: 60         # simple interval
    # (no trigger = manual only, via /loop run <name>)
  budget:
    max_iterations: 5
    max_minutes: 90
  enabled: true

Special case `runner: none` = watchdog loop: just verify; alert to Slack on
pass→fail transitions (no LLM calls at all).

State (SQLite) lives in /app/state/loops.db — survives rebuilds via volume.
Control from Slack: /loop list|run|enable|disable|status  (see loopctl.py)
"""

import json
import logging
import os
import sqlite3
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s [loopd] %(message)s")
log = logging.getLogger("loopd")

import slack_client as slack

SCRIPT_DIR = Path(__file__).parent
LOOPS_DIR  = Path(os.environ.get("LOOPS_DIR", "/app/loops"))
STATE_DIR  = Path(os.environ.get("LOOP_STATE_DIR", "/app/state"))
DB_PATH    = STATE_DIR / "loops.db"

# Loop workdirs live in the ./workspace volume, which is visible from BOTH
# the container (/workspace) and the host (~/animated-octo-guide/agent-node/
# workspace). The Claude Code proxy runs on the HOST, so it gets the host
# translation of the container path.
WORK_ROOT     = Path(os.environ.get("LOOP_WORK_ROOT", "/workspace/loop_workdirs"))
HOST_WS_ROOT  = os.environ.get(
    "HOST_WORKSPACE_ROOT",
    "/home/pacers4ever/animated-octo-guide/agent-node/workspace")


def to_host_path(container_path: str) -> str:
    return str(container_path).replace("/workspace", HOST_WS_ROOT, 1)


def make_shared_dir(path: Path):
    """mkdir that the unprivileged host user (proxy) can also write into.
    The container runs as root, so dirs it creates must be opened up."""
    path.mkdir(parents=True, exist_ok=True)
    p = path
    while True:
        try:
            os.chmod(p, 0o777)
        except OSError:
            pass
        if p == p.parent or str(p) in ("/workspace", "/"):
            break
        p = p.parent

TICK_SECONDS        = 20
MAX_CONCURRENT      = int(os.environ.get("LOOP_MAX_CONCURRENT", "2"))
DEFAULT_MAX_ITER    = 5
DEFAULT_MAX_MINUTES = 90
VERIFY_TIMEOUT      = 600
RUNNER_TIMEOUT      = 3600

LOOPS_DIR.mkdir(parents=True, exist_ok=True)
STATE_DIR.mkdir(parents=True, exist_ok=True)
WORK_ROOT.mkdir(parents=True, exist_ok=True)

# ── DB ────────────────────────────────────────────────────────────────────────
def db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            loop_name TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',  -- queued|running|done|failed|escalated
            queued_at TEXT, started_at TEXT, finished_at TEXT,
            iterations INTEGER DEFAULT 0,
            note TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS loop_state (
            loop_name TEXT PRIMARY KEY,
            last_scheduled TEXT,
            last_status TEXT,          -- pass|fail (watchdogs)
            enabled_override INTEGER   -- NULL=use yaml, 0/1=override
        );
        """)


# ── Loop definitions ──────────────────────────────────────────────────────────
def load_loops() -> dict:
    import yaml
    loops = {}
    for f in sorted(LOOPS_DIR.glob("*.yaml")):
        try:
            d = yaml.safe_load(f.read_text())
            if not d or "name" not in d:
                continue
            d["_file"] = str(f)
            loops[d["name"]] = d
        except Exception as e:
            log.warning("bad loop file %s: %s", f, e)
    return loops


def is_enabled(loop, conn) -> bool:
    row = conn.execute("SELECT enabled_override FROM loop_state WHERE loop_name=?",
                       (loop["name"],)).fetchone()
    if row and row[0] is not None:
        return bool(row[0])
    return bool(loop.get("enabled", True))


# ── Scheduling ────────────────────────────────────────────────────────────────
def is_due(loop, conn) -> bool:
    trig = loop.get("trigger") or {}
    now = datetime.now(timezone.utc)
    row = conn.execute("SELECT last_scheduled FROM loop_state WHERE loop_name=?",
                       (loop["name"],)).fetchone()
    last = datetime.fromisoformat(row[0]) if row and row[0] else None

    if "interval_minutes" in trig:
        iv = float(trig["interval_minutes"]) * 60
        return last is None or (now - last).total_seconds() >= iv

    if "schedule" in trig:
        try:
            from croniter import croniter
            base = last or now
            nxt = croniter(trig["schedule"], base).get_next(datetime)
            if nxt.tzinfo is None:
                nxt = nxt.replace(tzinfo=timezone.utc)
            return nxt <= now
        except Exception as e:
            log.warning("cron parse failed for %s: %s", loop["name"], e)
            return False
    return False  # manual-only


def mark_scheduled(name, conn):
    conn.execute("""INSERT INTO loop_state(loop_name, last_scheduled)
                    VALUES(?, ?)
                    ON CONFLICT(loop_name) DO UPDATE SET last_scheduled=excluded.last_scheduled""",
                 (name, datetime.now(timezone.utc).isoformat()))
    conn.commit()


def enqueue(name, conn, note="scheduled"):
    running = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE loop_name=? AND status IN ('queued','running')",
        (name,)).fetchone()[0]
    if running:
        log.info("loop %s already queued/running — skipping", name)
        return False
    conn.execute("INSERT INTO jobs(loop_name, status, queued_at, note) VALUES(?,?,?,?)",
                 (name, "queued", datetime.now(timezone.utc).isoformat(), note))
    conn.commit()
    return True


# ── Verification (ground truth) ───────────────────────────────────────────────
def run_verify(loop) -> tuple:
    """Run the verify command. Returns (exit_code, tail_of_output)."""
    v = loop.get("verify") or {}
    cmd = v.get("command")
    if not cmd:
        return 0, "(no verify command — single-shot loop)"
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                           timeout=int(v.get("timeout", VERIFY_TIMEOUT)),
                           cwd=str(SCRIPT_DIR))
        out = ((r.stdout or "") + "\n" + (r.stderr or "")).strip()
        return r.returncode, out[-3000:]
    except subprocess.TimeoutExpired:
        return 124, "(verify timed out)"
    except Exception as e:
        return 1, f"(verify error: {e})"


# ── Acting ────────────────────────────────────────────────────────────────────
def act(loop, prompt, workdir) -> str:
    """Run one iteration of work. Returns a short summary of what happened."""
    runner = loop.get("runner", "claude-code")

    if runner == "claude-code":
        from claude_code_runner import run_claude_code, CLAUDE_CODE_AVAILABLE
        if not CLAUDE_CODE_AVAILABLE:
            raise RuntimeError("claude-code proxy unreachable")
        out, _ = run_claude_code(
            prompt, workdir=to_host_path(workdir),
            system=(f"# Loop: {loop['name']}\nYou are one iteration of a "
                    f"verification-driven loop. The verify command and its "
                    f"latest failing output are in the prompt. Fix the cause; "
                    f"the loop re-verifies after you finish."),
            timeout=RUNNER_TIMEOUT)
        return out[-1500:]

    if runner in ("dynamic", "misc"):
        script = SCRIPT_DIR / f"run_{runner}.py"
        env = os.environ.copy()
        env["OPENCLAW_TASK"] = prompt
        flags = (loop.get("runner_flags") or "").split()
        r = subprocess.run(["python3", str(script)] + flags,
                           cwd=str(SCRIPT_DIR), env=env, capture_output=True,
                           text=True, timeout=RUNNER_TIMEOUT)
        return f"(runner {runner} exited {r.returncode})"

    raise ValueError(f"unknown runner: {runner}")


# ── The loop itself ───────────────────────────────────────────────────────────
def execute_loop(loop, job_id):
    name   = loop["name"]
    budget = loop.get("budget") or {}
    max_iter = int(budget.get("max_iterations", DEFAULT_MAX_ITER))
    max_secs = float(budget.get("max_minutes", DEFAULT_MAX_MINUTES)) * 60
    runner = loop.get("runner", "claude-code")
    verify_cmd = (loop.get("verify") or {}).get("command", "")
    started = time.time()

    # Watchdog loops: verify only, alert on state change, no LLM
    if runner == "none":
        code, out = run_verify(loop)
        status = "pass" if code == 0 else "fail"
        with db() as conn:
            prev = conn.execute("SELECT last_status FROM loop_state WHERE loop_name=?",
                                (name,)).fetchone()
            prev = prev[0] if prev else None
            conn.execute("""INSERT INTO loop_state(loop_name, last_status) VALUES(?,?)
                            ON CONFLICT(loop_name) DO UPDATE SET last_status=excluded.last_status""",
                         (name, status))
            conn.execute("UPDATE jobs SET status=?, finished_at=?, iterations=1, note=? WHERE id=?",
                         ("done" if code == 0 else "failed",
                          datetime.now(timezone.utc).isoformat(), status, job_id))
            conn.commit()
        if status != prev and prev is not None or (status == "fail" and prev is None):
            icon = "✅" if status == "pass" else "🚨"
            slack.post(f"{icon} *Watchdog `{name}`: {status.upper()}*"
                       + (f"\n```{out[-800:]}```" if status == "fail" else ""))
        log.info("watchdog %s: %s", name, status)
        return

    workdir = WORK_ROOT / name
    make_shared_dir(workdir)

    thread_ts, _ = slack.post(
        f"🔁 *Loop `{name}` started* (runner: {runner}, "
        f"budget: {max_iter} iterations / {max_secs/60:.0f} min)\n"
        f"Goal: {loop.get('goal', '')[:200].strip()}\n"
        f"Verify: `{verify_cmd[:120] or 'none (single-shot)'}`")

    iterations = 0
    final = "failed"
    try:
        for i in range(1, max_iter + 1):
            # 1. VERIFY — maybe there's nothing to do
            code, vout = run_verify(loop)
            if code == 0 and verify_cmd:
                final = "done"
                slack.post(f"✅ *Loop `{name}` verified done* after "
                           f"{iterations} iteration(s) — `{verify_cmd[:80]}` "
                           f"exits 0.", thread_ts)
                break

            if time.time() - started > max_secs:
                final = "escalated"
                slack.post(f"⏰ *Loop `{name}` hit time budget* "
                           f"({max_secs/60:.0f} min) — escalating.\n"
                           f"Last verify output:\n```{vout[-800:]}```", thread_ts)
                break

            # 2. ACT — feed the failure back to the agent
            iterations = i
            slack.post(f"🔄 *Iteration {i}/{max_iter}* — verify "
                       f"exit={code}, acting…", thread_ts)
            prompt = (
                f"GOAL:\n{loop.get('goal', '').strip()}\n\n"
                + (f"VERIFY COMMAND (must exit 0 when you are done):\n"
                   f"{verify_cmd}\n\n"
                   f"LATEST VERIFY OUTPUT (currently failing, exit {code}):\n"
                   f"{vout}\n\n" if verify_cmd else "")
                + f"This is iteration {i} of an automated loop. "
                  f"Fix the root cause, then stop."
            )
            try:
                summary = act(loop, prompt, workdir)
                slack.post(f"_Iteration {i} result:_\n```{summary[-700:]}```",
                           thread_ts)
            except Exception as e:
                slack.post(f"⚠️ Iteration {i} runner error: `{e}`", thread_ts)
                log.warning("loop %s iter %d runner error: %s", name, i, e)

            if not verify_cmd:           # single-shot loop: one act, done
                final = "done"
                slack.post(f"✅ *Loop `{name}` complete* (single-shot).", thread_ts)
                break
        else:
            final = "escalated"
            code, vout = run_verify(loop)
            slack.post(f"🚨 *Loop `{name}` exhausted {max_iter} iterations "
                       f"without passing verification — needs a human.*\n"
                       f"Last verify (exit {code}):\n```{vout[-800:]}```\n"
                       f"Workdir: `{workdir}`", thread_ts)
    except Exception as e:
        final = "failed"
        log.exception("loop %s crashed", name)
        slack.post(f"❌ *Loop `{name}` crashed:* `{e}`", thread_ts)

    with db() as conn:
        conn.execute("UPDATE jobs SET status=?, finished_at=?, iterations=? WHERE id=?",
                     (final, datetime.now(timezone.utc).isoformat(), iterations, job_id))
        conn.commit()
    log.info("loop %s finished: %s (%d iterations)", name, final, iterations)


# ── Daemon ────────────────────────────────────────────────────────────────────
_active = threading.Semaphore(MAX_CONCURRENT)


def _worker(loop, job_id):
    with _active:
        with db() as conn:
            conn.execute("UPDATE jobs SET status='running', started_at=? WHERE id=?",
                         (datetime.now(timezone.utc).isoformat(), job_id))
            conn.commit()
        execute_loop(loop, job_id)


def tick():
    loops = load_loops()
    with db() as conn:
        # recover jobs left 'running' by a crash → requeue once
        conn.execute("""UPDATE jobs SET status='failed',
                        note=note || ' (daemon restart)'
                        WHERE status='running'
                        AND started_at < datetime('now', '-1 day')""")
        # schedule due loops
        for name, loop in loops.items():
            if not is_enabled(loop, conn):
                continue
            if is_due(loop, conn):
                mark_scheduled(name, conn)
                enqueue(name, conn)
        # dispatch queued jobs
        rows = conn.execute(
            "SELECT id, loop_name FROM jobs WHERE status='queued' ORDER BY id LIMIT 5"
        ).fetchall()
    for job_id, name in rows:
        loop = loops.get(name)
        if not loop:
            with db() as conn:
                conn.execute("UPDATE jobs SET status='failed', note='unknown loop' WHERE id=?",
                             (job_id,))
                conn.commit()
            continue
        threading.Thread(target=_worker, args=(loop, job_id), daemon=True).start()
        with db() as conn:   # mark immediately so we don't double-dispatch
            conn.execute("UPDATE jobs SET status='running', started_at=? WHERE id=?",
                         (datetime.now(timezone.utc).isoformat(), job_id))
            conn.commit()


def main():
    init_db()
    loops = load_loops()
    log.info("loop daemon up — %d loop(s) defined: %s",
             len(loops), ", ".join(loops) or "(none)")
    while True:
        try:
            tick()
        except Exception:
            log.exception("tick failed")
        time.sleep(TICK_SECONDS)


if __name__ == "__main__":
    main()
