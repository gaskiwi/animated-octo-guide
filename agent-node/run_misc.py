from slack_logger import SlackLogger as _SL, init_logger as _init_logger
from knowledge_base import get_kb
"""
run_misc.py — General automation runner (local qwen only, no Claude credits)
Flow:
  1. qwen generates a complete Python automation script for the task
  2. Script is written to a temp file and executed on kamrui
  3. stdout/stderr is captured and posted back to Slack
Handles: Google Workspace, file manipulation, web tasks, data processing, etc.
Credentials expected at:
  Google: /home/pacers4ever/credentials/google_service_account.json
         or /home/pacers4ever/credentials/google_oauth_token.json
"""
import sys, os, re, logging, subprocess, tempfile, textwrap
from pathlib import Path
from datetime import datetime
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
SLACK_CHANNEL   = os.environ.get("SLACK_CHANNEL", "")
OLLAMA_URL      = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
CREDS_DIR       = Path("/home/pacers4ever/credentials")

TASK = " ".join(sys.argv[1:]).strip() if len(sys.argv) > 1 else ""

SCRIPT_TIMEOUT = 120  # seconds max for generated script to run

# ── Slack ─────────────────────────────────────────────────────────────────────
# ── SlackLogger setup ─────────────────────────────────────────────────────
_slog = _init_logger(token=SLACK_BOT_TOKEN, channel=SLACK_CHANNEL)

def post(text):
    _slog.step(text)


# ── qwen ──────────────────────────────────────────────────────────────────────
def ask_qwen(prompt, num_predict=2000):
    resp = requests.post(f"{OLLAMA_URL}/api/generate",
        json={"model": "qwen2.5-coder:7b", "prompt": prompt,
              "stream": False, "options": {"num_predict": num_predict}},
        timeout=300)
    resp.raise_for_status()
    return resp.json()["response"]

# ── credential context ────────────────────────────────────────────────────────
def creds_context():
    """Tell qwen what credentials are available so it can use them."""
    lines = []
    sa = CREDS_DIR / "google_service_account.json"
    tok = CREDS_DIR / "google_oauth_token.json"
    if sa.exists():
        lines.append(f"  - Google Service Account JSON: {sa}")
    if tok.exists():
        lines.append(f"  - Google OAuth token: {tok}")
    if not lines:
        lines.append("  - No Google credentials found at /home/pacers4ever/credentials/")
        lines.append("    (Google API tasks will fail unless credentials are added)")
    return "\n".join(lines)

# ── extract code block ────────────────────────────────────────────────────────
def extract_script(text):
    """Pull the first python code block out of qwen's response."""
    m = re.search(r"```(?:python|py)?\s*\n(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # Fallback: if no fences, treat whole response as code if it looks like it
    if text.strip().startswith(("import ", "from ", "#!")):
        return text.strip()
    return None

# ── generate script ───────────────────────────────────────────────────────────
def generate_script(task):
    creds = creds_context()
    prompt = textwrap.dedent(f"""
        You are an expert Python automation engineer.
        Write a complete, self-contained Python script that accomplishes this task:

        TASK: {task}

        Available credentials on this machine:
        {creds}

        Rules:
        - Output the script in a single ```python ... ``` code block
        - The script must run without user interaction (no input() calls)
        - Print a clear summary of what was done to stdout at the end
        - If creating a Google Slides/Docs file, print the shareable URL
        - If the task produces a file, save it to /tmp/ and print the path
        - Handle errors gracefully with try/except and print useful messages
        - Keep the script concise — avoid unnecessary boilerplate
        - Use only standard library + these installed packages:
          google-api-python-client, google-auth, google-auth-oauthlib,
          google-auth-httplib2, requests, beautifulsoup4, lxml,
          python-docx, openpyxl, pandas, pillow, markdown

        Write only the script. No explanation outside the code block.
    """).strip()

    import anthropic as _ant, os as _os
    client = _ant.Anthropic(api_key=_os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2500,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text

# ── execute script ────────────────────────────────────────────────────────────
def execute_script(code):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py",
                                     prefix="misc_task_", delete=False) as f:
        f.write(code)
        script_path = f.name

    try:
        result = subprocess.run(
            ["python3", script_path],
            capture_output=True, text=True,
            timeout=SCRIPT_TIMEOUT
        )
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        rc     = result.returncode
        return stdout, stderr, rc
    except subprocess.TimeoutExpired:
        return "", f"Script timed out after {SCRIPT_TIMEOUT}s", 1
    finally:
        os.unlink(script_path)

# ── format result for Slack ───────────────────────────────────────────────────
def format_output(stdout, stderr, rc):
    lines = []
    if stdout:
        # Truncate very long output
        out = stdout if len(stdout) < 1500 else stdout[:1500] + "\n…(truncated)"
        lines.append(f"```\n{out}\n```")
    if rc != 0 and stderr:
        err = stderr if len(stderr) < 600 else stderr[:600] + "…"
        lines.append(f"⚠️ *stderr:*\n```\n{err}\n```")
    if not lines:
        lines.append("_(Script ran but produced no output)_")
    status = "✅" if rc == 0 else "❌"
    return status, "\n".join(lines)

# ── main ──────────────────────────────────────────────────────────────────────
def main():
    _slog.start(title="/misc", task=TASK[:180], model="qwen2.5-coder")
    if not TASK:
        post("⚙️ */misc* — Usage: `/misc <describe what you want to automate>`\n"
             "_Examples:_\n"
             "• `/misc create a Google Slides deck on climate change with 5 slides`\n"
             "• `/misc write a Google Doc report summarising these bullet points: ...`\n"
             "• `/misc scrape the top 10 HN posts and format as a table`\n"
             "• `/misc convert this CSV to a formatted Excel file`")
        return

    logging.info(f"misc task: {TASK[:80]}")
    post(f"⚙️ */misc* — generating automation script…\n`{TASK[:100]}`")

    try:
        # Step 1: generate
        post("🧠 _Asking Claude Haiku to write the script…_")
        raw = generate_script(TASK)
        code = extract_script(raw)

        if not code:
            post(f"⚠️ *Could not extract a runnable script.* qwen responded:\n```\n{raw[:800]}\n```")
            return

        # Post the generated script so user can see it
        script_preview = code if len(code) < 1200 else code[:1200] + "\n# …(truncated for preview)"
        post(f"📝 *Generated script:*\n```python\n{script_preview}\n```")

        # Step 2: execute
        post("▶️ _Running script on kamrui…_")
        stdout, stderr, rc = execute_script(code)

        # Step 3: report
        status, output_text = format_output(stdout, stderr, rc)
        # Store successful scripts so --knowledge_base can find similar ones later
        if rc == 0:
            try:
                get_kb().store_script(TASK, code, stdout[:400], success=True)
            except Exception:
                pass
        post(f"{status} */misc result* — `{TASK[:80]}`\n\n{output_text}\n\n"
             f"_Used Claude Haiku_")

    except Exception as e:
        _slog.error(f"/misc error: {e}")
        post(f"❌ `/misc` error: `{e}`")
        sys.exit(1)

if __name__ == "__main__":
    main()
