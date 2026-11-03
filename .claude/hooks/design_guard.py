#!/usr/bin/env python3
# Guard v5 for the routine probe (Test D: one real WeMod page on one native Design canvas).
#
# PreToolUse (every tool, main session and subagents) allows only what the wemod-page-designer skill, WeMod Web V0
# and the Design canvas need:
#   - Read, Glob, Grep, ToolSearch, TodoWrite, TaskStop, BashOutput, KillBash (read-only or session bookkeeping).
#     Glob with "HOOK_PROBE" in its pattern is always blocked: the run's first call proves this hook is active.
#   - Skill: only anthropic-skills:wemod-page-designer.
#   - Agent / Task: subagents (the skill's independent reviewers). Their tool calls pass through this same hook.
#   - SubagentHandback: a subagent returning its report to the run. SendMessage: only to a subagent this run started
#     (agent ids recorded from the Agent results or the transcript). New in v5.
#   - Write / Edit / MultiEdit: files inside the session scratchpad only. The narratives file is frozen once the
#     exploration gate opens.
#   - Bash / Monitor: local rendering and checks only (node, npm install of a package, python3, file utilities).
#     Blocked: git, gh, curl, wget, ssh and other network clients, sudo, package managers other than npm install,
#     `playwright install`, and any command naming Linear, Slack, another outbound service, the guard's files or
#     the gate's narratives file.
#   - Artifact read / list (no out_dir) of WeMod Web V0, the Design type and the created canvas only. EXPLORATION
#     GATE (new in v5): until <scratchpad>/gate/page-narratives.md holds at least two "## Narrative" sections and a
#     "## Section strategy" section, V0 reads are limited to gate/v0-pre-gate.json (brand foundations, page model,
#     intent, claims and production media) and the canvas cannot be filled. Everything that shows previous designs,
#     patterns, examples or review verdicts (13, 23-26, 29, layout-library, components, history asset groups,
#     archived) opens after the gate.
#   - ONE Artifact create from the Design type, then publishes only to the canvas it returned (URL from the
#     PostToolUse hook or the session transcript), at most MAX_FILLS: page files from the scratchpad, asset uploads
#     from the scratchpad, asset copies and file copies from WeMod Web V0 only. No runtime capabilities, contract,
#     force or pin; no other artifact is ever written.
#   - Shared WeMod requirements (new in v5, requirements/wemod-page-requirements.md): the V0 assets in
#     requirements/v0-asset-denylist.json are never read, copied or uploaded, and a publish of the page boards
#     (project/Page-1440.dc.html, project/Page-390.dc.html) must pass tools/check_requirements.py.
# Everything else (WebFetch, WebSearch, MCP, DesignSync, ArtifactComments, ArtifactData, Cron, RemoteTrigger,
# PushNotification, ListAgents, …) is blocked with exit 2 and the marker.
#
# PostToolUse (Artifact, Agent and Task, run with --post) records the created canvas URL and subagent ids.
# Every gate event and block is appended to LOG.
import glob
import hashlib
import json
import os
import re
import sys
import time

PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(PROJECT, 'tools'))
import check_requirements  # noqa: E402

MARKER = 'ROUTINE-PROBE-GUARD-v5'
DESIGN_TYPE = 'https://claude.ai/artifact/QKN21svewxgyPb6SYRqWnd'
V0 = 'https://claude.ai/artifact/KE3kJTKgBbXwSgvaaJkrLE'
SKILL = 'anthropic-skills:wemod-page-designer'
STATE = '/tmp/routine-probe-guard-state.json'
LOG = '/tmp/routine-probe-guard-log.jsonl'
MAX_FILLS = 60
CREATE_KEYS = {'action', 'type_url', 'title', 'auto_open', 'description', 'icon'}
FILL_KEYS = {'action', 'url', 'file_path', 'file_paths', 'root', 'files', 'description', 'label', 'asset',
             'from_url', 'asset_ids'}
READ_KEYS = {'action', 'url', 'path', 'paths', 'page', 'prompt', 'scope', 'limit', 'after', 'type_query'}
SEND_KEYS = {'to', 'message', 'content', 'summary'}
CREATED = re.compile(r'Created a new Artifact at (https://claude\.ai/artifact/[A-Za-z0-9]+)')
AGENT_ID = re.compile(r'agentId: (a[0-9a-f]{8,40})\b')
FREE_TOOLS = {'Read', 'Glob', 'Grep', 'ToolSearch', 'TodoWrite', 'TaskStop', 'BashOutput', 'KillBash'}
NARRATIVES = 'gate/page-narratives.md'
PAGE_BOARDS = {'project/Page-1440.dc.html': 'desktop', 'project/Page-390.dc.html': 'phone'}
# Words that may not appear anywhere in a shell command (matched as whole words, case-insensitive).
SHELL_DENY = re.compile(
    r'(?<![\w.-])(git|gh|curl|wget|ssh|scp|sftp|rsync|nc|ncat|netcat|telnet|ftp|sudo|su|apt|apt-get|dpkg|'
    r'pip|pip3|uv|poetry|yarn|pnpm|bun|brew|docker|kubectl|crontab)(?![\w-])', re.I)
SHELL_DENY_TEXT = re.compile(r'playwright\s+install|linear|slack|gmail|notion|hooks/|\.claude/|routine-probe-guard|'
                             r'page-narratives|requirements/|gate/v0-', re.I)

with open(os.path.join(PROJECT, 'gate', 'v0-pre-gate.json')) as f:
    PRE_GATE = json.load(f)
DENY = check_requirements.load_denylist()
DENIED_SHA = {v['sha256'] for v in DENY['denied'].values() if v.get('sha256')}


def load():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {'create_attempted': False, 'created_url': None, 'fills': 0, 'agents': [], 'gate': None}


def save(state):
    with open(STATE, 'w') as f:
        json.dump(state, f)


def log(event, **kw):
    try:
        with open(LOG, 'a') as f:
            f.write(json.dumps({'t': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'event': event, **kw}) + '\n')
    except Exception:
        pass


def block(why, tool=None):
    log('block', tool=tool, why=why)
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


def agents_in_transcript(path):
    try:
        with open(path, errors='replace') as f:
            return set(AGENT_ID.findall(f.read()))
    except Exception:
        return set()


def narratives_ready(path):
    """The gate's condition: ≥ 2 '## Narrative' sections and a '## Section strategy' section, ≥ 1500 bytes."""
    try:
        with open(path, errors='replace') as f:
            text = f.read()
    except Exception:
        return False
    return (len(text.encode()) >= 1500 and len(re.findall(r'^##\s+Narrative\b', text, re.M | re.I)) >= 2
            and re.search(r'^##\s+Section strategy\b', text, re.M | re.I) is not None)


def gate_open(state):
    """True once the narratives exist. The first time, records the file and its sha256 and freezes it."""
    if state.get('gate'):
        return True
    # /tmp/claude-<uid>/<project>/<session>/scratchpad/… (the cloud VM's /tmp/claude-0/…, macOS /private/tmp/…)
    for path in glob.glob('/tmp/claude-*/*/*/scratchpad/' + NARRATIVES):
        if narratives_ready(path):
            with open(path, 'rb') as f:
                sha = hashlib.sha256(f.read()).hexdigest()
            state['gate'] = {'path': os.path.realpath(path), 'sha256': sha, 'opened': time.time()}
            save(state)
            log('gate_open', path=path, sha256=sha)
            return True
    return False


def is_narratives(path):
    return isinstance(path, str) and os.path.realpath(path).replace('/private/tmp/', '/tmp/').endswith(
        '/scratchpad/' + NARRATIVES)


def strip_url(u):
    return (u or '').split('?')[0].rstrip('/')


def asset_id(p):
    return p if isinstance(p, str) and re.fullmatch(r'[0-9a-f]{32}', p) else None


def check_v0_path(p, state):
    """Block a V0 file or asset read that the gate or the denylist rules out."""
    aid = asset_id(p)
    if aid and aid in DENY['denied']:
        block(f'V0 asset {DENY["denied"][aid]["name"]} is denied for this page ({DENY["denied"][aid]["reason"]})')
    if gate_open(state):
        return
    if aid:
        if aid not in PRE_GATE['pre_gate_assets']:
            block(f'V0 asset {aid} before the exploration gate (only production media until {NARRATIVES} exists)')
    elif p not in PRE_GATE['pre_gate_files']:
        block(f'V0 file {p!r} before the exploration gate (write {NARRATIVES} first)')


def check_read(inp, state):
    url = strip_url(inp.get('url'))
    if 'out_dir' in inp:
        block('Artifact read with out_dir')
    if set(inp) - READ_KEYS:
        block(f'Artifact read with fields {sorted(set(inp) - READ_KEYS)}')
    action = inp.get('action')
    if action == 'list' and not url:
        # The type catalogue only: the account's lists, and lists by type, would show earlier explorations.
        if inp.get('scope') == 'types' and not inp.get('type') and not inp.get('type_url'):
            sys.exit(0)
        block('Artifact list of the account (earlier canvases); list only V0, the Design type or the canvas')
    if url not in (V0, DESIGN_TYPE, state.get('created_url')):
        block(f'Artifact {action} of another artifact ({url!r})')
    if url == V0:
        if action == 'list' and inp.get('scope') not in ('files', 'assets'):
            block('Artifact list of V0 other than its files or assets')
        paths = inp.get('paths') or ([inp['path']] if 'path' in inp else [])
        if action == 'read' and not paths and not gate_open(state):
            block('V0 page read before the exploration gate (read files by path)')
        for p in paths:
            check_v0_path(p, state)
    sys.exit(0)


def check_upload_sha(path, root):
    if root and not os.path.isabs(path):
        path = os.path.join(root, path)
    try:
        with open(path, 'rb') as f:
            sha = hashlib.sha256(f.read()).hexdigest()
    except Exception:
        return
    if sha in DENIED_SHA:
        block(f'upload of a denied V0 asset ({os.path.basename(path)}, requirements/v0-asset-denylist.json)')


def check_page_board(published, source, root):
    role = PAGE_BOARDS.get(published)
    if not role:
        return
    if root and not os.path.isabs(source):
        source = os.path.join(root, source)
    try:
        with open(source, errors='replace') as f:
            fails = check_requirements.check_board(f.read(), role, DENY)
    except OSError:
        block(f'cannot read {published} to check the WeMod requirements')
    if fails:
        block(f'{published} fails the WeMod requirements: ' + '; '.join(fails[:4]))


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
    if not gate_open(state):
        block(f'publish to the canvas before the exploration gate ({NARRATIVES})')
    root = inp.get('root')
    if root is not None and not in_scratchpad(root):
        block(f'root outside the session scratchpad ({root!r})')
    if inp.get('asset'):
        if 'from_url' in inp:
            if inp['from_url'] != V0:
                block(f'asset copy from an artifact other than V0 ({inp["from_url"]!r})')
            for aid in inp.get('asset_ids') or []:
                check_v0_path(aid, state)
        else:
            paths = inp.get('file_paths') or [inp.get('file_path')]
            for p in paths:
                if not in_scratchpad(p, root):
                    block(f'asset upload from outside the session scratchpad ({p!r})')
                check_upload_sha(p, root)
    else:
        if 'from_url' in inp or 'asset_ids' in inp or 'file_paths' in inp:
            block('asset fields on a page publish')
        if 'file_path' in inp and not in_scratchpad(inp['file_path'], root):
            block(f'file_path outside the session scratchpad ({inp["file_path"]!r})')
    files = inp.get('files')
    if files is not None:
        items = files.items() if isinstance(files, dict) else [(s, s) for s in files]
        for published, s in items:
            if s is None:
                continue  # removing one of the canvas's own files
            if isinstance(s, str):
                if not in_scratchpad(s, root):
                    block(f'files entry outside the session scratchpad ({s!r})')
                check_page_board(published, s, root)
            elif isinstance(s, dict) and 'artifact' in s:
                if strip_url(s.get('artifact')) != V0 or set(s) - {'artifact', 'path', 'ver'}:
                    block('files entry copying from an artifact other than V0')
                if published in PAGE_BOARDS:
                    block(f'{published} copied from V0 instead of written in the scratchpad')
            elif isinstance(s, dict) and 'from' in s and not set(s) - {'from', 'contentType'}:
                if not in_scratchpad(s['from'], root):
                    block(f'files entry outside the session scratchpad ({s["from"]!r})')
                check_page_board(published, s['from'], root)
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
    # Record the created canvas URL and subagent ids. Never blocks.
    state = load()
    resp = json.dumps(ev.get('tool_response'))
    if tool == 'Artifact' and inp.get('type_url') == DESIGN_TYPE:
        m = CREATED.search(resp)
        if m and not state.get('created_url'):
            state['created_url'] = m.group(1)
    if tool in ('Agent', 'Task'):
        state['agents'] = sorted(set(state.get('agents', [])) | set(AGENT_ID.findall(resp)))
    save(state)
    sys.exit(0)

if tool == 'Glob' and 'HOOK_PROBE' in str(inp.get('pattern', '')):
    block('Glob HOOK_PROBE (guard check)', tool)
if tool in FREE_TOOLS:
    sys.exit(0)
if tool == 'Skill':
    if inp.get('skill') == SKILL:
        sys.exit(0)
    block(f'skill {inp.get("skill")!r} (only {SKILL})', tool)
if tool in ('Agent', 'Task', 'SubagentHandback'):
    sys.exit(0)
if tool == 'SendMessage':
    state = load()
    to = inp.get('to')
    if set(inp) - SEND_KEYS:
        block(f'SendMessage with fields {sorted(set(inp) - SEND_KEYS)}', tool)
    known = set(state.get('agents', []))
    if to not in known:
        known |= agents_in_transcript(ev.get('transcript_path'))
        state['agents'] = sorted(known)
        save(state)
    if to in known:
        sys.exit(0)
    block(f'SendMessage to {to!r}, which is not a subagent of this run', tool)
if tool in ('Write', 'Edit', 'MultiEdit'):
    path = inp.get('file_path')
    if not in_scratchpad(path):
        block(f'{tool} outside the session scratchpad ({path!r})', tool)
    if is_narratives(path) and load().get('gate'):
        block(f'{NARRATIVES} is frozen: the exploration gate opened on it', tool)
    sys.exit(0)
if tool in ('Bash', 'Monitor'):
    cmd = inp.get('command')
    if not isinstance(cmd, str) or not cmd.strip():
        block('empty shell command', tool)
    m = SHELL_DENY.search(cmd)
    if m:
        block(f'shell command uses {m.group(1)!r}', tool)
    m = SHELL_DENY_TEXT.search(cmd)
    if m:
        block(f'shell command mentions {m.group(0)!r}', tool)
    for npm in re.finditer(r'(?<![\w-])npm\s+(\S+)', cmd):
        if npm.group(1) not in ('i', 'install', 'ls', '--version', '-v'):
            block(f'npm {npm.group(1)} (only npm install is allowed)', tool)
    if re.search(r'(?<![\w-])npx(?![\w-])', cmd):
        block('npx (run installed scripts with node instead)', tool)
    sys.exit(0)

if tool == 'Artifact':
    action = inp.get('action', 'publish')
    state = load()
    if state.get('create_attempted') and not state.get('created_url'):
        found = created_in_transcript(ev.get('transcript_path'))
        if found:
            state['created_url'] = found
            save(state)
    if action in ('read', 'list'):
        check_read(inp, state)
    if action != 'publish':
        block(f'Artifact action {action!r}', tool)
    if 'type_url' in inp:
        if inp.get('type_url') != DESIGN_TYPE:
            block(f'create from a type other than Design ({inp.get("type_url")!r})', tool)
        if set(inp) - CREATE_KEYS:
            block(f'create with extra fields {sorted(set(inp) - CREATE_KEYS)}', tool)
        if state.get('create_attempted'):
            block('a second Design create (only one is allowed)', tool)
        state['create_attempted'] = True
        save(state)
        sys.exit(0)
    check_fill(inp, state)

block(f'{tool} is not allowed in this probe', tool)
