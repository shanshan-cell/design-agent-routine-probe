# design-agent-routine-probe

Private test repository for Claude Code cloud routine probes of native Claude Design generation for WeMod. It holds
no product code or data, only the guard that is active from session start (it sits on the default branch).

## Current: Guard v4 (Test C, one real WeMod page)

- `.claude/hooks/design_guard.py`: a PreToolUse hook on every tool (subagents included) plus a PostToolUse hook on
  Artifact. Allows only what `wemod-page-designer`, WeMod Web — Private V0 and one Design canvas need:
  - read-only tools (Read, Glob, Grep, ToolSearch, TodoWrite)
  - the `anthropic-skills:wemod-page-designer` skill, no other
  - subagents (the skill's independent reviewer)
  - Write/Edit inside the session scratchpad
  - Bash/Monitor for local rendering only: blocks git, gh, curl, wget, ssh and other network clients, sudo, package
    managers other than `npm install`, `npx`, `playwright install`, and commands that name Linear, Slack, the hooks
    or the guard state
  - Artifact read/list; ONE create from the Design type; publishes only to that canvas (at most 60), with files and
    asset uploads from the scratchpad and asset or file copies from V0 only; no runtime capabilities, contract,
    force, pin or delete
  - everything else (web, MCP, DesignSync, ArtifactComments, ArtifactData, scheduling) is blocked.
  Marker: `ROUTINE-PROBE-GUARD-v4`. Tests: `python3 -I tests/guard_v4_test.py .claude/hooks/design_guard.py`.
- `.claude/settings.json`: registers both hooks; denies web, notebook, DesignSync, ArtifactComments, ArtifactData and
  MCP tools as a second layer.

## Rollback point: Test B

Tag `test-b-guard-v3` (b1c71e5) is the guard Test B passed with (one placeholder canvas). Its hook,
`.claude/hooks/read_only_guard.py`, is kept unchanged in the tree; `tests/guard_v3_test.py` is its test.
To roll back: check out the tag's `.claude/settings.json`.
