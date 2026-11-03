# design-agent-routine-probe

Private test repository for one read-only Claude Code cloud routine run: does a cloud session on a claude.ai Team
login expose the Artifact tool, read WeMod Web — Private V0 through it, and list the synced `wemod-page-designer`
skill?

It holds no product code or data. The only content is the read-only guard on the default branch, so it is active
from session start:

- `.claude/hooks/read_only_guard.py`: a PreToolUse hook on every tool. Allows Artifact `read` / `list` (no
  `out_dir`) and ToolSearch; blocks everything else, including every Artifact publish, delete, open, pin and
  quickstart. Block messages carry the marker `ROUTINE-PROBE-GUARD-v1`.
- `.claude/settings.json`: registers the hook and denies write and outbound tools as a second layer.

Copied from `wemod/design-agent-poc` branch `routine-capability-probe` (commit ef93642).
