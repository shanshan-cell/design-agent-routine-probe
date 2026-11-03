#!/usr/bin/env python3
# Read-only guard for the routine capability probe (PreToolUse, every tool).
# Allows only: Artifact read/list (no out_dir) and ToolSearch (loads tool schemas, no side effects).
# Blocks everything else, including any Artifact publish (an omitted action is a publish), delete, open, pin and
# quickstart. Exit 2 blocks the call; the marker in the message proves this hook, not a permission rule, blocked it.
import json
import sys

MARKER = 'ROUTINE-PROBE-GUARD-v1'

try:
    ev = json.load(sys.stdin)
except Exception:
    print(f'{MARKER}: unreadable hook input, blocked.', file=sys.stderr)
    sys.exit(2)

tool = ev.get('tool_name') or ''
inp = ev.get('tool_input') or {}
action = inp.get('action')

if tool == 'ToolSearch':
    sys.exit(0)
if tool == 'Artifact' and action in ('read', 'list') and 'out_dir' not in inp:
    sys.exit(0)

print(f'{MARKER}: read-only probe, blocked {tool} (action={action!r}).', file=sys.stderr)
sys.exit(2)
