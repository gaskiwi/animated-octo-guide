"""
loopctl.py — Slack control for the loop daemon. Launched by gateway like any
other runner (/loop ... or a `loop ...` message).

Subcommands:
  /loop list                 all loops, schedule, enabled, last result
  /loop run <name>           queue a loop now
  /loop enable <name>        enable (overrides yaml)
  /loop disable <name>       disable (overrides yaml)
  /loop status [<name>]      recent runs
  /loop show <name>          full definition
"""

import os
import sys
import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [loopctl] %(message)s")
log = logging.getLogger("loopctl")

import slack_client as slack
from loop_daemon import db, init_db, load_loops, enqueue, is_enabled


def fmt_trigger(loop):
    t = loop.get("trigger") or {}
    if "schedule" in t:
        return f"cron `{t['schedule']}`"
    if "interval_minutes" in t:
        return f"every {t['interval_minutes']} min"
    return "manual"


def cmd_list():
    loops = load_loops()
    if not loops:
        slack.post("No loops defined. Drop YAML files in `loops/` "
                   "(see `loops/README.md`).")
        return
    init_db()
    lines = []
    with db() as conn:
        for name, loop in loops.items():
            en = "🟢" if is_enabled(loop, conn) else "⚪️"
            last = conn.execute(
                "SELECT status, finished_at FROM jobs WHERE loop_name=? "
                "ORDER BY id DESC LIMIT 1", (name,)).fetchone()
            last_s = f"last: {last[0]} {(last[1] or '')[:16]}" if last else "never run"
            runner = loop.get("runner", "claude-code")
            lines.append(f"{en} *`{name}`* — {fmt_trigger(loop)} · "
                         f"runner: {runner} · {last_s}")
    slack.post("🔁 *Loops:*\n" + "\n".join(lines))


def cmd_run(name):
    loops = load_loops()
    if name not in loops:
        slack.post(f":x: No loop named `{name}`. Known: "
                   + ", ".join(f"`{n}`" for n in loops))
        return
    init_db()
    with db() as conn:
        ok = enqueue(name, conn, note="manual via /loop")
    slack.post(f"▶️ Loop `{name}` queued — the daemon picks it up within ~20s."
               if ok else f"⏳ Loop `{name}` is already queued or running.")


def cmd_toggle(name, value):
    loops = load_loops()
    if name not in loops:
        slack.post(f":x: No loop named `{name}`.")
        return
    init_db()
    with db() as conn:
        conn.execute("""INSERT INTO loop_state(loop_name, enabled_override) VALUES(?,?)
                        ON CONFLICT(loop_name) DO UPDATE SET enabled_override=excluded.enabled_override""",
                     (name, value))
        conn.commit()
    slack.post(f"{'🟢 Enabled' if value else '⚪️ Disabled'} loop `{name}`.")


def cmd_status(name=None):
    init_db()
    q = "SELECT loop_name, status, iterations, queued_at, finished_at FROM jobs "
    args = ()
    if name:
        q += "WHERE loop_name=? "
        args = (name,)
    q += "ORDER BY id DESC LIMIT 10"
    with db() as conn:
        rows = conn.execute(q, args).fetchall()
    if not rows:
        slack.post("No loop runs recorded yet.")
        return
    icon = {"done": "✅", "failed": "❌", "escalated": "🚨",
            "running": "🔄", "queued": "⏳"}
    lines = [f"{icon.get(s, '▪️')} `{ln}` — {s}, {it} iter, "
             f"queued {(qa or '')[:16]}" + (f", finished {(fa or '')[:16]}" if fa else "")
             for ln, s, it, qa, fa in rows]
    slack.post("📜 *Recent loop runs:*\n" + "\n".join(lines))


def cmd_show(name):
    loops = load_loops()
    if name not in loops:
        slack.post(f":x: No loop named `{name}`.")
        return
    raw = Path(loops[name]["_file"]).read_text()
    slack.post(f"📄 *`{name}`* (`{loops[name]['_file']}`):\n```{raw[:2500]}```")


def main():
    text = os.environ.get("OPENCLAW_TASK", "") or " ".join(sys.argv[1:])
    parts = text.split()
    sub = parts[0].lower() if parts else "list"
    arg = parts[1] if len(parts) > 1 else None

    if sub == "list":
        cmd_list()
    elif sub == "run" and arg:
        cmd_run(arg)
    elif sub == "enable" and arg:
        cmd_toggle(arg, 1)
    elif sub == "disable" and arg:
        cmd_toggle(arg, 0)
    elif sub == "status":
        cmd_status(arg)
    elif sub == "show" and arg:
        cmd_show(arg)
    else:
        slack.post("Usage: `/loop list | run <name> | enable <name> | "
                   "disable <name> | status [<name>] | show <name>`")


if __name__ == "__main__":
    main()
