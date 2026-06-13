# Handoff Protocol — Swarm ↔ Yoo

One board, one convention, no ambiguity. The live board is **`workspace/HANDOFFS.md`**
(host path: `~/animated-octo-guide/agent-node/workspace/HANDOFFS.md` on kamrui).
Both sides edit it; every state change is mirrored to Slack.

## Entry format

```
## H-<number> — <short title>            [STATE]
- Direction: SWARM→YOO | YOO→SWARM
- What: one sentence.
- Where: exact file paths / cart links / commands.
- Steps for the receiver: numbered, max 6, no jargon.
- Done when: the single check that closes it.
```

## States

`READY` (receiver can start) → `IN-PROGRESS` (receiver claimed it) →
`RETURNED` (receiver finished; results noted in the entry) → `CLOSED` (originator verified).

## Rules

1. **The swarm never hands Yoo a question — it hands a kit.** Files, carts, print
   STLs, a numbered procedure, and one "done when" check. If Yoo has to figure out
   *how*, the handoff is defective; send it back by setting state `READY` with a note.
2. **Yoo returns results in the entry itself** (numbers, file drops into
   `workspace/returns/H-<n>/`, or just "done"). Slack message "H-3 returned" is enough —
   the PM loop syncs the board.
3. One entry = one sitting. If a kit needs more than ~2 hours of bench time, the
   swarm must split it.
4. Money: any entry involving a purchase carries the draft cart + total; ≥ $250 or
   ambiguous = explicit approval line for Yoo to initial (guardrail §0.0-2).
5. The weekly PM status (`workspace/status/weekly_status.md` + Slack) lists all
   non-CLOSED entries — nothing gets lost.
