# design-agent-routine-probe

Private test repository for one read-only Claude Code cloud routine run: does a cloud session on a claude.ai Team
login expose the Artifact tool, read WeMod Web — Private V0 through it, and list the synced `wemod-page-designer`
skill?

It holds no product code or data. The only content is the guard on the default branch, so it is active from
session start. Guard v2 (Test B) allows exactly one native Design canvas:

- `.claude/hooks/read_only_guard.py`: a PreToolUse hook on every tool. Allows ToolSearch, Read, Artifact
  `read` / `list`, ONE create from the Design type, publishes (at most 6) only to the canvas that create returned
  with files from the session scratchpad, and Write/Edit inside the scratchpad. Blocks everything else: other
  creates, other artifacts, asset or cross-artifact copies, runtime capabilities, force, delete, open, pin, Bash,
  Skill, subagents, MCP. A PostToolUse hook records the created canvas URL. Marker: `ROUTINE-PROBE-GUARD-v2`.
- `.claude/settings.json`: registers both hooks and denies Bash, web, subagent, Skill and MCP tools as a second
  layer.

Copied from `wemod/design-agent-poc` branch `routine-capability-probe` (commit ef93642).
