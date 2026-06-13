#!/usr/bin/env python3
"""
Weekly spend-ledger audit — verify command for the ledger-audit loop.

Checks /workspace/spend_ledger.md (live append surface used by
guardrails.ledger_append) against the program budget caps:

  hardware   ≤ $10,000 cumulative
  cloud-gpu  ≤ $400 cumulative, ≤ $50 per entry
  llm-api    ≤ $300 in the current calendar month

Exit 0 = compliant (the loop stays quiet).
Exit 1 = violation or unparseable ledger → loop escalates to Slack.

A missing ledger is bootstrapped with a header and passes (empty = compliant).
"""
import datetime
import os
import re
import sys

LEDGER = sys.argv[1] if len(sys.argv) > 1 else "/workspace/spend_ledger.md"

CUMULATIVE_CAPS = {"hardware": 10_000.00, "cloud-gpu": 400.00}
PER_ENTRY_CAPS  = {"cloud-gpu": 50.00}
MONTHLY_CAPS    = {"llm-api": 300.00}
# Yoo's directive 2026-06: ALL compute (tokens + cloud + other APIs) ≤ $300 total.
TOTAL_COMPUTE_CAP = 300.00
COMPUTE_CATEGORIES = {"llm-api", "cloud-gpu", "api"}

HEADER = ("# Spend Ledger (live)\n\n"
          "| Timestamp | Actor | Category | Amount | Description |\n"
          "|---|---|---|---|---|\n")

ROW = re.compile(
    r"^\|\s*(?P<ts>[\d:T.\-]+)\s*\|\s*(?P<actor>[^|]+?)\s*\|"
    r"\s*(?P<cat>[^|]+?)\s*\|\s*\$(?P<amt>[\d.]+)\s*\|\s*(?P<desc>[^|]*)\|\s*$")

def main() -> int:
    if not os.path.exists(LEDGER):
        with open(LEDGER, "w", encoding="utf-8") as f:
            f.write(HEADER)
        print(f"ledger missing — bootstrapped empty at {LEDGER}: PASS")
        return 0

    totals, monthly, violations = {}, {}, []
    this_month = datetime.date.today().strftime("%Y-%m")
    n_rows = 0

    for i, line in enumerate(open(LEDGER, encoding="utf-8"), 1):
        line = line.strip()
        if not line.startswith("|") or set(line) <= {"|", "-", " "}:
            continue
        if re.match(r"^\|\s*Timestamp", line):
            continue
        m = ROW.match(line)
        if not m:
            violations.append(f"line {i}: unparseable ledger row: {line[:80]}")
            continue
        n_rows += 1
        cat = m["cat"].strip().lower()
        amt = float(m["amt"])
        totals[cat] = totals.get(cat, 0.0) + amt
        if m["ts"][:7] == this_month:
            monthly[cat] = monthly.get(cat, 0.0) + amt
        if cat in PER_ENTRY_CAPS and amt > PER_ENTRY_CAPS[cat]:
            violations.append(
                f"line {i}: {cat} entry ${amt:.2f} exceeds per-entry cap "
                f"${PER_ENTRY_CAPS[cat]:.2f}")

    for cat, cap in CUMULATIVE_CAPS.items():
        if totals.get(cat, 0.0) > cap:
            violations.append(
                f"{cat} cumulative ${totals[cat]:.2f} exceeds cap ${cap:.2f}")

    compute = sum(totals.get(c, 0.0) for c in COMPUTE_CATEGORIES)
    if compute > TOTAL_COMPUTE_CAP:
        violations.append(
            f"total compute ${compute:.2f} exceeds Yoo's $"
            f"{TOTAL_COMPUTE_CAP:.0f} all-in compute cap — halt API-heavy work")
    elif compute > TOTAL_COMPUTE_CAP * 0.8:
        print(f"WARNING: compute spend ${compute:.2f} is past 80% of the "
              f"${TOTAL_COMPUTE_CAP:.0f} cap")

    # Guardrail §0.0-1: program spend (hardware + cloud) crossing $9,000
    # triggers escalation before the $10k hard cap is reached.
    program = totals.get("hardware", 0.0) + totals.get("cloud-gpu", 0.0)
    if program > 9_000.0:
        violations.append(
            f"ESCALATE (guardrail §0.0-1): program spend ${program:.2f} "
            f"crossed the $9,000 escalation threshold")
    for cat, cap in MONTHLY_CAPS.items():
        if monthly.get(cat, 0.0) > cap:
            violations.append(
                f"{cat} this month ${monthly[cat]:.2f} exceeds monthly cap "
                f"${cap:.2f}")

    print(f"ledger: {n_rows} entries; totals: "
          f"{ {k: round(v, 2) for k, v in totals.items()} or 'none'}")
    if violations:
        print("AUDIT FAIL:")
        for v in violations:
            print(f"  - {v}")
        return 1
    print("AUDIT PASS")
    return 0

if __name__ == "__main__":
    sys.exit(main())
