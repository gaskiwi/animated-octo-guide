"""
claude_code_runner.py — Client for the Claude Code proxy service.

The proxy (claude_code_proxy.py) runs as pacers4ever on the HOST and handles
--dangerously-skip-permissions. This module is imported inside the container
and calls the proxy over localhost (network_mode: host).

Usage:
    from claude_code_runner import run_claude_code, CLAUDE_CODE_AVAILABLE
    output, workdir = run_claude_code(prompt, system="...")
"""

import logging
import os
import shutil
from pathlib import Path

log = logging.getLogger(__name__)

PROXY_URL = "http://127.0.0.1:18790"


def _probe_proxy() -> bool:
    try:
        import urllib.request
        with urllib.request.urlopen(f"{PROXY_URL}/health", timeout=2) as r:
            import json
            data = json.loads(r.read())
            return data.get("status") == "ok"
    except Exception:
        return False


CLAUDE_CODE_AVAILABLE = _probe_proxy()

if CLAUDE_CODE_AVAILABLE:
    log.info("Claude Code proxy reachable at %s", PROXY_URL)
else:
    log.warning("Claude Code proxy not reachable at %s — --claude-code will fall back to API", PROXY_URL)


def run_claude_code(
    prompt: str,
    workdir: str = None,
    timeout: int = 600,
    system: str = None,
) -> tuple[str, str]:
    """
    Send a task to the Claude Code proxy and return (output, workdir).

    workdir should be a container-relative path (e.g. /workspace/cc_runs/xyz)
    so files are accessible from both the proxy and the container.
    """
    import json
    import urllib.request
    import urllib.error

    if not CLAUDE_CODE_AVAILABLE:
        raise RuntimeError(
            "Claude Code proxy is not running. "
            "Start it on the host: nohup python3 claude_code_proxy.py &"
        )

    payload = json.dumps({
        "prompt":  prompt,
        "system":  system or "",
        "workdir": workdir,
        "timeout": timeout,
    }).encode()

    req = urllib.request.Request(
        PROXY_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout + 30) as resp:
            data = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        raise RuntimeError(f"Proxy error {e.code}: {body}")
    except Exception as e:
        raise RuntimeError(f"Proxy connection failed: {e}")

    output   = data.get("output", "")
    out_dir = data.get('workdir') or data.get('host_workdir') or workdir or ''
    files    = data.get("files", [])

    log.info("Claude Code complete: %d chars, %d files in %s", len(output), len(files), out_dir)
    return output, out_dir


def archive_workdir(workdir: str, run_id: str, vault_root: str = "/app/vault") -> str:
    """Zip workdir into the vault Runs folder."""
    from datetime import datetime
    date_str = datetime.now().strftime("%Y-%m-%d")
    runs_dir = Path(vault_root) / "Runs" / date_str / run_id
    runs_dir.mkdir(parents=True, exist_ok=True)

    zip_path = str(runs_dir / "workdir")
    if Path(workdir).exists():
        shutil.make_archive(zip_path, "zip", workdir)
        for md in Path(workdir).rglob("*.md"):
            shutil.copy2(md, runs_dir / md.name)
    return zip_path + ".zip"


def list_created_files(workdir: str) -> list[str]:
    if not Path(workdir).exists():
        return []
    return [
        str(p.relative_to(workdir))
        for p in Path(workdir).rglob("*")
        if p.is_file() and p.name != "CLAUDE.md"
    ]
