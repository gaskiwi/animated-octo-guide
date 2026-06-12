from slack_logger import SlackLogger as _SL, init_logger as _init_logger
"""
run_pipeline.py — Multi-step autonomous pipeline with CrewAI + self-evaluation + checkpoints

Stages (always in order, subset selectable):
  research → plan → build → test → deploy

After each stage:
  1. Evaluator scores output (1-10). If < 7, reruns with critique (max 2 retries).
  2. If --review flag: posts to Slack and waits for reaction before proceeding.
     React with ✅ to continue, ✏️ to revise (then reply with feedback), ⏹️ to stop.
  3. Each stage's output is fed as context to the next.

Usage:
  python3 run_pipeline.py "build a workout tracker REST API"
  python3 run_pipeline.py --crewai "build a workout tracker REST API"
  python3 run_pipeline.py --review "build a workout tracker REST API"
  python3 run_pipeline.py --crewai --review --steps research,plan,build "vague idea"
"""

import sys
import os
import json
import logging
import textwrap
import time
import re
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
import requests
from research_tools import research_topic, get_crewai_tools
from knowledge_base import get_kb

load_dotenv(Path(__file__).parent / ".env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pipeline")  # FIX: `log` was used below but never defined (NameError)

# ── Config ────────────────────────────────────────────────────────────────────
SLACK_TOKEN    = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL  = os.environ.get("SLACK_CHANNEL", "")
OLLAMA_URL     = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
STATE_DIR      = Path("/tmp/pipeline_states")
STATE_DIR.mkdir(exist_ok=True)

QUALITY_THRESHOLD  = 7       # minimum score to pass a stage without retry
MAX_RETRIES        = 2       # max reruns of a failing stage
CHECKPOINT_TIMEOUT = 1800    # 30 min before auto-proceeding at a checkpoint
POLL_INTERVAL      = 10      # seconds between reaction polls

SONNET = "claude-sonnet-4-6"
HAIKU  = "claude-haiku-4-5-20251001"

# Stages that produce formulaic output route to Haiku (cheaper).
# Reasoning-heavy stages stay on Sonnet.
STAGE_MODEL = {
    "research": SONNET,  # deep synthesis
    "plan":     SONNET,  # architecture decisions
    "build":    SONNET,  # code quality matters
    "test":     HAIKU,   # formulaic test patterns
    "deploy":   HAIKU,   # formulaic Dockerfile/compose
}

ALL_STAGES = ["research", "plan", "build", "test", "deploy"]

STAGE_EMOJI = {
    "research": "🔍",
    "plan":     "📋",
    "build":    "🏗️",
    "test":     "🧪",
    "deploy":   "🚀",
}

# ── Parse args ────────────────────────────────────────────────────────────────
raw_args   = sys.argv[1:]
USE_CREWAI = "--crewai" in raw_args
USE_REVIEW      = "--review"      in raw_args
USE_CLAUDE_CODE = "--claude-code" in raw_args
raw_args   = [a for a in raw_args if a not in ("--crewai", "--review", "--claude-code")]

# --steps research,plan,build
steps_flag = next((a for a in raw_args if a.startswith("--steps")), None)
if steps_flag:
    raw_args.remove(steps_flag)
    STAGES = [s.strip() for s in steps_flag.replace("--steps", "").strip("= ").split(",") if s.strip() in ALL_STAGES]
    if not STAGES:
        STAGES = ALL_STAGES
else:
    STAGES = ALL_STAGES

# --resume <run_id> — continue from a saved state file
resume_flag = next((a for a in raw_args if a.startswith("--resume")), None)
RESUME_ID = resume_flag.replace("--resume", "").strip("= ") if resume_flag else None
if resume_flag:
    raw_args = [a for a in raw_args if not a.startswith("--resume")]

# --depth quick/standard/deep
depth_flag = next((a for a in raw_args if a.startswith("--depth")), None)
if depth_flag:
    raw_args.remove(depth_flag)
    RESEARCH_DEPTH = depth_flag.replace("--depth", "").strip("= ") or "standard"
else:
    RESEARCH_DEPTH = "standard"

TASK = " ".join(a for a in raw_args if not a.startswith("--")).strip()

# If launched from gateway with a file attachment, full markdown content
# (newlines preserved) is in OPENCLAW_TASK.  Strip leading flag tokens to
# get the clean task text; everything after is preserved verbatim.
_env_task = os.environ.get("OPENCLAW_TASK", "")
if _env_task:
    import re as _re
    # Remove flag tokens and their values from the START of the string only
    _cleaned = _re.sub(r'^(\s*--\w[\w-]*(?:\s+[^-\s]\S*)?\s*)+', '', _env_task).strip()
    if _cleaned:
        TASK = _cleaned
        logging.info("TASK loaded from OPENCLAW_TASK env var (%d chars)", len(TASK))

if not TASK:
    import requests as _rq, os as _os
    _ch  = _os.environ.get("SLACK_CHANNEL", "")
    _tok = _os.environ.get("SLACK_BOT_TOKEN", "")
    if _ch and _tok:
        _rq.post("https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {_tok}", "Content-Type": "application/json"},
            json={"channel": _ch, "text": (
                ":x: */pipeline* \u2014 no task text provided.\n"
                "Add a description after the flags, or attach a file with `--with-file`."
            )}, timeout=5)
    sys.exit(1)

# ── Slack helpers ─────────────────────────────────────────────────────────────
def slack_post(text, thread_ts=None, blocks=None):
    payload = {"channel": SLACK_CHANNEL, "text": text}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    if blocks:
        payload["blocks"] = blocks
    resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {SLACK_TOKEN}", "Content-Type": "application/json"},
        json=payload, timeout=10
    )
    data = resp.json()
    return data.get("ts"), data.get("ok")

def slack_update(ts, text, blocks=None):
    payload = {"channel": SLACK_CHANNEL, "ts": ts, "text": text}
    if blocks:
        payload["blocks"] = blocks
    requests.post(
        "https://slack.com/api/chat.update",
        headers={"Authorization": f"Bearer {SLACK_TOKEN}", "Content-Type": "application/json"},
        json=payload, timeout=10
    )

def slack_add_reaction(ts, emoji):
    requests.post(
        "https://slack.com/api/reactions.add",
        headers={"Authorization": f"Bearer {SLACK_TOKEN}", "Content-Type": "application/json"},
        json={"channel": SLACK_CHANNEL, "timestamp": ts, "name": emoji}, timeout=10
    )

def slack_get_reactions(ts):
    """Return list of reaction names on a message."""
    resp = requests.get(
        "https://slack.com/api/reactions.get",
        headers={"Authorization": f"Bearer {SLACK_TOKEN}"},
        params={"channel": SLACK_CHANNEL, "timestamp": ts}, timeout=10
    )
    data = resp.json()
    if not data.get("ok"):
        return []
    reactions = data.get("message", {}).get("reactions", [])
    return [r["name"] for r in reactions]

def slack_get_thread_replies(ts):
    """Get replies in a thread, returning latest non-bot message text."""
    resp = requests.get(
        "https://slack.com/api/conversations.replies",
        headers={"Authorization": f"Bearer {SLACK_TOKEN}"},
        params={"channel": SLACK_CHANNEL, "ts": ts, "limit": 10}, timeout=10
    )
    data = resp.json()
    messages = data.get("messages", [])
    # Get messages after the original (index 0), from humans not bot
    for msg in reversed(messages[1:]):
        if not msg.get("bot_id") and msg.get("text"):
            return msg["text"]
    return ""

def build_progress_bar(stages, current_stage, stage_scores):
    """Build a visual stage progress indicator."""
    parts = []
    for s in stages:
        emoji = STAGE_EMOJI.get(s, "▪️")
        score = stage_scores.get(s)
        if s == current_stage:
            parts.append(f"*{emoji} {s.upper()}* ⟵")
        elif score is not None:
            parts.append(f"~{emoji} {s}~ ✓{score}/10")
        else:
            parts.append(f"◻️ {s}")
    return " → ".join(parts)

# ── qwen ──────────────────────────────────────────────────────────────────────
def ask_qwen(prompt, num_predict=3000):
    resp = requests.post(f"{OLLAMA_URL}/api/generate",
        json={"model": "qwen2.5-coder:7b", "prompt": prompt,
              "stream": False, "options": {"num_predict": num_predict}},
        timeout=600)
    resp.raise_for_status()
    return resp.json()["response"].strip()

# ── Stage prompts ─────────────────────────────────────────────────────────────
STAGE_SYSTEM = {
    "research": textwrap.dedent("""
        You are a Research Analyst. Your job is to deeply understand a project idea and gather all
        relevant technical context. Cover: what the project is, key technical components needed,
        relevant libraries/frameworks, potential challenges, similar existing solutions, and
        recommended tech stack. Be specific and thorough — your output feeds into a planning stage.
    """),
    "plan": textwrap.dedent("""
        You are a Software Architect. Given research context, produce a detailed implementation plan.
        Include: project structure (files/folders), data models, API endpoints or interfaces,
        key algorithms, dependencies list, implementation order (what to build first),
        and any architecture decisions. Be precise — your output will be used to write actual code.
    """),
    "build": textwrap.dedent("""
        You are a Senior Software Engineer. Given a plan, write the complete implementation.
        Produce production-quality code with proper error handling, comments, and structure.
        Output each file clearly labeled with its path. Cover all components in the plan.
    """),
    "test": textwrap.dedent("""
        You are a QA Engineer. Given an implementation, write a comprehensive test suite.
        Include: unit tests for core functions, integration tests, edge case tests,
        and a test plan describing how to run them. Also identify any bugs or issues you spot
        in the implementation and suggest fixes.
    """),
    "deploy": textwrap.dedent("""
        You are a DevOps Engineer. Given a tested implementation, produce everything needed to deploy it:
        Dockerfile, docker-compose.yml, environment variable template (.env.example),
        deployment instructions, and a health check endpoint if applicable.
        Make it ready to run on a Linux server with Docker.
    """),
}

EVAL_SYSTEM = textwrap.dedent("""
    You are a strict technical reviewer evaluating pipeline stage output.
    Score the output 1-10 on: completeness, technical accuracy, and readiness for the next stage.
    A score of 7+ means it's good enough to proceed. Below 7 means it needs improvement.

    Respond in EXACTLY this format:
    SCORE: X
    PROCEED: yes/no
    CRITIQUE: [specific issues and what's missing — be actionable]
""")

def build_stage_prompt(stage, task, context, critique=None):
    ctx_section = f"\n\nCONTEXT FROM PREVIOUS STAGES:\n{context[-6000:]}" if context else ""
    retry_section = f"\n\nPREVIOUS ATTEMPT CRITIQUE (fix these issues):\n{critique}" if critique else ""
    return f"{STAGE_SYSTEM[stage].strip()}\n\nTASK: {task}{ctx_section}{retry_section}\n\nProduce your {stage} output now:"

def _ask_haiku_eval(prompt: str) -> str:
    """Call Claude Haiku for evaluation — cheap, fast, no local model needed."""
    import anthropic as _ant
    client = _ant.Anthropic(api_key=ANTHROPIC_KEY)
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
        system=[{"type": "text", "text": EVAL_SYSTEM,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text


def evaluate_output(stage, task, output):
    prompt = f"STAGE: {stage}\nTASK: {task}\nOUTPUT TO EVALUATE:\n{output[:4000]}"
    raw = _ask_haiku_eval(prompt)
    score = 5
    proceed = False
    critique = ""
    for line in raw.split("\n"):
        line = line.strip()
        if line.startswith("SCORE:"):
            try:
                score = int(re.search(r"\d+", line).group())
            except Exception:
                pass
        elif line.startswith("PROCEED:"):
            proceed = "yes" in line.lower()
        elif line.startswith("CRITIQUE:"):
            critique = line.replace("CRITIQUE:", "").strip()
    # Fallback if parsing failed
    if not critique:
        critique = raw[:300]
    proceed = score >= QUALITY_THRESHOLD
    return score, proceed, critique

# ── CrewAI pipeline ───────────────────────────────────────────────────────────

def run_claude_direct_stage(stage, task, context, critique=None):
    """
    Direct Anthropic API call with a cached system prompt.
    Cheaper than the crewai path: system prompt is cached (90% off input tokens)
    and we avoid the LangChain overhead that strips cache_control support.
    Used for all stages except research (which needs live crewai tools).
    """
    import anthropic as _anthropic
    client = _anthropic.Anthropic(api_key=ANTHROPIC_KEY)

    ctx_section   = (
        "\n\nCONTEXT FROM PREVIOUS STAGES:\n" + context[-6000:]
        if context else ""
    )
    retry_section = (
        "\n\nPREVIOUS ATTEMPT CRITIQUE (fix these issues):\n" + critique
        if critique else ""
    )
    user_msg = f"TASK: {task}" + ctx_section + retry_section + "\n\nProduce your " + stage + " output now:"

    model = STAGE_MODEL.get(stage, SONNET)
    logging.info("Pipeline routing: stage=%s model=%s", stage, model)
    resp = client.messages.create(
        model=model,
        max_tokens=4000,
        system=[{
            "type": "text",
            "text": STAGE_SYSTEM[stage].strip(),
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": user_msg}],
    )
    logging.info(
        "Pipeline Claude usage [%s/%s] — input: %d (cache_read: %d, cache_create: %d) output: %d",
        stage, model,
        resp.usage.input_tokens,
        getattr(resp.usage, "cache_read_input_tokens", 0),
        getattr(resp.usage, "cache_creation_input_tokens", 0),
        resp.usage.output_tokens,
    )
    return resp.content[0].text


def run_crewai_stage(stage, task, context, critique=None):
    """Run a single stage using CrewAI with Claude Sonnet.
    Non-research stages use the direct Anthropic API with cached system prompts
    (cheaper and simpler). Research stage keeps crewai for live tool access.
    """
    # Non-research stages: direct Anthropic API with cached system prompt
    if stage != "research":
        return run_claude_direct_stage(stage, task, context, critique)

    # Research stage: fetch live sources, then synthesize with Claude + caching
    try:
        raw_findings = research_topic(task, depth=RESEARCH_DEPTH)
        logging.info("Research sweep: %d chars", len(raw_findings))
    except Exception as e:
        logging.warning("Research sweep failed: %s", e)
        raw_findings = f"(Research sweep unavailable: {e})"

    ctx_section   = ("\n\nCONTEXT FROM PREVIOUS STAGES:\n" + context[-4000:]) if context else ""
    retry_section = ("\n\nPREVIOUS ATTEMPT CRITIQUE:\n" + critique) if critique else ""
    user_msg = (
        "TASK: " + task + ctx_section + retry_section +
        "\n\nLIVE RESEARCH FINDINGS (use as primary sources, cite where relevant):\n" +
        raw_findings[:8000] +
        "\n\nSynthesise the above into a comprehensive research report now."
    )

    import anthropic as _anthropic
    client = _anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    resp = client.messages.create(
        model=STAGE_MODEL.get("research", SONNET),
        max_tokens=4000,
        system=[{
            "type": "text",
            "text": STAGE_SYSTEM["research"].strip(),
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": user_msg}],
    )
    logging.info(
        "Pipeline Claude usage [research] — input: %d (cache_read: %d) output: %d",
        resp.usage.input_tokens,
        getattr(resp.usage, "cache_read_input_tokens", 0),
        resp.usage.output_tokens,
    )
    return resp.content[0].text

def run_claude_code_stage(stage, task, context, critique, workdir):
    """
    Run a pipeline stage using Claude Code CLI.
    Reuses the same workdir across all stages so Claude Code can read/edit
    files produced by earlier stages — this is the key advantage over the API.
    """
    from claude_code_runner import run_claude_code, CLAUDE_CODE_AVAILABLE
    if not CLAUDE_CODE_AVAILABLE:
        logging.warning("Claude Code unavailable — falling back to direct API for %s", stage)
        return run_claude_direct_stage(stage, task, context, critique)

    ctx_section   = f"\n\nCONTEXT FROM PREVIOUS STAGES:\n{context[-6000:]}" if context else ""
    retry_section = f"\n\nPREVIOUS ATTEMPT CRITIQUE (fix these):\n{critique}" if critique else ""

    prompt = (
        f"{STAGE_SYSTEM[stage].strip()}\n\n"
        f"TASK: {task}"
        f"{ctx_section}"
        f"{retry_section}"
        f"\n\nProduce your {stage} output now. "
        f"Write any code files directly to disk in the current directory."
    )

    system_md = (
        f"# Pipeline Stage: {stage.upper()}\n\n"
        f"You are running the **{stage}** stage of a multi-stage autonomous pipeline.\n"
        f"- Previous stage outputs may exist as files in this directory — read them.\n"
        f"- Write all code and artifacts as files to this directory.\n"
        f"- End your response with a clear stage summary.\n"
    )

    output, _ = run_claude_code(prompt, workdir=workdir, system=system_md, timeout=2700)
    logging.info("Claude Code stage %s complete: %d chars", stage, len(output))
    return output


def run_stage(stage, task, context, critique=None, workdir=None):
    """
    Route to Claude Code or direct API.
    With --claude-code: only the build stage uses Claude Code (agentic file-writing).
    All other stages use direct Anthropic API — same quality, much cheaper
    since Claude Code defaults to Opus+thinking which is 5x more expensive.
    """
    if USE_CLAUDE_CODE and workdir and stage == "build":
        return run_claude_code_stage(stage, task, context, critique, workdir)
    return run_crewai_stage(stage, task, context, critique)


def _run_qwen_research(task, context, critique):
    """
    qwen research: gather live sources first, then synthesise.
    """
    # Notify Slack that we're fetching sources
    if 'thread_ts' in globals() and thread_ts:
        slack_post(
            f"🔬 _Gathering sources: ArXiv → Semantic Scholar → Wikipedia → Web…_",
            thread_ts=thread_ts
        )

    try:
        raw_findings = research_topic(task, depth=RESEARCH_DEPTH)
        log.info("Research sweep complete: %d chars", len(raw_findings))
    except Exception as e:
        log.error("Research sweep failed: %s", e)
        raw_findings = f"(Research sweep failed: {e} — proceeding from model knowledge)"

    # Inject findings into the research prompt
    prompt = (
        STAGE_SYSTEM["research"].strip() + "\n\n"
        f"TASK: {task}\n\n"
        f"LIVE RESEARCH FINDINGS (use these as your primary sources):\n"
        f"{raw_findings[:8000]}\n\n"
        + (f"CONTEXT FROM PREVIOUS STAGES:\n{context[-3000:]}\n\n" if context else "")
        + (f"PREVIOUS ATTEMPT CRITIQUE:\n{critique}\n\n" if critique else "")
        + "Now synthesise the above findings into a comprehensive research report. "
          "Cite specific papers by ArXiv ID or author/year where relevant. "
          "Identify key findings, open questions, and implications for the task."
    )
    import anthropic as _ant
    client = _ant.Anthropic(api_key=ANTHROPIC_KEY)
    resp = client.messages.create(
        model=STAGE_MODEL.get('research', SONNET),
        max_tokens=3000,
        system=[{'type': 'text', 'text': STAGE_SYSTEM['research'].strip(),
                 'cache_control': {'type': 'ephemeral'}}],
        messages=[{'role': 'user', 'content': prompt}],
    )
    return resp.content[0].text

# ── Checkpoint: wait for Slack reaction ──────────────────────────────────────
def wait_for_checkpoint(stage, output, thread_ts, stage_scores):
    """
    Post stage output and wait for user reaction.
    Returns: ('proceed', feedback_text) or ('stop', '') or ('proceed', feedback)
    """
    preview = output[:1200] + "\n…(truncated)" if len(output) > 1200 else output
    msg = (
        f"{STAGE_EMOJI.get(stage, '▪️')} *{stage.upper()} complete* — score {stage_scores[stage]}/10\n\n"
        f"```{preview}```\n\n"
        f"React to this message:\n"
        f"  ✅ — looks good, proceed to next stage\n"
        f"  ✏️ — I have feedback (reply in thread with your notes)\n"
        f"  ⏹️ — stop the pipeline here\n"
        f"_(auto-proceeds in 30 min if no reaction)_"
    )
    msg_ts, _ = slack_post(msg, thread_ts=thread_ts)
    if not msg_ts:
        return "proceed", ""

    # Add bot reactions as hints
    for emoji in ["white_check_mark", "pencil2", "stop_button"]:
        slack_add_reaction(msg_ts, emoji)
        time.sleep(0.3)

    deadline = time.time() + CHECKPOINT_TIMEOUT
    while time.time() < deadline:
        time.sleep(POLL_INTERVAL)
        reactions = slack_get_reactions(msg_ts)

        if "stop_button" in reactions:
            slack_post("⏹️ Pipeline stopped by user.", thread_ts=thread_ts)
            return "stop", ""

        if "pencil2" in reactions or "pencil" in reactions:
            feedback = slack_get_thread_replies(msg_ts)
            if feedback:
                slack_post(f"✏️ Got your feedback — incorporating into next stage.", thread_ts=thread_ts)
                return "revise", feedback
            # Wait a bit more for them to type the reply
            continue

        if "white_check_mark" in reactions:
            return "proceed", ""

    # Timed out — auto-proceed
    slack_post(f"⏱️ No reaction after 30 min — auto-proceeding past {stage}.", thread_ts=thread_ts)
    return "proceed", ""

# ── Save/load pipeline state ──────────────────────────────────────────────────
def save_state(run_id, state):
    (STATE_DIR / f"{run_id}.json").write_text(json.dumps(state, indent=2))

def load_state(run_id):
    p = STATE_DIR / f"{run_id}.json"
    return json.loads(p.read_text()) if p.exists() else {}

# ── Main pipeline ─────────────────────────────────────────────────────────────
def main():
    run_id    = datetime.now().strftime("%Y%m%d_%H%M%S")
    mode_tag  = ("⚡ Claude Code" if USE_CLAUDE_CODE else "🤖 Claude") + (" + checkpoints" if USE_REVIEW else "")
    results   = {}
    stage_scores = {}

    # Always-on KB: prepend relevant prior knowledge to the initial context.
    # Gracefully skips if chromadb isn't available yet.
    import tempfile as _tmpfile
    from claude_code_runner import CLAUDE_CODE_AVAILABLE as _CC_AVAIL
    cc_workdir = _tmpfile.mkdtemp(prefix=f"pipeline_{run_id}_") if (USE_CLAUDE_CODE and _CC_AVAIL) else None
    if cc_workdir:
        logging.info("Claude Code workdir: %s", cc_workdir)

    context = ""
    try:
        prior = get_kb().query_prior_knowledge(TASK)
        if prior:
            context = prior + "\n\n"
            logging.info("KB: injected %d chars of prior knowledge", len(prior))
    except Exception as _kb_e:
        logging.debug("KB query skipped: %s", _kb_e)

    logging.info(f"Pipeline start: run_id={run_id} stages={STAGES} crewai={USE_CREWAI} review={USE_REVIEW}")
    _slog = _init_logger(token=SLACK_TOKEN, channel=SLACK_CHANNEL)
    model_name = "Claude Code" if USE_CLAUDE_CODE else ("Claude Sonnet" if USE_CREWAI else "qwen2.5-coder")
    # Opening Slack message — single thread for everything
    progress = build_progress_bar(STAGES, STAGES[0], stage_scores)
    header = (
        f"🔄 *Pipeline started* — {mode_tag}\n"
        f"Task: `{TASK[:120]}`\n\n"
        f"{progress}"
    )
    thread_ts, _ = slack_post(header)
    if not thread_ts:
        logging.error("Could not post to Slack — check SLACK_BOT_TOKEN and SLACK_CHANNEL")
        sys.exit(1)

    # Wire _slog into the same thread so all messages stay consolidated
    import threading as _threading
    _slog.job_title  = "🔄 /pipeline"
    _slog.job_task   = TASK[:200]
    _slog.job_model  = model_name
    _slog.start_time = time.time()
    _slog.thread_ts  = thread_ts
    _slog.status_ts  = _slog._post("⏳ Starting up…", thread=True)
    _slog._stop_heartbeat.clear()
    _slog._heartbeat_thread = _threading.Thread(
        target=_slog._heartbeat_loop, daemon=True)
    _slog._heartbeat_thread.start()

    state = {"run_id": run_id, "task": TASK, "stages": STAGES, "thread_ts": thread_ts, "results": {}}
    save_state(run_id, state)

    task_handle = TASK  # may be compressed after research stage

    # --resume: load previous stage outputs to skip already-done work
    if RESUME_ID:
        _resume_file = STATE_DIR / f"{RESUME_ID}.json"
        if _resume_file.exists():
            _saved = json.loads(_resume_file.read_text())
            _saved_results = _saved.get("results", {})
            _saved_scores  = _saved.get("scores", {})
            _loaded = []
            for _stage, _output in _saved_results.items():
                if _stage not in STAGES:  # only load stages we're skipping
                    results[_stage]      = _output
                    stage_scores[_stage] = _saved_scores.get(_stage, 8)
                    context += f"\n\n{'='*40}\n{_stage.upper()} OUTPUT:\n{_output[:1500]}"
                    _loaded.append(_stage)
            if _loaded:
                logging.info("Resumed: loaded %s from run %s", _loaded, RESUME_ID)
                # Compress task handle now that research is loaded into context
                if "research" in _loaded and len(TASK) > 2000:
                    task_handle = TASK[:300] + "\n...(full context in research output above)"
                    logging.info("Task compressed for resume: %d -> %d chars", len(TASK), len(task_handle))
                slack_post(
                    f"♻️ *Resuming run `{RESUME_ID}`* — skipping {_loaded}, starting from {STAGES[0]}",
                    thread_ts=thread_ts,
                )
        else:
            logging.warning("Resume file not found: %s", _resume_file)

    for i, stage in enumerate(STAGES):
        logging.info(f"Stage: {stage}")

        # Update progress bar
        progress = build_progress_bar(STAGES, stage, stage_scores)
        slack_post(f"{STAGE_EMOJI.get(stage, '▪️')} *Running {stage}…*\n{progress}", thread_ts=thread_ts)

        output     = None
        score      = 0
        critique   = None
        extra_ctx  = ""  # user feedback from checkpoint

        for attempt in range(1, MAX_RETRIES + 2):  # attempts: 1, 2, 3
            # Run the stage
            full_context = context + (f"\n\nUSER FEEDBACK: {extra_ctx}" if extra_ctx else "")
            _slog.thinking(f"Running {stage} via {model_name} (attempt {attempt}/{MAX_RETRIES+1})…")
            try:
                output = run_stage(
                    stage,
                    task_handle if stage != "research" else TASK,
                    full_context,
                    critique if attempt > 1 else None,
                    workdir=cc_workdir,
                )
            except RuntimeError as _cc_err:
                logging.warning("Claude Code failed (%s) — falling back to direct API for %s", _cc_err, stage)
                slack_post(f":warning: Claude Code timed out on {stage} — falling back to direct API", thread_ts=thread_ts)
                output = run_crewai_stage(stage,
                    task_handle if stage != "research" else TASK,
                    full_context,
                    critique if attempt > 1 else None)

            # Evaluate output
            slack_post(f"🔎 _Evaluating {stage} output (attempt {attempt})…_", thread_ts=thread_ts)
            _slog.thinking(f"Evaluator scoring {stage} output…")
            score, passed, critique = evaluate_output(stage, TASK, output)
            stage_scores[stage] = score

            logging.info(f"  {stage} attempt {attempt}: score={score} passed={passed}")

            if passed:
                break

            if attempt <= MAX_RETRIES:
                slack_post(
                    f"⚠️ {stage} scored {score}/10 — retrying (attempt {attempt+1}/{MAX_RETRIES+1})\n"
                    f"_Critique: {critique[:200]}_",
                    thread_ts=thread_ts
                )
            else:
                slack_post(
                    f"⚠️ {stage} scored {score}/10 after {MAX_RETRIES+1} attempts — proceeding anyway\n"
                    f"_Final critique: {critique[:200]}_",
                    thread_ts=thread_ts
                )

        # Store result
        results[stage] = output
        # Persist to knowledge base
        try:
            get_kb().store_stage(run_id, TASK, stage, output,
                                 score=stage_scores.get(stage, 0),
                                 model='Claude Sonnet' if USE_CREWAI else 'qwen')
        except Exception as _kb_e:
            log.warning('KB store_stage failed: %s', _kb_e)
        state["results"][stage] = output
        save_state(run_id, state)

        # Checkpoint (--review mode)
        if USE_REVIEW:
            action, feedback = wait_for_checkpoint(stage, output, thread_ts, stage_scores)
            if action == "stop":
                slack_post(
                    f"⏹️ *Pipeline stopped after {stage}.*\n"
                    f"Results so far saved to `/tmp/pipeline_states/{run_id}.json`",
                    thread_ts=thread_ts
                )
                return
            elif action == "revise":
                # Re-run this stage with user feedback
                extra_ctx = feedback
                slack_post(f"✏️ _Re-running {stage} with your feedback…_", thread_ts=thread_ts)
                output = run_stage(stage, TASK, context + f"\n\nUSER FEEDBACK TO INCORPORATE: {feedback}")
                score, _, _ = evaluate_output(stage, TASK, output)
                stage_scores[stage] = score
                results[stage] = output
                state["results"][stage] = output
                save_state(run_id, state)
                slack_post(f"✅ {stage} revised — score {score}/10", thread_ts=thread_ts)
        else:
            # Non-review: post a brief summary
            preview = output[:600] + "…" if len(output) > 600 else output
            slack_post(
                f"✅ *{stage} done* — score {stage_scores[stage]}/10\n```{preview}```",
                thread_ts=thread_ts
            )

        _slog.step(f"{STAGE_EMOJI.get(stage,'▪️')} {stage} complete", detail=f"Score {stage_scores.get(stage,'?')}/10")
        # Accumulate context for next stage
        context += f"\n\n{'='*40}\n{stage.upper()} OUTPUT:\n{output[:1500]}"
        # After research, replace the full task with a short handle so subsequent
        # stages don't re-embed the entire source file on every API call.
        if stage == "research" and len(TASK) > 2000:
            task_handle = TASK[:300] + "\n...(see research output above for full context)"
            logging.info("Task compressed: %d → %d chars for remaining stages",
                         len(TASK), len(task_handle))
        else:
            task_handle = TASK

        # Small delay between stages
        if i < len(STAGES) - 1:
            time.sleep(2)

    # ── Final summary ──────────────────────────────────────────────────────────
    progress = build_progress_bar(STAGES, None, stage_scores)
    avg_score = sum(stage_scores.values()) / len(stage_scores) if stage_scores else 0

    summary_lines = [f"• *{s}*: {stage_scores.get(s, '?')}/10" for s in STAGES]
    if USE_CLAUDE_CODE:
        stage_models = "Claude Code (agentic)"
    else:
        stage_models = " · ".join(
            f"{s}={'haiku' if 'haiku' in STAGE_MODEL.get(s, SONNET) else 'sonnet'}"
            for s in STAGES
        )
    final_msg = (
        f"🎉 *Pipeline complete!*\n\n"
        f"{progress}\n\n"
        f"*Stage scores:*\n" + "\n".join(summary_lines) + "\n\n"
        f"*Overall: {avg_score:.1f}/10*\n"
        f"_Models: {stage_models} · Run ID: `{run_id}`_"
    )
    slack_post(final_msg, thread_ts=thread_ts)
    _slog.done(f"Pipeline complete — avg {avg_score:.1f}/10 across {len(STAGES)} stages")

    # Persist complete run to knowledge base
    try:
        get_kb().store_run(run_id, TASK, results, stage_scores,
                           model='Claude Code' if USE_CLAUDE_CODE else 'Claude')
        kb_stats = get_kb().stats()
        slack_post(
            f"🧠 *Knowledge base updated* — "
            f"{kb_stats.get('task_stages', '?')} stage docs, "
            f"{kb_stats.get('research_docs', '?')} research chunks stored\n"
            f"_Use `--knowledge_base` on your next run to pull this context in._",
            thread_ts=thread_ts
        )
    except Exception as _kb_e:
        log.warning('KB store_run failed: %s', _kb_e)

    # Save final state
    if cc_workdir:
        try:
            from claude_code_runner import archive_workdir, list_created_files
            files = list_created_files(cc_workdir)
            zip_path = archive_workdir(cc_workdir, run_id)
            if files:
                file_list = "\n".join(f"  • `{f}`" for f in files[:30])
                slack_post(
                    f"📁 *Claude Code artifacts ({len(files)} files):*\n{file_list}\n"
                    f"_Archived to vault: `{zip_path}`_",
                    thread_ts=thread_ts,
                )
        except Exception as _ae:
            logging.warning("Workdir archive failed: %s", _ae)

    state["completed"] = True
    state["scores"] = stage_scores
    save_state(run_id, state)
    logging.info(f"Pipeline complete: run_id={run_id} avg_score={avg_score:.1f}")

if __name__ == "__main__":
    main()
