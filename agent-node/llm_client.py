"""
llm_client.py — Unified LLM access for all runners.

Providers (auto-detected from env):
  anthropic   ANTHROPIC_API_KEY            (preferred for Claude models)
  openrouter  OPENROUTER_API_KEY           (fallback / non-Claude models)
  ollama      OLLAMA_BASE_URL              (free local)
  cc-proxy    Claude Code proxy :18790     (agentic, writes files)

Model tiers (override via env):
  smart  — planning / orchestration / synthesis   LLM_MODEL_SMART
  fast   — subagent grunt work / evaluation       LLM_MODEL_FAST
  local  — free local model                       (qwen2.5-coder:7b)

Usage:
    from llm_client import complete
    text = complete("system prompt", "user msg", tier="fast", max_tokens=2000)
"""

import json
import logging
import os
import threading

import requests

log = logging.getLogger(__name__)

ANTHROPIC_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
OPENROUTER_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OLLAMA_URL     = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

# Anthropic-native model ids
_ANTHROPIC_OPUS  = os.environ.get("LLM_MODEL_OPUS",  "claude-opus-4-8")
_ANTHROPIC_SMART = os.environ.get("LLM_MODEL_SMART", "claude-sonnet-4-6")
_ANTHROPIC_FAST  = os.environ.get("LLM_MODEL_FAST",  "claude-haiku-4-5-20251001")

# OpenRouter model ids (used when no Anthropic key)
_OPENROUTER_OPUS  = os.environ.get("OPENROUTER_MODEL_OPUS", "anthropic/claude-opus-4.8")
_OPENROUTER_SMART = os.environ.get("OPENROUTER_MODEL",      "anthropic/claude-sonnet-4.6")
_OPENROUTER_FAST  = os.environ.get("OPENROUTER_MODEL_FAST", "anthropic/claude-haiku-4.5")

# Guardrails doc — injected as cached system context into every Anthropic call.
_GUARDRAILS_DOC = ""
try:
    _gp = os.environ.get(
        "GUARDRAILS_DOC",
        os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "docs", "guardrails.md"))
    with open(_gp, encoding="utf-8") as _gf:
        _GUARDRAILS_DOC = _gf.read().strip()
except OSError:
    pass

_LOCAL_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5-coder:7b")

_anthropic_client = None
_anthropic_lock = threading.Lock()


def provider() -> str:
    if ANTHROPIC_KEY:
        return "anthropic"
    if OPENROUTER_KEY:
        return "openrouter"
    return "ollama"


def _get_anthropic():
    global _anthropic_client
    with _anthropic_lock:
        if _anthropic_client is None:
            import anthropic
            _anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_KEY)
    return _anthropic_client


def _complete_anthropic(system: str, user: str, tier: str, max_tokens: int) -> str:
    model = {"opus": _ANTHROPIC_OPUS,
             "smart": _ANTHROPIC_SMART}.get(tier, _ANTHROPIC_FAST)
    if _GUARDRAILS_DOC:
        system = _GUARDRAILS_DOC + "\n\n---\n\n" + system
    resp = _get_anthropic().messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": system,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user}],
    )
    log.info("anthropic[%s] in=%d out=%d", model,
             resp.usage.input_tokens, resp.usage.output_tokens)
    return resp.content[0].text


def _complete_openrouter(system: str, user: str, tier: str, max_tokens: int) -> str:
    model = {"opus": _OPENROUTER_OPUS,
             "smart": _OPENROUTER_SMART}.get(tier, _OPENROUTER_FAST)
    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENROUTER_KEY}",
                 "Content-Type": "application/json"},
        json={"model": model, "max_tokens": max_tokens,
              "messages": [{"role": "system", "content": system},
                           {"role": "user",   "content": user}]},
        timeout=600,
    )
    resp.raise_for_status()
    data = resp.json()
    log.info("openrouter[%s] usage=%s", model, data.get("usage"))
    return data["choices"][0]["message"]["content"]


def _complete_ollama(system: str, user: str, tier: str, max_tokens: int) -> str:
    resp = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={"model": _LOCAL_MODEL, "prompt": f"{system}\n\n{user}",
              "stream": False, "options": {"num_predict": max_tokens}},
        timeout=600,
    )
    resp.raise_for_status()
    return resp.json()["response"].strip()


def complete(system: str, user: str, tier: str = "fast",
             max_tokens: int = 3000) -> str:
    """Single completion routed to the best available provider.

    tier: "opus" | "smart" | "fast" | "local"
    ("opus" is the escalation tier — architecture changes, stuck debugging,
     review of high-stakes output. Invoke sparingly; default to "smart".)
    """
    if tier == "local":
        return _complete_ollama(system, user, tier, max_tokens)
    p = provider()
    if p == "anthropic":
        try:
            return _complete_anthropic(system, user, tier, max_tokens)
        except Exception as e:
            log.warning("anthropic failed (%s) — falling back to openrouter", e)
            if OPENROUTER_KEY:
                return _complete_openrouter(system, user, tier, max_tokens)
            raise
    if p == "openrouter":
        return _complete_openrouter(system, user, tier, max_tokens)
    return _complete_ollama(system, user, tier, max_tokens)


def complete_json(system: str, user: str, tier: str = "smart",
                  max_tokens: int = 4000, retries: int = 2):
    """Completion that must return parseable JSON. Extracts the first JSON
    object/array from the response; retries with an explicit correction."""
    msg = user
    for attempt in range(retries + 1):
        raw = complete(system, msg, tier=tier, max_tokens=max_tokens)
        try:
            return _extract_json(raw)
        except ValueError as e:
            log.warning("JSON parse failed (attempt %d): %s", attempt + 1, e)
            msg = (user + "\n\nYour previous reply was not valid JSON "
                   f"({e}). Reply with ONLY the JSON, no prose, no fences.")
    raise ValueError("LLM did not return valid JSON after retries")


def _extract_json(text: str):
    text = text.strip()
    # Strip markdown fences
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0] if "```" in text else text
    # Find first { or [
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        if start == -1:
            continue
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(text)):
            c = text[i]
            if esc:
                esc = False
                continue
            if c == "\\":
                esc = True
            elif c == '"' and not esc:
                in_str = not in_str
            elif not in_str:
                if c == opener:
                    depth += 1
                elif c == closer:
                    depth -= 1
                    if depth == 0:
                        return json.loads(text[start:i + 1])
        break
    raise ValueError("no JSON object found in response")
