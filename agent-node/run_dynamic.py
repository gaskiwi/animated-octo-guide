"""
run_dynamic.py — Claude Dynamic Workflows.

Instead of a fixed research→plan→build→test→deploy pipeline, a Claude
orchestrator decomposes the task into a DAG of subtasks, and an executor
fans the independent ones out to parallel subagents (waves). Code-type
subtasks run through the Claude Code proxy (agentic, writes real files);
everything else is a direct LLM call. A final synthesis call merges all
subagent output into one deliverable posted to Slack.

Flow:
  1. PLAN       orchestrator (smart tier) → JSON DAG of subtasks
  2. EXECUTE    topological waves, each wave parallel (ThreadPoolExecutor)
  3. REPLAN     after each wave the orchestrator may add follow-up subtasks
  4. SYNTHESIZE merge everything into the final answer

Usage (via gateway: /dynamic <task>, or /pipeline --dynamic <task>):
  python3 run_dynamic.py "build and document a URL shortener"
  python3 run_dynamic.py --max-agents 12 --no-replan "research X from 6 angles"

Flags:
  --max-agents N   max parallel subagents per wave (default 8, cap 24 —
                   protects the mini PC and API rate limits)
  --no-replan      single planning pass, no adaptive follow-up waves
  --local          subagents use the free local model (orchestrator stays smart)
"""

import concurrent.futures as cf
import json
import logging
import os
import re
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("dynamic")

import slack_client as slack
from llm_client import complete, complete_json, provider

# ── Config ────────────────────────────────────────────────────────────────────
HARD_CAP_AGENTS   = 24    # absolute max parallel subagents
DEFAULT_PARALLEL  = 8
MAX_TOTAL_TASKS   = 40    # replanning cannot grow the DAG past this
MAX_WAVES         = 8
SUBAGENT_TIMEOUT  = 2700  # claude-code subtasks
STATE_DIR         = Path("/tmp/dynamic_states")
STATE_DIR.mkdir(exist_ok=True)

# Workdirs for code subtasks must live in the ./workspace volume so both the
# container AND the host-side Claude Code proxy can reach them.
CC_RUNS_ROOT = Path(os.environ.get("CC_RUNS_ROOT", "/workspace/cc_runs"))
HOST_WS_ROOT = os.environ.get(
    "HOST_WORKSPACE_ROOT",
    "/home/pacers4ever/animated-octo-guide/agent-node/workspace")


def to_host_path(container_path: str) -> str:
    return str(container_path).replace("/workspace", HOST_WS_ROOT, 1)

# ── Args ──────────────────────────────────────────────────────────────────────
raw_args = sys.argv[1:]

def _flag_value(name, default):
    m = re.search(rf"{name}[=\s]+(\d+)", " ".join(raw_args))
    return int(m.group(1)) if m else default

MAX_PARALLEL = min(_flag_value("--max-agents", DEFAULT_PARALLEL), HARD_CAP_AGENTS)
NO_REPLAN    = "--no-replan" in raw_args
USE_LOCAL    = "--local" in raw_args
SUB_TIER     = "local" if USE_LOCAL else "fast"

TASK = re.sub(r"--max-agents[=\s]+\d+|--no-replan|--local|--dynamic", "",
              " ".join(a for a in raw_args)).strip()

_env_task = os.environ.get("OPENCLAW_TASK", "")
if _env_task:
    cleaned = re.sub(r"^(\s*--[\w-]+(?:[=\s]+\S+)?\s*)+", "", _env_task).strip()
    cleaned = re.sub(r"--max-agents[=\s]+\d+|--no-replan|--local|--dynamic", "",
                     cleaned).strip()
    if cleaned:
        TASK = cleaned

if not TASK:
    slack.post(":x: */dynamic* — no task text provided.")
    sys.exit(1)

# ── Orchestrator prompts ──────────────────────────────────────────────────────
PLANNER_SYSTEM = """You are the orchestrator of a multi-agent system. Decompose the user's task into subtasks that independent subagents will execute, maximizing parallelism: subtasks with no dependency between them run at the same time.

Reply with ONLY a JSON object:
{
  "goal": "one-line restatement of the goal",
  "subtasks": [
    {
      "id": "t1",
      "title": "short title",
      "role": "one-line persona for the subagent, e.g. 'API researcher'",
      "prompt": "complete, self-contained instructions for the subagent",
      "depends_on": [],
      "kind": "llm" | "code"
    }
  ]
}

Rules:
- 2 to 12 subtasks. Prefer many small parallel subtasks over few serial ones.
- depends_on lists ids whose output this subtask needs; keep chains shallow.
- kind "code" ONLY for subtasks that must write/edit real files in a shared
  workspace (implementation, tests). Use "llm" for research/analysis/writing.
- Each prompt must stand alone: a subagent sees only its prompt plus the
  outputs of its depends_on."""

REPLAN_SYSTEM = """You are the orchestrator reviewing intermediate results of a multi-agent run. Decide if follow-up subtasks are needed (gaps, errors, verification). Be conservative — only add subtasks that clearly improve the final deliverable.

Reply with ONLY JSON: {"done": true} if nothing is needed, or
{"done": false, "subtasks": [ ...same schema as planning, ids must be new... ]}"""

SYNTH_SYSTEM = """You are the lead agent writing the final deliverable for Slack. Merge the subagent outputs into one coherent, well-organized answer. Resolve contradictions, drop duplication, credit nothing. Lead with the result, not the process."""

# ── Subagent execution ────────────────────────────────────────────────────────
def _deps_context(task_def, outputs):
    parts = []
    for dep in task_def.get("depends_on", []):
        if dep in outputs:
            parts.append(f"=== OUTPUT OF {dep} ===\n{outputs[dep][:5000]}")
    return ("\n\n".join(parts) + "\n\n") if parts else ""


def run_subagent(task_def, outputs, workdir):
    tid = task_def["id"]
    ctx = _deps_context(task_def, outputs)
    prompt = ctx + task_def["prompt"]
    system = (f"You are a subagent in a multi-agent workflow. "
              f"Persona: {task_def.get('role', 'specialist')}. "
              f"Do exactly your subtask; be complete but not padded.")

    t0 = time.time()
    if task_def.get("kind") == "code":
        try:
            from claude_code_runner import run_claude_code, CLAUDE_CODE_AVAILABLE
            if CLAUDE_CODE_AVAILABLE:
                out, _ = run_claude_code(
                    prompt, workdir=to_host_path(workdir),
                    system=f"# Subtask {tid}: {task_def['title']}\n\n{system}",
                    timeout=SUBAGENT_TIMEOUT)
                return tid, out, time.time() - t0, None
            log.warning("[%s] cc proxy down — using LLM fallback", tid)
        except Exception as e:
            log.warning("[%s] claude-code failed (%s) — LLM fallback", tid, e)
    try:
        out = complete(system, prompt, tier=SUB_TIER, max_tokens=4000)
        return tid, out, time.time() - t0, None
    except Exception as e:
        return tid, f"(subagent failed: {e})", time.time() - t0, str(e)


# ── DAG helpers ───────────────────────────────────────────────────────────────
def next_wave(subtasks, done):
    """Subtasks whose dependencies are all satisfied and aren't done."""
    return [t for t in subtasks
            if t["id"] not in done
            and all(d in done for d in t.get("depends_on", []))]


def validate_plan(plan):
    subtasks = plan.get("subtasks", [])
    if not subtasks:
        raise ValueError("planner returned no subtasks")
    ids = {t["id"] for t in subtasks}
    for t in subtasks:
        t["depends_on"] = [d for d in t.get("depends_on", []) if d in ids and d != t["id"]]
        t.setdefault("kind", "llm")
        t.setdefault("title", t["id"])
    return subtasks


def plan_tree(subtasks, outputs, durations):
    lines = []
    for t in subtasks:
        tid = t["id"]
        if tid in outputs:
            mark = f"✅ {durations.get(tid, 0):.0f}s"
        else:
            mark = "◻️"
        deps = f" ← {','.join(t['depends_on'])}" if t.get("depends_on") else ""
        kind = " ⚡" if t.get("kind") == "code" else ""
        lines.append(f"{mark} `{tid}` {t['title']}{kind}{deps}")
    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    log.info("dynamic run %s | provider=%s parallel=%d replan=%s",
             run_id, provider(), MAX_PARALLEL, not NO_REPLAN)

    thread_ts, ok = slack.post(
        f"🧠 *Dynamic workflow started*\n"
        f"Task: `{TASK[:150]}`\n"
        f"_Orchestrator planning… (provider: {provider()}, "
        f"max {MAX_PARALLEL} parallel subagents)_")
    if not ok:
        log.error("cannot post to Slack — check tokens")

    # 1. PLAN
    try:
        plan = complete_json(PLANNER_SYSTEM, f"TASK:\n{TASK}", tier="smart")
        subtasks = validate_plan(plan)
    except Exception as e:
        slack.post(f":x: Orchestrator planning failed: `{e}`", thread_ts)
        sys.exit(1)

    try:
        CC_RUNS_ROOT.mkdir(parents=True, exist_ok=True)
        os.chmod(CC_RUNS_ROOT, 0o777)
        workdir = tempfile.mkdtemp(prefix=f"dynamic_{run_id}_",
                                   dir=str(CC_RUNS_ROOT))
        os.chmod(workdir, 0o777)  # host-side proxy user must write here
    except Exception:
        workdir = tempfile.mkdtemp(prefix=f"dynamic_{run_id}_")
    outputs, durations, failures = {}, {}, {}
    slack.post(f"📋 *Plan* — {len(subtasks)} subtasks "
               f"(goal: {plan.get('goal', TASK)[:120]})\n"
               + plan_tree(subtasks, outputs, durations), thread_ts)

    # 2. EXECUTE in waves
    wave_num = 0
    while wave_num < MAX_WAVES:
        wave = next_wave(subtasks, outputs)
        if not wave:
            break
        wave_num += 1
        names = ", ".join(f"`{t['id']}`" for t in wave)
        slack.post(f"🌊 *Wave {wave_num}* — {len(wave)} subagents in "
                   f"parallel: {names}", thread_ts)

        with cf.ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
            futures = [pool.submit(run_subagent, t, dict(outputs), workdir)
                       for t in wave]
            for fut in cf.as_completed(futures):
                tid, out, dur, err = fut.result()
                outputs[tid] = out
                durations[tid] = dur
                if err:
                    failures[tid] = err
                log.info("[%s] done in %.0fs (%d chars)%s",
                         tid, dur, len(out), f" ERR={err}" if err else "")

        slack.post(f"*Progress after wave {wave_num}:*\n"
                   + plan_tree(subtasks, outputs, durations), thread_ts)

        # 3. REPLAN
        remaining = next_wave(subtasks, outputs)
        if NO_REPLAN or remaining or len(subtasks) >= MAX_TOTAL_TASKS:
            continue
        try:
            digest = "\n\n".join(
                f"[{t['id']}] {t['title']}:\n{outputs[t['id']][:800]}"
                for t in subtasks if t["id"] in outputs)
            verdict = complete_json(
                REPLAN_SYSTEM,
                f"GOAL: {plan.get('goal', TASK)}\n\nRESULTS SO FAR:\n{digest}",
                tier="smart")
            if not verdict.get("done", True):
                new = validate_plan({"subtasks": verdict.get("subtasks", [])})
                existing = {t["id"] for t in subtasks}
                new = [t for t in new if t["id"] not in existing]
                new = new[:MAX_TOTAL_TASKS - len(subtasks)]
                if new:
                    subtasks.extend(new)
                    slack.post(f"🔁 *Orchestrator added {len(new)} follow-up "
                               f"subtask(s):*\n"
                               + plan_tree(new, outputs, durations), thread_ts)
        except Exception as e:
            log.warning("replan skipped: %s", e)

    # 4. SYNTHESIZE
    slack.post("🧵 _Synthesizing final deliverable…_", thread_ts)
    digest = "\n\n".join(
        f"=== [{t['id']}] {t['title']} ===\n{outputs.get(t['id'], '(not run)')[:6000]}"
        for t in subtasks)
    try:
        final = complete(SYNTH_SYSTEM,
                         f"ORIGINAL TASK:\n{TASK}\n\nSUBAGENT OUTPUTS:\n{digest}",
                         tier="smart", max_tokens=4000)
    except Exception as e:
        final = f"(synthesis failed: {e})\n\nRaw outputs:\n{digest[:8000]}"

    total = sum(durations.values())
    wall = max(durations.values()) if durations else 0
    fail_note = (f"\n⚠️ {len(failures)} subagent(s) failed: "
                 f"{', '.join(failures)}" if failures else "")
    slack.post(final[:39000], thread_ts)
    slack.post(
        f"🎉 *Dynamic workflow complete* — {len(outputs)}/{len(subtasks)} "
        f"subtasks in {wave_num} wave(s)\n"
        f"_Compute: {total:.0f}s of agent time in ~{wall:.0f}s wall per wave "
        f"(parallel speedup)_{fail_note}\n"
        f"_Run ID: `{run_id}`_", thread_ts)

    # Artifacts from code subtasks
    files = [str(p.relative_to(workdir)) for p in Path(workdir).rglob("*")
             if p.is_file() and p.name != "CLAUDE.md"]
    if files:
        listing = "\n".join(f"  • `{f}`" for f in files[:30])
        slack.post(f"📁 *Files created ({len(files)}):*\n{listing}\n"
                   f"_Workdir: `{workdir}`_", thread_ts)

    # Persist state + KB
    (STATE_DIR / f"{run_id}.json").write_text(json.dumps({
        "run_id": run_id, "task": TASK, "plan": plan,
        "subtasks": subtasks, "durations": durations,
        "failures": failures, "workdir": workdir}, indent=2, default=str))
    try:
        from knowledge_base import get_kb
        get_kb().store_run(run_id, TASK,
                           {t["id"]: outputs.get(t["id"], "") for t in subtasks},
                           {t["id"]: 8 for t in subtasks if t["id"] in outputs},
                           model="dynamic")
    except Exception as e:
        log.debug("KB store skipped: %s", e)


if __name__ == "__main__":
    main()
