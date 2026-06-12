# Agent Swarm Capability Checklist — Companion to Master Plan v2.0

This document defines what the agent swarm must be able to do, which models run it, what accounts and tools it touches, and what money it is given. It is subordinate to the master plan's §0.0 guardrails. Anything not granted here is denied by default.

---

## 1. Agent Roles (logical capabilities)

The swarm needs these functions. Whether they map to separate agents or modes of one orchestrator is an implementation choice; the *separation between doer and checker* is not optional.

- [ ] **Orchestrator** — decomposes master-plan tasks into work items, tracks phase exit criteria, routes work to the right agent/model, owns the escalation protocol (knows when to stop and ping Yoo). Must hold the master plan + this doc in context (or retrieval) at all times.
- [ ] **Simulation engineer** — Isaac Lab/MJX task implementation, surrogate model coding, USD/asset pipeline, scenario suite + success predicates, CI smoke tests.
- [ ] **RL training engineer** — MAPPO implementation, curriculum management, reward YAML tuning, run launching (local first), experiment tracking hygiene, distillation/quantization pipeline.
- [ ] **Firmware engineer** — ESP-IDF/FreeRTOS code, message codecs, safety task, TFLite Micro integration, HIL test scripts. Output is code + flash instructions; flashing hardware is human.
- [ ] **Mechanical/CAD assistant** — parametric CAD as *code* (CadQuery/OpenSCAD/build123d, so agents can author and revise it), BOM maintenance with live pricing, tolerance/mass spreadsheets, drawings for the human to print/order from.
- [ ] **Procurement drafter** — builds carts/quotes/order drafts with part numbers and prices, writes the spend-ledger entry, then STOPS. Never pays. Every order ≥ $250 (or whenever ambiguous) is executed by Yoo.
- [ ] **Verifier/auditor** (separate from all doers) — checks every external-facing action against §0.0 before it executes, reconciles the spend ledger weekly, re-runs claimed results (training metrics, test passes) before they're marked done. This role exists because of the lesson from the quantum-MoE project: swarm claims must be verified against raw data, not trusted.
- [ ] **Docs/PM** — change-note drafting, weekly status to Yoo, pitch-material assembly in Phase 6P.

Cross-cutting logical requirements:
- [ ] Guardrail pre-check: a hard gate (not a suggestion) that runs before any tool call that spends money, contacts a vendor, or commits externally.
- [ ] Spend ledger writes happen *before* the spend, atomically, in git.
- [ ] Test-gated workflow: no task marked complete without its check (CI run, sim eval, measured number) attached.
- [ ] Checkpoint/resume: all long jobs (training especially) resumable; state in git + experiment tracker, never only in an agent's context.
- [ ] Escalation: uncertain → stop and ask. Silence is never approval.

## 2. Model Assignments (what runs the swarm)

Honest assessment first: **your local qwen2.5-coder:7b is not sufficient for the hard work here.** Isaac Lab integration, MAPPO debugging, and ESP-IDF firmware are exactly the tasks where small local models produce confident, subtly broken code that costs you weeks. Use it where it's good; don't put it on the critical path.

| Workload | Model | Why |
|---|---|---|
| Orchestrator | Claude Sonnet (claude-sonnet-4-6) | Best cost/capability for routing + planning; long-context plan adherence |
| Hard design moments (architecture changes, stuck debugging, change-note review) | Claude Opus-class, invoked sparingly | Escalation tier, not default |
| Sim / RL / firmware coding | Claude Sonnet via Claude Code | Agentic coding with test loops is the whole job |
| Bulk cheap tasks (log summarization, doc formatting, BOM checks, lint) | Claude Haiku 4.5 or local qwen2.5-coder:7b | Free/cheap; failures are low-cost |
| Verifier/auditor | Claude Sonnet (different conversation/agent than the doer) | Checker must not share the doer's blind spots; don't use a weaker model to audit a stronger one |
| NLP front end (the product's encoder, not the swarm) | Open-weights E5/BGE-large class, local | Free, offline, fine-tunable; per master plan §2.8 |
| Instruction-dataset paraphrase generation (offline, once) | Claude API batch | One-time job; use Batch API at 50% discount |

Cost controls you already know from your API optimization work — apply all three: **prompt caching** (the master plan + this doc as cached system context), **Batch API** for anything non-interactive (dataset generation, bulk verification passes), **model routing** (Haiku/local by default, Sonnet for real work, Opus by exception).

## 3. Tool & API Access Matrix

| Tool | Access | Credential holder |
|---|---|---|
| Git repo (GitHub, free private) | Read/write for all agents | Yoo owns org; agents get repo-scoped token |
| Code execution / sandboxes | Full, local | — |
| Local K3s cluster + 4060 (training jobs) | Submit/monitor jobs | Yoo's cluster; agent gets namespace-scoped kubeconfig, no cluster-admin |
| Web search + fetch | Read-only | — |
| Experiment tracking (W&B free tier or self-hosted MLflow on K3s) | Read/write | Yoo account; agent API key |
| Vast.ai / Lambda (cloud GPU) | Agents prepare job specs only | **Yoo only.** Prepaid credit ≤ $100 at a time, card removed after top-up |
| JLCPCB / PCBWay, Digi-Key/Mouser, Amazon, McMaster | Agents draft carts/quotes | **Yoo only. No agent ever has a logged-in session** |
| Slack/Discord notification channel | Post-only webhook | Yoo |
| KiCad / CadQuery files | Read/write (they're just files in git) | — |
| OTA firmware signing key | None | **Yoo only, offline.** Agents produce unsigned builds |
| Anthropic API | Per-agent keys with workspace spend limits | Yoo console |

Deny-by-default list (worth stating because agents will eventually propose them): no email sending, no social media, no contacting the FreeSN authors or any vendor rep autonomously, no creating new accounts anywhere, no payment instruments of any kind.

## 4. Budgets & Balances

| Budget | Amount | Mechanism |
|---|---|---|
| Hardware program (master plan §12) | $10,000 hard cap | Spend ledger; all payments human-executed |
| Cloud GPU | $400 cumulative, ≤ $50/run | Inside the $10k; prepaid credit in $100 increments |
| **Swarm operating cost (LLM API)** — this is the number you asked about | **$150–250/month soft cap; ~$2,000–3,500 expected over the 15-month program** | Anthropic console workspace limits per key; hard monthly cutoff at $300 |
| Free-tier services (GitHub, W&B, tracking) | $0 | Stay on free tiers; any paid upgrade is a §0.0-2 approval |

Two things to internalize about the operating cost line. First, it is real money relative to your program — a multi-agent swarm running daily on Sonnet with sloppy caching can blow past $500/month without producing more, which is why routing and caching are listed as requirements, not tips. Second, keep it **outside** the $10k hardware cap but **inside** the spend ledger — investors reading the ledger should see total program cost honestly, and "built for $10k hardware + $3k inference" is still an excellent story.

Recommended mechanical setup: one Anthropic workspace per role (orchestrator, coders, verifier, bulk) with per-workspace spend limits, so a runaway loop in one role can't drain the whole monthly budget, and so the ledger can attribute cost per function.

## 5. Pre-Launch Checklist (do these before the swarm touches the plan)

- [ ] Repo created; master plan v2.0, this document, and an empty `/docs/spend_ledger.md` committed
- [ ] §0.0 guardrails + this doc injected as cached system context for every agent
- [ ] Per-role API keys created with workspace spend limits set
- [ ] Verifier agent wired to run on a schedule (weekly ledger audit) and as a gate (pre-spend check)
- [ ] Namespace-scoped kubeconfig issued; confirm agents cannot see other cluster workloads
- [ ] Vendor accounts confirmed to have no agent-accessible sessions; cloud GPU account prepaid-only
- [ ] Notification webhook tested (agent → your phone)
- [ ] Dry run: give the swarm one small Phase 2 task (e.g., the simulator spike report) end-to-end and audit the result yourself before opening the rest of the plan
