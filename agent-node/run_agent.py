from slack_logger import SlackLogger as _SL, init_logger as _init_logger
from knowledge_base import get_kb
"""
run_agent.py — Unified slash-command runner
Supports: /build  /plan  /deploy  /research
Flags:
  --crewai   Use Claude Sonnet (counts against daily limit)
  --batch    Use Claude via Batch API (50% cheaper, ~5-15min turnaround, implies --crewai)
  --github   (build only) push generated code to GitHub
Default model: qwen2.5-coder:7b  (local Ollama, free, no limit)
"""
import sys, os, re, logging, base64, json, time as _time, uuid
from pathlib import Path
from datetime import date
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ── env ───────────────────────────────────────────────────────────────────────
OPENROUTER_API_KEY = os.environ["OPENROUTER_API_KEY"]
SLACK_BOT_TOKEN    = os.environ["SLACK_BOT_TOKEN"]
SLACK_CHANNEL      = os.environ.get("SLACK_CHANNEL", "")
OLLAMA_URL         = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
GITHUB_TOKEN       = os.environ.get("GITHUB_TOKEN", "")
GITHUB_USER        = os.environ.get("GITHUB_USER", "")

from openai import OpenAI as _OpenAI
_or_client = _OpenAI(
    api_key=OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1",
)

# ── arg parsing ───────────────────────────────────────────────────────────────
raw_args = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""

USE_BATCH    = "--batch"  in raw_args.lower()
USE_CLAUDE   = "--crewai" in raw_args.lower() or USE_BATCH   # --batch implies --crewai
FORCE_HAIKU     = "--haiku"       in raw_args.lower()
FORCE_SONNET    = "--sonnet"      in raw_args.lower()
USE_CLAUDE_CODE = "--claude-code" in raw_args.lower()
UPLOAD_GITHUB = "--github" in raw_args.lower()

# First token is the command type, rest is the task
CMD_TYPE = sys.argv[1].lstrip("/").lower() if len(sys.argv) > 1 else "build"
TASK = re.sub(r"--crewai|--github|--batch|--haiku|--sonnet|--claude-code", "", " ".join(sys.argv[2:]), flags=re.IGNORECASE).strip()

VALID_CMDS = {"build", "plan", "deploy", "research"}
if CMD_TYPE not in VALID_CMDS:
    TASK = re.sub(r"--crewai|--github|--batch|--haiku|--sonnet|--claude-code", "", raw_args, flags=re.IGNORECASE).strip()
    CMD_TYPE = "build"

# ── SlackLogger setup ─────────────────────────────────────────────────────────
_slog = _init_logger(token=SLACK_BOT_TOKEN, channel=SLACK_CHANNEL)

# ── usage limiter (Claude only) ───────────────────────────────────────────────
USAGE_FILE           = Path(__file__).parent / "usage.json"
MAX_CLAUDE_CALLS_DAY = 10
MAX_TOKENS           = 1500

def _load_usage():
    today = str(date.today())
    if USAGE_FILE.exists():
        try:
            d = json.loads(USAGE_FILE.read_text())
            if d.get("date") == today:
                return d
        except Exception:
            pass
    return {"date": today, "claude_calls": 0}

def _save_usage(d):
    USAGE_FILE.write_text(json.dumps(d))

def check_limit():
    d = _load_usage()
    if d["claude_calls"] >= MAX_CLAUDE_CALLS_DAY:
        raise RuntimeError(
            f"⛔ Daily Claude limit reached ({MAX_CLAUDE_CALLS_DAY} calls). Resets at midnight.\n"
            f"_Tip: run without `--crewai` to use the free local model instead._"
        )
    d["claude_calls"] += 1
    _save_usage(d)
    rem = MAX_CLAUDE_CALLS_DAY - d["claude_calls"]
    logging.info(f"Claude call #{d['claude_calls']} today ({rem} remaining)")
    return d["claude_calls"]

def usage_line():
    d = _load_usage()
    used = d["claude_calls"]
    bar  = "▓" * used + "░" * (MAX_CLAUDE_CALLS_DAY - used)
    return f"📊 Claude today: `{bar}` {used}/{MAX_CLAUDE_CALLS_DAY}"

# ── Slack ─────────────────────────────────────────────────────────────────────
def post(text, channel=None):
    requests.post("https://slack.com/api/chat.postMessage",
        headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}",
                 "Content-Type": "application/json"},
        json={"channel": channel or SLACK_CHANNEL, "text": text}, timeout=10)

# ── Model routing ─────────────────────────────────────────────────────────────
# OpenRouter model IDs — override via OPENROUTER_MODEL / OPENROUTER_MODEL_FAST env vars
SONNET = os.environ.get("OPENROUTER_MODEL",      "qwen/qwen3.7-max")
HAIKU  = os.environ.get("OPENROUTER_MODEL_FAST", "qwen/qwen3-8b")

# Keywords that signal a task is complex enough to warrant Sonnet
_COMPLEX_KEYWORDS = {
    "complex", "advanced", "full", "complete", "production", "enterprise",
    "system", "architecture", "multiple", "integrate", "integration",
    "refactor", "migrate", "migration", "distributed", "scalable", "secure",
    "authentication", "database", "api", "framework", "pipeline", "microservice",
}

def pick_model(task: str) -> tuple[str, str]:
    """
    Return (model_id, reason) for a given task string.
    Haiku when task is short and simple; Sonnet when complex or long.
    --haiku / --sonnet flags override (checked via FORCE_HAIKU / FORCE_SONNET globals).
    """
    if FORCE_HAIKU:
        return HAIKU, "forced via --haiku"
    if FORCE_SONNET:
        return SONNET, "forced via --sonnet"

    words = task.lower().split()
    word_set = set(words)

    # Long task → Sonnet
    if len(task) > 300:
        return SONNET, f"task length {len(task)} > 300 chars"

    # Complex keywords → Sonnet
    hits = word_set & _COMPLEX_KEYWORDS
    if hits:
        return SONNET, f"complexity keywords: {', '.join(sorted(hits))}"

    # Short, simple task → Haiku
    return HAIKU, f"short simple task ({len(task)} chars) → Haiku"


# ── Static system prompts (cached via cache_control: ephemeral) ───────────────
# These are sent as the system prompt so Anthropic can cache them across calls.
# Dynamic task content goes in the user message — never in here.
SYSTEM_PROMPTS = {
    "build": (
        "You are a senior software engineer responding in Slack. "
        "When given a build task, provide complete, working code. "
        "Use ```language\n...\n``` blocks, one per file. "
        "Add a brief intro line explaining what you built. "
        f"Keep total response under {MAX_TOKENS} tokens."
    ),
    "plan": (
        "You are a senior software architect responding in Slack. "
        "When given a planning task, produce a detailed technical plan. "
        "Include: high-level design, components, data flow, tech stack choices with rationale, "
        "and ordered implementation steps. Format clearly for Slack. "
        f"Under {MAX_TOKENS} tokens."
    ),
    "deploy": (
        "You are a senior DevOps engineer responding in Slack. "
        "When given a deployment task, provide all necessary configuration files "
        "(Dockerfile, compose, CI/CD, scripts) using ```language\n...\n``` blocks, one per file. "
        f"Include a brief deployment guide. Under {MAX_TOKENS} tokens."
    ),
    "research": (
        "You are a senior engineer doing technical research for a Slack team. "
        "When given a research topic, provide: overview, key concepts, pros/cons/tradeoffs, "
        "best practices, and a clear recommendation. Format for Slack readability. "
        f"Under {MAX_TOKENS} tokens."
    ),
}

# ── LLM helpers ───────────────────────────────────────────────────────────────
def ask_claude(task, cmd_type="build"):
    """Call the brain LLM via OpenRouter (Qwen3 by default)."""
    check_limit()
    # Prepend KB prior knowledge if available (gracefully skips if chromadb not installed)
    try:
        prior = get_kb().query_prior_knowledge(task)
        if prior:
            task = prior + "\n\n---\n\n" + task
            logging.info("KB: injected %d chars into ask_claude", len(prior))
    except Exception as _kb_e:
        logging.debug("KB query skipped: %s", _kb_e)
    model, reason = pick_model(task)
    logging.info("Model routing: %s (%s)", model, reason)
    system_text = SYSTEM_PROMPTS.get(cmd_type, SYSTEM_PROMPTS["build"])
    resp = _or_client.chat.completions.create(
        model=model,
        max_tokens=MAX_TOKENS,
        messages=[
            {"role": "system", "content": system_text},
            {"role": "user",   "content": task},
        ],
    )
    logging.info(
        "OpenRouter usage — prompt: %d  completion: %d",
        resp.usage.prompt_tokens,
        resp.usage.completion_tokens,
    )
    return resp.choices[0].message.content


def ask_claude_batch(task, cmd_type="build"):
    """
    OpenRouter has no batch API — delegates straight to ask_claude().
    --batch flag is accepted but no longer queued; runs immediately.
    """
    logging.info("--batch flag detected but OpenRouter has no batch API; running immediately")
    return ask_claude(task, cmd_type)


def ask_claude_code(task, cmd_type="build"):
    """
    Run the task through Claude Code CLI (--print mode).
    Claude Code iterates, writes files, and self-corrects — better than raw API
    for code-heavy tasks. Falls back to ask_claude() if binary unavailable.
    """
    from claude_code_runner import run_claude_code, CLAUDE_CODE_AVAILABLE, list_created_files
    if not CLAUDE_CODE_AVAILABLE:
        logging.warning("Claude Code unavailable — falling back to API")
        return ask_claude(task, cmd_type)

    check_limit()
    system = (
        f"You are an expert assistant handling a /{cmd_type} request.\n"
        f"Work in the current directory. Create files as needed.\n"
        f"When done, print a clear summary of what you produced.\n"
    )
    # Guardrails doc rides along as system context on the Claude Code path too.
    try:
        from llm_client import _GUARDRAILS_DOC
        if _GUARDRAILS_DOC:
            system = _GUARDRAILS_DOC + "\n\n---\n\n" + system
    except ImportError:
        pass
    output, workdir = run_claude_code(task, system=system, timeout=600)

    files = list_created_files(workdir)
    if files:
        file_list = "\n".join(f"  • `{f}`" for f in files[:20])
        output += f"\n\n📁 *Files created:*\n{file_list}"

    return output


def ask_qwen(prompt, num_predict=1200):
    resp = requests.post(f"{OLLAMA_URL}/api/generate",
        json={"model": "qwen2.5-coder:7b", "prompt": prompt,
              "stream": False, "options": {"num_predict": num_predict}},
        timeout=300)
    resp.raise_for_status()
    return resp.json()["response"]

# ── Qwen prompt templates (local model — unchanged) ───────────────────────────
QWEN_PROMPTS = {
    "build": (
        "You are an expert software engineer. The user wants you to build the following.\n"
        "Respond with complete, working code only. Use ```language\n...\n``` blocks, one per file.\n"
        "Task: {task}"
    ),
    "plan": (
        "You are a software architect. Create a detailed technical plan for:\n{task}\n\n"
        "Include: overview, components, data flow, tech stack, and implementation steps. "
        "Use clear headings. Be specific and concise."
    ),
    "deploy": (
        "You are a DevOps engineer. Generate deployment configuration and scripts for:\n{task}\n\n"
        "Include relevant files: Dockerfile, docker-compose.yml, CI/CD config, shell scripts as needed. "
        "Use ```language\n...\n``` code blocks, one per file."
    ),
    "research": (
        "You are a technical researcher. Research and summarize the following topic thoroughly:\n{task}\n\n"
        "Cover: overview, key concepts, pros/cons or tradeoffs, best practices, and recommendations. "
        "Be factual and concise."
    ),
}

CMD_EMOJI = {"build": "🔨", "plan": "📐", "deploy": "🚀", "research": "🔍"}

# ── GitHub helpers ────────────────────────────────────────────────────────────
LANG_FILE = {
    "html":"index.html","css":"style.css","javascript":"script.js","js":"script.js",
    "typescript":"main.ts","ts":"main.ts","python":"main.py","py":"main.py",
    "bash":"run.sh","shell":"run.sh","sh":"run.sh","json":"config.json",
    "yaml":"config.yaml","yml":"config.yaml","sql":"schema.sql",
    "dockerfile":"Dockerfile","go":"main.go","rust":"main.rs","java":"Main.java",
    "toml":"config.toml","nginx":"nginx.conf","hcl":"main.tf",
}

def extract_code_blocks(text):
    files, counters = {}, {}
    for lang, code in re.findall(r"```(\w+)?\s*\n(.*?)```", text, re.DOTALL):
        lang = (lang or "txt").lower().strip()
        name = LANG_FILE.get(lang, f"file.{lang}")
        if name.endswith(".txt"):
            continue
        stem, ext = os.path.splitext(name)
        if name not in files:
            files[name] = code.strip()
        else:
            counters[name] = counters.get(name, 1) + 1
            files[f"{stem}_{counters[name]}{ext}"] = code.strip()
    return list(files.items())

def make_repo_name(task):
    stop = {"a","an","the","with","and","or","for","to","in","of","that","this",
            "build","create","design","make","write","generate","simple","basic"}
    words = re.sub(r"[^a-z0-9 ]", "", task.lower()).split()
    return "-".join(w for w in words if w not in stop)[:4*6+3] or "agent-project"

def push_files(full_name, files):
    pushed = []
    for fname, content in files:
        r = requests.put(
            f"https://api.github.com/repos/{full_name}/contents/{fname}",
            headers={"Authorization": f"token {GITHUB_TOKEN}",
                     "Accept": "application/vnd.github+json"},
            json={"message": f"Add {fname}", "content": base64.b64encode(content.encode()).decode()},
            timeout=30)
        if r.status_code in (200, 201):
            pushed.append(fname)
    return pushed

def upload_github(task, result):
    try:
        post("⏳ *Uploading to GitHub…*")
        files = extract_code_blocks(result)
        if not files:
            return "\n\n⚠️ *GitHub upload skipped* — no code blocks found."
        slug = make_repo_name(task)
        r = requests.post("https://api.github.com/user/repos",
            headers={"Authorization": f"token {GITHUB_TOKEN}",
                     "Accept": "application/vnd.github+json"},
            json={"name": slug, "description": f"AI-generated: {task[:72]}",
                  "private": False, "auto_init": True}, timeout=30)
        if r.status_code == 201:
            full_name = r.json()["full_name"]
        elif r.status_code == 422:
            full_name = f"{GITHUB_USER}/{slug}"
        else:
            return f"\n\n⚠️ *GitHub error {r.status_code}*"
        pushed = push_files(full_name, files)
        lines  = "\n".join(f"  • `{f}`" for f in pushed)
        return f"\n\n---\n📦 *Repo:* https://github.com/{full_name}\n*Files ({len(pushed)}):*\n{lines}"
    except Exception as e:
        return f"\n\n⚠️ *GitHub upload error:* `{e}`"

# ── main ──────────────────────────────────────────────────────────────────────
def run():
    emoji = CMD_EMOJI.get(CMD_TYPE, "⚙️")
    gh_note = " + GitHub upload" if UPLOAD_GITHUB else ""

    if USE_CLAUDE_CODE:
        model     = "Claude Code *(--claude-code)*"
        mode_note = " _(⚡ agentic — writes files, iterates)_"
    elif USE_BATCH:
        _routed_model, _reason = pick_model(TASK)
        _short = "haiku" if "haiku" in _routed_model else "sonnet"
        model     = f"Claude {_short} *(--batch)*"
        mode_note = f" _(⏳ batch — ~5–15 min, 50% cheaper | {_reason})_"
    else:
        _routed_model, _reason = pick_model(TASK)
        _short = "haiku" if "haiku" in _routed_model else "sonnet"
        model     = f"Claude {_short}"
        mode_note = f" _({_reason})_"

    _slog.start(title=f"/{CMD_TYPE}", task=TASK[:180], model=model.replace("*","").strip())
    post(f"{emoji} */{CMD_TYPE}* — running via {model}{gh_note}\n`{TASK[:100]}`{mode_note}")

    try:
        if USE_CLAUDE_CODE:
            result = ask_claude_code(TASK, CMD_TYPE)
            footer = f"\n\n{usage_line()}\n_⚡ Claude Code (agentic)_"

        elif USE_BATCH:
            post(f"⏳ _Submitted to Anthropic Batch API — will post result when ready. 50% cheaper!_")
            result = ask_claude_batch(TASK, CMD_TYPE)
            footer = f"\n\n{usage_line()}\n_✅ Processed via Batch API (50% discount applied)_"

        else:
            # Default: Claude with Haiku/Sonnet routing
            result = ask_claude(TASK, CMD_TYPE)
            footer = f"\n\n{usage_line()}"

        gh_suffix = upload_github(TASK, result) if UPLOAD_GITHUB else ""

        post(
            f"{emoji} */{CMD_TYPE} result*\n"
            f"*Task:* `{TASK}`\n"
            f"*Model:* {model}\n\n"
            f"{result}"
            f"{gh_suffix}"
            f"{footer}"
        )
        # Store result in KB so future runs can reference it
        try:
            import uuid as _uuid
            get_kb().store_stage(
                _uuid.uuid4().hex[:8], TASK, CMD_TYPE, result,
                score=8, model=model.replace("*","").strip(),
            )
        except Exception as _kb_e:
            logging.debug("KB store skipped: %s", _kb_e)
        _slog.done(f"/{CMD_TYPE} complete")

    except RuntimeError as e:
        _slog.error(f"/{CMD_TYPE} limit/batch error: {e}")
        post(f"⛔ {e}")
        sys.exit(1)
    except Exception as e:
        _slog.error(f"/{CMD_TYPE} error: `{e}`")
        sys.exit(1)

if __name__ == "__main__":
    logging.info(f"/{CMD_TYPE} | crewai={USE_CLAUDE} | batch={USE_BATCH} | github={UPLOAD_GITHUB} | task={TASK[:60]}")
    run()
