"""
guardrails.py — deny-by-default policy gate + spend ledger helper.

Hard gate, not a suggestion: any code path that performs an external-facing
action (spends money, contacts a vendor, sends email, commits externally)
MUST call check_action() before executing. Anything not explicitly allowed
is denied.

Per the capability checklist: agents never pay, never create accounts,
never contact vendors autonomously, never send email/social posts, never
sign firmware. Uncertain → stop and escalate to Yoo via Slack. Silence is
never approval.
"""
import datetime
import logging
import os

log = logging.getLogger("guardrails")

# Actions agents may perform without escalation.
ALLOWED_ACTIONS = {
    "llm_call",            # model inference within budget
    "code_exec_local",     # sandboxed local execution
    "web_fetch_readonly",  # search/fetch, no writes
    "slack_post",          # notification channel
    "git_commit_local",    # local commits; push is reviewed
    "file_write_local",    # workspace files
}

# Explicitly denied (listed for clarity; everything unknown is denied too).
DENIED_ACTIONS = {
    "payment", "vendor_contact", "email_send", "social_post",
    "account_create", "ota_sign", "cloud_spend",
}

LEDGER_PATH = os.environ.get("SPEND_LEDGER", "/workspace/spend_ledger.md")


class GuardrailViolation(Exception):
    """Raised when a denied external action is attempted."""


def check_action(kind: str, detail: str = "", actor: str = "unknown") -> bool:
    """Pre-action hard gate. Returns True if allowed, raises otherwise."""
    if kind in ALLOWED_ACTIONS:
        return True
    # Operator-sanctioned exception for the (non-swarm) school email flow:
    # requires BOTH the env override and deliberate invocation with .env.school.
    if kind == "email_send" and \
            os.environ.get("GUARDRAILS_ALLOW_EMAIL", "").lower() == "true":
        log.warning("email_send allowed via GUARDRAILS_ALLOW_EMAIL override (%s)", detail)
        return True
    log.warning("GUARDRAIL DENY: action=%s detail=%s actor=%s", kind, detail, actor)
    raise GuardrailViolation(
        f"Action '{kind}' is denied by default ({detail}). "
        f"Stop and escalate to Yoo via Slack — do not retry.")


def ledger_append(amount_usd: float, category: str, description: str,
                  actor: str = "agent") -> str:
    """Write the spend entry BEFORE the spend happens. Returns the line written."""
    ts = datetime.datetime.now().isoformat(timespec="seconds")
    line = f"| {ts} | {actor} | {category} | ${amount_usd:.2f} | {description} |\n"
    with open(LEDGER_PATH, "a", encoding="utf-8") as f:
        f.write(line)
    log.info("ledger: %s", line.strip())
    return line
