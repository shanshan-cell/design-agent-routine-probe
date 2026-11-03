#!/usr/bin/env python3
# Guard v4 for the routine probe (Test C: one real WeMod page on one native Design canvas).
#
# PreToolUse (every tool, main session and subagents) allows only what the wemod-page-designer skill, WeMod Web V0
# and the Design canvas need:
#   - Read, Glob, Grep, ToolSearch, TodoWrite, TaskStop, BashOutput, KillBash (read-only or session bookkeeping).
#     Glob with "HOOK_PROBE" in its pattern is always blocked: the run's first call proves this hook is active.
#   - Skill: only anthropic-skills:wemod-page-designer.
#   - Agent / Task: subagents (the skill's independent reviewer). Their tool calls pass through this same hook.
#   - Write / Edit / MultiEdit: files inside the session scratchpad only.
#   - Bash / Monitor: local rendering and checks only (node, npm install of a package, file utilities). Blocked:
#     git, gh, curl, wget, ssh and other network clients, sudo, package managers other than npm install,
#     `playwright install`, and any command naming Linear, Slack or another outbound service.
#   - Artifact read / list (no out_dir).
#   - ONE Artifact create from the Design type, then publishes only to the canvas it returned (URL from the
#     PostToolUse hook or the session transcript), at most MAX_FILLS: page files from the scratchpad, asset uploads
#     from the scratchpad, asset copies and file copies from WeMod Web V0 only. No runtime capabilities, contract,
#     force or pin; no other artifact is ever written.
# Everything else (WebFetch, WebSearch, MCP, DesignSync, ArtifactComments, ArtifactData, Cron, RemoteTrigger, …) is
# blocked with exit 2 and the marker.
#
# PostToolUse (Artifact only, run with --post) records the created canvas URL.
import json
import os
import re
import sys

MARKER = 'ROUTINE-PROBE-GUARD-v4'
DESIGN_TYPE = 'https://claude.ai/artifact/QKN21svewxgyPb6SYRqWnd'
V0 = 'https://claude.ai/artifact/KE3kJTKgBbXwSgvaaJkrLE'
SKILL = 'anthropic-skills:wemod-page-designer'
STATE = '/tmp/routine-probe-guard-state.json'
MAX_FILLS = 60
CREATE_KEYS = {'action', 'type_url', 'title', 'auto_open', 'description', 'icon'}
FILL_KEYS = {'action', 'url', 'file_path', 'file_paths', 'root', 'files', 'description', 'label', 'asset',
             'from_url', 'asset_ids'}
CREATED = re.compile(r'Created a new Artifact at (https://claude\.ai/artifact/[A-Za-z0-9]+)')
FREE_TOOLS = {'Read', 'Glob', 'Grep', 'ToolSearch', 'TodoWrite', 'TaskStop', 'BashOutput', 'KillBash'}
# Words that may not appear anywhere in a shell command (matched as whole words, case-insensitive).
SHELL_DENY = re.compile(
    r'(?<![\w.-])(git|gh|curl|wget|ssh|scp|sftp|rsync|nc|ncat|netcat|telnet|ftp|sudo|su|apt|apt-get|dpkg|'
    r'pip|pip3|uv|poetry|yarn|pnpm|bun|brew|docker|kubectl|crontab)(?![\w-])', re.I)
SHELL_DENY_TEXT = re.compile(r'playwright\s+install|linear|slack|gmail|notion|hooks/|\.claude/|routine-probe-guard',
                             re.I)


def load():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {'create_attempted': False, 'created_url': None, 'fills': 0}


def save(state):
    with open(STATE, 'w') as f:
        json.dump(state, f)


def block(why):
    print(f'{MARKER}: blocked: {why}', file=sys.stderr)
    sys.exit(2)


def in_scratchpad(path, root=None):
    if not isinstance(path, str) or not path:
        return False
    if root and not os.path.isabs(path):
        path = os.path.join(root, path)
    real = os.path.realpath(path)
    if real.startswith('/private/tmp/'):  # macOS /tmp, so local tests match the Linux VM
        real = real[len('/private'):]
    return real.startswith('/tmp/claude-') and '/scratchpad/' in real + '/'


def created_in_transcript(path):
    """The first artifact URL a 'Created a new Artifact at …' tool result names, other than the type itself."""
    try:
        with open(path, errors='replace') as f:
            for m in CREATED.finditer(f.read()):
                if m.group(1) != DESIGN_TYPE:
                    return m.group(1)
    except Exception:
        pass
    return None


def check_shell(cmd):
    if not isinstance(cmd, str) or not cmd.strip():
        block('empty shell command')
    m = SHELL_DENY.search(cmd)
    if m:
        block(f'shell command uses {m.group(1)!r}')
    m = SHELL_DENY_TEXT.search(cmd)
    if m:
        block(f'shell command mentions {m.group(0)!r}')
    for npm in re.finditer(r'(?<![\w-])npm\s+(\S+)', cmd):
        if npm.group(1) not in ('i', 'install', 'ls', '--version', '-v'):
            block(f'npm {npm.group(1)} (only npm install is allowed)')
    for npx in re.finditer(r'(?<![\w-])npx(?![\w-])', cmd):
        block('npx (run installed scripts with node instead)')


def check_fill(inp, state):
    if not state.get('created_url'):
        block('publish before the Design canvas was created')
    if inp.get('url') != state['created_url']:
        block(f'publish to another artifact ({inp.get("url")!r})')
    extra = set(inp) - FILL_KEYS
    if extra:
        block(f'publish with fields {sorted(extra)}')
    if state.get('fills', 0) >= MAX_FILLS:
        block(f'more than {MAX_FILLS} publishes to the canvas')
    root = inp.get('root')
    if root is not None and not in_scratchpad(root):
        block(f'root outside the session scratchpad ({root!r})')
    if inp.get('asset'):
        if 'from_url' in inp:
            if inp['from_url'] != V0:
                block(f'asset copy from an artifact other than V0 ({inp["from_url"]!r})')
        else:
            paths = inp.get('file_paths') or [inp.get('file_path')]
            for p in paths:
                if not in_scratchpad(p, root):
                    block(f'asset upload from outside the session scratchpad ({p!r})')
    else:
        if 'from_url' in inp or 'asset_ids' in inp or 'file_paths' in inp:
            block('asset fields on a page publish')
        if 'file_path' in inp and not in_scratchpad(inp['file_path'], root):
            block(f'file_path outside the session scratchpad ({inp["file_path"]!r})')
    files = inp.get('files')
    if files is not None:
        items = files.items() if isinstance(files, dict) else [(None, s) for s in files]
        for _, s in items:
            if s is None:
                continue  # removing one of the canvas's own files
            if isinstance(s, str):
                if not in_scratchpad(s, root):
                    block(f'files entry outside the session scratchpad ({s!r})')
            elif isinstance(s, dict) and 'artifact' in s:
                if s.get('artifact', '').split('?')[0].rstrip('/') != V0 or set(s) - {'artifact', 'path', 'ver'}:
                    block('files entry copying from an artifact other than V0')
            elif isinstance(s, dict) and 'from' in s and not set(s) - {'from', 'contentType'}:
                if not in_scratchpad(s['from'], root):
                    block(f'files entry outside the session scratchpad ({s["from"]!r})')
            else:
                block('unrecognised files entry')
    state['fills'] = state.get('fills', 0) + 1
    save(state)
    sys.exit(0)


try:
    ev = json.load(sys.stdin)
except Exception:
    block('unreadable hook input')

tool = ev.get('tool_name') or ''
inp = ev.get('tool_input') or {}

if '--post' in sys.argv:
    # Record the created canvas URL. Never blocks.
    if tool == 'Artifact' and inp.get('type_url') == DESIGN_TYPE:
        m = CREATED.search(json.dumps(ev.get('tool_response')))
        state = load()
        if m and not state.get('created_url'):
            state['created_url'] = m.group(1)
            save(state)
    sys.exit(0)

if tool == 'Glob' and 'HOOK_PROBE' in str(inp.get('pattern', '')):
    block('Glob HOOK_PROBE (guard check)')
if tool in FREE_TOOLS:
    sys.exit(0)
if tool == 'Skill':
    if inp.get('skill') == SKILL:
        sys.exit(0)
    block(f'skill {inp.get("skill")!r} (only {SKILL})')
if tool in ('Agent', 'Task'):
    sys.exit(0)
if tool in ('Write', 'Edit', 'MultiEdit'):
    if in_scratchpad(inp.get('file_path')):
        sys.exit(0)
    block(f'{tool} outside the session scratchpad ({inp.get("file_path")!r})')
if tool in ('Bash', 'Monitor'):
    check_shell(inp.get('command'))
    sys.exit(0)

if tool == 'Artifact':
    action = inp.get('action', 'publish')
    state = load()
    if action in ('read', 'list'):
        if 'out_dir' in inp:
            block('Artifact read with out_dir')
        sys.exit(0)
    if action != 'publish':
        block(f'Artifact action {action!r}')
    if 'type_url' in inp:
        if inp.get('type_url') != DESIGN_TYPE:
            block(f'create from a type other than Design ({inp.get("type_url")!r})')
        if set(inp) - CREATE_KEYS:
            block(f'create with extra fields {sorted(set(inp) - CREATE_KEYS)}')
        if state.get('create_attempted'):
            block('a second Design create (only one is allowed)')
        state['create_attempted'] = True
        save(state)
        sys.exit(0)
    if state.get('create_attempted') and not state.get('created_url'):
        found = created_in_transcript(ev.get('transcript_path'))
        if found:
            state['created_url'] = found
            save(state)
    check_fill(inp, state)

block(f'{tool} is not allowed in this probe')
