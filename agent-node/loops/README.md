# Loops

Each `*.yaml` file here defines one loop. The daemon (`loop_daemon.py`) reloads
this directory every ~20s — no restart needed to add/edit loops.

```yaml
name: fix-tests              # unique id (used by /loop run fix-tests)
goal: |                      # what the agent should accomplish
  Make the test suite in /workspace/myproj pass without deleting tests.
verify:                      # GROUND TRUTH — exit 0 means done
  command: "cd /workspace/myproj && pytest -q"
  timeout: 300
runner: claude-code          # claude-code | dynamic | misc | none
runner_flags: ""             # e.g. "--no-replan --max-agents 4" for dynamic
trigger:                     # omit entirely for manual-only (/loop run)
  schedule: "0 6 * * *"      # cron, UTC
  # interval_minutes: 60     # …or a simple interval
budget:
  max_iterations: 5          # acts before escalating to Slack
  max_minutes: 90            # wall clock before escalating
enabled: true
```

How an iteration works: verify → if failing, the agent gets the goal + the
verify command + the failing output → it acts (claude-code keeps a persistent
workdir per loop at `workspace/loop_workdirs/<name>/`, which the verify
command sees as `/workspace/loop_workdirs/<name>/`) → verify again.
Passes = done. Budget exhausted = 🚨 escalation in Slack.

Path tip for claude-code loops: phrase goals as "in the current directory"
(the agent is cd'd into its workdir) and point verify commands at
`/workspace/loop_workdirs/<name>/...`.

`runner: none` makes a watchdog: verify only, no LLM, alerts on pass↔fail
transitions. Control from Slack: `/loop list|run|enable|disable|status|show`.
