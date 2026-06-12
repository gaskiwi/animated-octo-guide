"""
verification.py — independent verifier gate (doer ≠ checker).

Every deliverable passes through gate() before being marked done. The
verifier runs in a FRESH model context (stateless llm_client call) so it
shares none of the doer's blind spots, per the capability checklist: swarm
claims are verified, not trusted.

If the claim ships a verify command (ground truth), it is re-run and its
exit code outranks the LLM verdict.
"""
import logging
import re
import subprocess

from llm_client import complete

log = logging.getLogger("verification")

VERIFIER_SYSTEM = """You are the independent verifier for an agent swarm. \
You did NOT produce the work you are reviewing. Be skeptical; your job is to \
catch what the doer missed or invented.

Assess the DELIVERABLE against the TASK:
1. UNSUPPORTED CLAIMS — numbers, benchmarks, prices, or factual assertions \
stated confidently without a source or attached evidence. Flag each one.
2. COMPLETION — was the task actually done, fully, as asked?
3. CONSISTENCY — internal contradictions, broken logic, fabricated-looking \
citations (e.g. links that don't plausibly exist).
4. EVIDENCE — if a VERIFY COMMAND result is attached, did it pass?

Reply in exactly this format:
VERDICT: PASS or FAIL
ISSUES:
- <each concrete issue, or '- none'>
SUMMARY: <one sentence>"""


def run_verify_command(cmd: str, timeout: int = 180):
    """Re-run a ground-truth check. Exit 0 = pass."""
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True,
                       timeout=timeout)
    tail = (r.stdout + r.stderr)[-2000:]
    log.info("verify command %r exit=%d", cmd[:80], r.returncode)
    return r.returncode, tail


def gate(task: str, deliverable: str, verify_command: str | None = None,
         tier: str = "smart"):
    """Returns (passed: bool, verdict: str). Never raises — a broken
    verifier must not silently bless work, so errors fail closed."""
    evidence, cmd_code = "", None
    if verify_command:
        try:
            cmd_code, out = run_verify_command(verify_command)
            evidence = (f"\n\nVERIFY COMMAND: {verify_command}"
                        f"\nEXIT CODE: {cmd_code}\nOUTPUT (tail):\n{out}")
        except Exception as e:
            cmd_code, evidence = 1, f"\n\nVERIFY COMMAND ERROR: {e}"
    user = (f"TASK:\n{task[:4000]}\n\nDELIVERABLE:\n{deliverable[:12000]}"
            f"{evidence}")
    try:
        verdict = complete(VERIFIER_SYSTEM, user, tier=tier, max_tokens=800)
    except Exception as e:
        return False, f"VERDICT: FAIL\nISSUES:\n- verifier error: {e}\nSUMMARY: could not verify."
    passed = bool(re.search(r"VERDICT:\s*PASS", verdict, re.I))
    if cmd_code is not None and cmd_code != 0:
        passed = False  # ground truth outranks the LLM
    return passed, verdict.strip()


def format_verdict(passed: bool, verdict: str) -> str:
    tag = "✅ *Verified (independent checker)*" if passed \
        else "⚠️ *VERIFICATION FAILED — do not treat as done*"
    return f"\n\n---\n{tag}\n```{verdict[:1500]}```"
