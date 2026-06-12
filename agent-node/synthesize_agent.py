import os, sys, re, logging, requests
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
SLACK_BOT_TOKEN   = os.environ.get("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL     = os.environ.get("SLACK_CHANNEL", "")
SLACK_LOG_CHANNEL = os.environ.get("SLACK_LOG_CHANNEL", "") or SLACK_CHANNEL
_task_file = os.environ.get("OPENCLAW_TASK_FILE", "")
CONVERSATION = open(_task_file, encoding="utf-8").read() if _task_file and os.path.exists(_task_file) else os.environ.get("OPENCLAW_TASK", "")

# Strip --batch flag from conversation text and set USE_BATCH
USE_BATCH       = "--batch"       in CONVERSATION
USE_CLAUDE_CODE = "--claude-code" in CONVERSATION
if USE_BATCH:
    CONVERSATION = CONVERSATION.replace("--batch", "").strip()
    log.info("Batch mode enabled for synthesis")
if USE_CLAUDE_CODE:
    CONVERSATION = CONVERSATION.replace("--claude-code", "").strip()
    log.info("Claude Code mode enabled for synthesis")
VAULT_ROOT        = Path(os.environ.get("VAULT_ROOT", "/home/pacers4ever/vault"))

SYNTHESIS_MODEL = os.environ.get("OPENROUTER_MODEL", "qwen/qwen3.7-max")

SYNTHESIS_SYSTEM = """You are a technical research synthesizer. Your job is to read a raw research conversation — which contains half-formed ideas, dead ends, contradictions, and exploratory thinking — and produce a concrete, rigorous experimental plan.

You are skeptical and demanding. You will:
- Ruthlessly discard ideas that aren't technically testable
- Demand numerical success criteria for every experiment (not "it should work better" but "accuracy > 0.85 on dataset X")
- Flag any hypothesis that can't be falsified and either sharpen it or drop it
- Identify the 3-5 most promising concrete experiments, ranked by expected insight-to-effort ratio
- Define exactly what data/code/results constitute "done" for each experiment

Output format — strict markdown, no prose preamble:

# Synthesized Research Plan
## Core Hypothesis
[One sentence. Falsifiable. Specific.]

## Background (from conversation)
[2-3 sentences max. What prior work / reasoning motivates this.]

## Experiments
### Experiment 1: [name]
**Hypothesis:** [specific, falsifiable]
**Method:** [concrete steps]
**Success criteria:** [numerical thresholds]
**Expected runtime:** [estimate]
**Priority:** [High/Medium/Low]

[repeat for each experiment]

## What the Conversation Got Wrong / Dead Ends
[Honest list of ideas in the conversation that are too vague, contradictory, or low-value to pursue]

## Open Questions
[Things that couldn't be resolved from the conversation alone]

## Definition of Done
[Specific outputs that must exist before this work is considered complete.]"""


def _slack_post(text, channel=None):
    ch = channel or SLACK_LOG_CHANNEL
    try:
        r = requests.post("https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
            json={"channel": ch, "text": text}, timeout=10)
        return r.json().get("ts", "")
    except Exception as e:
        log.warning("Slack post failed: %s", e)
        return ""


def synthesize(conversation):
    from openai import OpenAI as _OpenAI
    client = _OpenAI(api_key=OPENROUTER_API_KEY, base_url="https://openrouter.ai/api/v1")
    MAX_CONV_CHARS = 60000
    if len(conversation) > MAX_CONV_CHARS:
        half = MAX_CONV_CHARS // 2
        conversation = conversation[:half] + f"\n\n[... trimmed ...]\n\n" + conversation[-half:]
    log.info("Running synthesis on %d chars via OpenRouter (%s)...", len(conversation), SYNTHESIS_MODEL)
    response = client.chat.completions.create(
        model=SYNTHESIS_MODEL,
        max_tokens=8000,
        messages=[
            {"role": "system", "content": SYNTHESIS_SYSTEM},
            {"role": "user",   "content": (
                "Here is the raw research conversation to synthesize into an experimental plan:\n\n"
                "---\n" + conversation + "\n---\n\nProduce the synthesized plan now."
            )},
        ],
    )
    plan = response.choices[0].message.content.strip()
    log.info("Synthesis complete: %d chars", len(plan))
    return plan


def synthesize_batch(conversation):
    """OpenRouter has no batch API — delegates to synthesize() immediately."""
    log.info("--batch flag detected; OpenRouter has no batch API, running immediately")
    return synthesize(conversation)


def _update_vault_index(filename: str, draft_path):
    """Append new draft to vault Index.md so it shows up in Obsidian."""
    from datetime import datetime as _dt
    index = VAULT_ROOT / "Index.md"
    if not index.exists():
        return
    entry = f"- [[Plans/drafts/{filename}|{filename.replace('.md','')}]] ({_dt.now().strftime('%Y-%m-%d')})"
    content = index.read_text(encoding="utf-8")
    if filename in content:
        return  # already listed
    # Insert after the ## Plans header
    if "## Plans" in content:
        content = content.replace("## Plans\n", "## Plans\n" + entry + "\n", 1)
    else:
        content += "\n" + entry + "\n"
    index.write_text(content, encoding="utf-8")
    # Git commit the new draft + index update
    import subprocess as _sp
    _sp.run(["git", "-C", str(VAULT_ROOT), "add", "-A"], capture_output=True)
    _sp.run(["git", "-C", str(VAULT_ROOT), "commit", "-m", f"Add synthesis draft: {filename}"],
            capture_output=True)
    _sp.run(["git", "-C", str(VAULT_ROOT), "push"], capture_output=True)
    log.info("Vault index updated and pushed: %s", filename)




def synthesize_with_claude_code(conversation):
    """
    Run synthesis through Claude Code CLI.
    Claude Code can cross-reference files, reason iteratively, and produce
    a richer experimental plan than a single-shot API call.
    """
    from claude_code_runner import run_claude_code, CLAUDE_CODE_AVAILABLE
    if not CLAUDE_CODE_AVAILABLE:
        log.warning("Claude Code unavailable — falling back to API synthesis")
        return synthesize(conversation)

    MAX_CONV = 60000
    if len(conversation) > MAX_CONV:
        half = MAX_CONV // 2
        conversation = conversation[:half] + "\n\n[... trimmed ...]\n\n" + conversation[-half:]

    prompt = (
        "Here is the raw research conversation to synthesize into an experimental plan:\n\n"
        "---\n" + conversation + "\n---\n\n"
        "Produce a rigorous synthesized research plan following the format in CLAUDE.md."
    )
    system = SYNTHESIS_SYSTEM  # reuse the same strict system prompt

    output, _ = run_claude_code(prompt, system=system, timeout=900)
    log.info("Claude Code synthesis complete: %d chars", len(output))
    return output



def save_draft(plan):
    drafts_dir = VAULT_ROOT / "Plans" / "drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"draft_{timestamp}.md"
    path = drafts_dir / filename
    path.write_text(plan, encoding="utf-8")
    log.info("Draft saved: %s", path)
    # Update vault Index.md
    try:
        _update_vault_index(filename, path)
    except Exception as _ie:
        log.debug("Index update skipped: %s", _ie)
    # Index draft into KB if available
    try:
        sys.path.insert(0, str(Path(__file__).parent))
        from knowledge_base import get_kb
        get_kb().store_stage(
            f"synth_{filename[:20]}", f"Synthesis: {filename}",
            "synthesize", plan, score=9, model="claude-sonnet-4-6",
        )
        log.info("Draft indexed into ChromaDB KB")
    except Exception as e:
        log.debug("KB index skipped (non-fatal): %s", e)
    return path


def post_to_slack(plan, draft_path):
    title_match = re.search(r"^# (.+)$", plan, re.MULTILINE)
    title = title_match.group(1) if title_match else "Synthesized Research Plan"
    hyp_match = re.search(r"## Core Hypothesis\s*\n(.+?)(?=\n##|\Z)", plan, re.DOTALL)
    hypothesis = hyp_match.group(1).strip() if hyp_match else ""
    exp_count = len(re.findall(r"^### Experiment \d+", plan, re.MULTILINE))
    _slack_post(
        f":microscope: *Synthesis complete* — {exp_count} experiments identified\n"
        f"_Hypothesis: {hypothesis[:200]}_\n"
        f"Full plan in thread ↓",
        channel=SLACK_CHANNEL,
    )
    ts = _slack_post(
        f":scroll: *{title}*\n_Draft saved: `{draft_path.name}`_\n\n"
        f"React with ✅ to run with `/pipeline --with-file` or ✏️ to edit first.\n\n"
        f"```\n{plan[:2800]}\n```",
        channel=SLACK_LOG_CHANNEL,
    )
    if len(plan) > 2800:
        remainder = plan[2800:]
        for i in range(0, len(remainder), 3000):
            chunk = remainder[i:i+3000]
            requests.post("https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
                json={"channel": SLACK_LOG_CHANNEL, "text": f"```\n{chunk}\n```", "thread_ts": ts},
                timeout=10)


def main():
    if not CONVERSATION:
        log.error("No OPENCLAW_TASK set")
        sys.exit(1)
    if not OPENROUTER_API_KEY:
        log.error("No OPENROUTER_API_KEY set")
        sys.exit(1)
    log.info("Synthesize agent starting")
    if USE_CLAUDE_CODE:
        _slack_post(":zap: *Synthesis starting via Claude Code* — agentic mode, may take a few minutes.",
                    channel=SLACK_CHANNEL)
    elif USE_BATCH:
        _slack_post(
            ":brain: *Synthesis submitted to Batch API* — will post plan when ready (~5–15 min). 50% cheaper!",
            channel=SLACK_CHANNEL,
        )
    else:
        _slack_post(":brain: *Synthesis starting...* reading conversation and extracting experiments",
                    channel=SLACK_CHANNEL)
    try:
        if USE_CLAUDE_CODE:
            plan = synthesize_with_claude_code(CONVERSATION)
        elif USE_BATCH:
            plan = synthesize_batch(CONVERSATION)
        else:
            plan = synthesize(CONVERSATION)
    except Exception as e:
        log.error("Synthesis failed: %s", e)
        _slack_post(f":x: Synthesis failed: {e}", channel=SLACK_CHANNEL)
        sys.exit(1)
    draft_path = save_draft(plan)
    post_to_slack(plan, draft_path)
    log.info("Synthesize agent done")


if __name__ == "__main__":
    main()
