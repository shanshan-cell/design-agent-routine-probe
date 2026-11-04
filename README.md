# design-agent-routine-probe

Private test repository for Claude Code cloud routine probes of native Claude Design generation for WeMod. It holds
no product code or data, only the guard that is active from session start (it sits on the default branch) and the
inputs a probe run reads.

## Linear design bridge (V1)

Anyone on the Product team labels an open ticket `ai-design` (the design-agent-poc trigger label) → the Cloudflare
relay (`relay/worker.js`) sees the new brief within 2 minutes (it reads Linear with a read-only key) and dispatches one
live tick of `.github/workflows/linear-design-bridge.yml` on `main` → `bridge/bridge.py` claims the brief version,
fires the Linear design routine through its API trigger and posts a **started** comment (GitHub run, Claude session)
→ the routine (prompt `prompts/linear-design.md`, Guard v5 unchanged) designs one canvas and runs
`tools/report_result.py`, which pushes the completion contract (`wemod-design-result/v1`: ticket, run key, status,
canvas URL from the guard's record, summary, limitations) as the only commit on `claude/design-result-<run_key>` →
GitHub's push webhook → relay → one tick validates it and posts ONE result comment, mentioning the ticket's creator.

- Who can trigger: open ticket in the Product team, `ai-design` by label id, a brief of 40+ characters, created by a
  full active workspace member (guests and integrations get one "didn't start" comment). `ignore_tickets` in
  `bridge/config.json` (and `IGNORE_TICKETS` in `relay/wrangler.toml`) are never fired: the earlier test tickets.
- Limits: `max_fires_per_day` (claims in the last 24 h; over it → one "didn't start" comment) and `max_in_flight`
  (the next brief waits). Kill switches: repo variable `DESIGN_BRIDGE_FIRING` must be `on` for the routine to fire;
  Worker variable `RELAY_ENABLED` must be `on` for anything to be dispatched.
- One run per brief version: claim tag `design-claim/<ticket>-<sha256(title+description)[:16]>` created before the
  fire; `design-fired/<run_key>` holds the session. Edit the brief to retry.
- Comments carry the marker `design-run:<run_key> · started|result|timeout|fire-failed|not-started`, which both the
  bridge and the relay read. No result within `result_timeout_minutes` → one "didn't finish" comment.
- Only Linear mutation: `commentCreate`, only on Product tickets. A manual `workflow_dispatch` is a dry run.
- Secrets: GitHub `LINEAR_API_KEY` (posts comments; personal key for now, Linear OAuth app later), `ROUTINE_FIRE_URL`,
  `ROUTINE_FIRE_TOKEN`; Cloudflare `LINEAR_READ_KEY`, `GITHUB_DISPATCH_TOKEN` (Actions read/write on this repo only),
  `GITHUB_WEBHOOK_SECRET`, `LINEAR_WEBHOOK_SECRET` (for a Linear webhook, once an admin creates one).
- Tests: `python3 -I tests/bridge_test.py` and `node tests/relay_test.mjs`

## Current: Guard v5 (Test D, prepared, not run)

- `.claude/hooks/design_guard.py`: a PreToolUse hook on every tool (subagents included) plus a PostToolUse hook on
  Artifact, Agent and Task. On top of v4 (below), v5 adds:
  - **Reviewer messaging.** `SubagentHandback` is allowed, and `SendMessage` only to a subagent this run started
    (ids from the Agent results or the transcript). `PushNotification` and `ListAgents` stay blocked.
  - **Exploration gate.** Until `<scratchpad>/gate/page-narratives.md` holds at least two `## Narrative` sections
    and a `## Section strategy` section, V0 reads are limited to `gate/v0-pre-gate.json` (17 brand, page-model,
    intent and claims files, 11 asset-group READMEs, 156 production media assets) and the canvas can't be filled.
    Files and assets with previous designs, patterns, examples or verdicts (13, 23–26, 29, layout-library,
    components, history asset groups, archived) open after the gate. The narratives file is frozen once the gate
    opens, and the opening (path, sha256, time) goes to `/tmp/routine-probe-guard-log.jsonl` with every block.
  - **Shared WeMod requirements** (`requirements/wemod-page-requirements.md`): R1 "WeMod by Wand" brand line, R2 a
    phone next step without a download, R3 no unverified game, store or mod imagery. The V0 assets in
    `requirements/v0-asset-denylist.json` can't be read, copied or uploaded (by id and sha256), and a publish of
    `project/Page-1440.dc.html` or `project/Page-390.dc.html` must pass `tools/check_requirements.py`.
  - Artifact reads and lists only of V0, the Design type and the created canvas (no account or type listings,
    which would show earlier canvases).
  - Marker: `ROUTINE-PROBE-GUARD-v5`.
- `inputs/learnings-pre-gate.md`: V0 29 §5 (L-01–L-05) without its canvases, scores, quotes and forms. The run reads
  it at the skill's Step 2.5 instead of V0 29 §5.
- `prompts/test-d.md`: the routine prompt for the next run. No routine uses it yet.
- `tools/build_gate_lists.py` rebuilds `gate/v0-pre-gate.json` from V0's `project/design-system.json` when V0 changes.
- Tests:
  - `python3 -I tests/guard_v5_test.py .claude/hooks/design_guard.py`
  - `python3 -I tests/check_requirements_test.py`

## Baselines and rollback

| Tag | Guard | Run |
| --- | --- | --- |
| `test-b-guard-v3` (b1c71e5) | `.claude/hooks/read_only_guard.py`, kept unchanged in the tree; `tests/guard_v3_test.py` | Test B: one placeholder canvas |
| `test-c-guard-v4` (163bff2) | `design_guard.py` v4; `tests/guard_v4_test.py` (run it against `git show test-c-guard-v4:.claude/hooks/design_guard.py`) | Test C: RDR2 Unlimited Health, cse_01BLdKrsnh8yTpTxWaSmSBXK |

The Test B and Test C routines are unchanged and disabled. They clone `main`, so a rerun would now load Guard v5: its
step 0 expects the v4 or v3 marker, sees v5 and stops with "GUARD NOT ACTIVE" before any other call. To rerun a
baseline exactly, restore that tag's `.claude/` on `main` first.

## Guard v4 (Test C)

Allows only what `wemod-page-designer`, WeMod Web — Private V0 and one Design canvas need: read-only tools; the
`anthropic-skills:wemod-page-designer` skill; subagents; Write/Edit inside the scratchpad; Bash/Monitor for local
rendering only (no git, gh, curl, network clients, sudo, other package managers, `npx`, `playwright install`, or
commands naming Linear, Slack, the hooks or the guard state); Artifact read/list; ONE create from the Design type and
publishes only to that canvas (at most 60), with files and uploads from the scratchpad and copies from V0 only.
Everything else (web, MCP, DesignSync, ArtifactComments, ArtifactData, scheduling) is blocked. `.claude/settings.json`
denies web, notebook, DesignSync, ArtifactComments, ArtifactData and MCP tools as a second layer.
