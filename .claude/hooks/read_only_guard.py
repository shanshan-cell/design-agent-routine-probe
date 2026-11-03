#!/usr/bin/env python3
# Guard v3 for the routine capability probe (Test B: one native Design canvas).
#
# PreToolUse (every tool) allows only:
#   - ToolSearch, Read
#   - Artifact read/list (no out_dir)
#   - ONE Artifact create from the Design type (type_url DESIGN_TYPE, no url, no files). The attempt is recorded before
#     the call runs, so a second create is blocked even if the first one failed.
#   - Artifact publishes to the one artifact that create returned (recorded by the PostToolUse hook below), at most
#     MAX_FILLS, with page files from the session scratchpad only: no asset copies, no files copied from another
#     artifact, no runtime capabilities, no force, no pin.
#   - Write/Edit of files inside the session scratchpad only (the canvas files to publish).
# Everything else is blocked with exit 2 and the marker. Glob is always blocked: the run's first call uses it to prove
# this hook is active.
#
# PostToolUse (Artifact only, run with --post) records the URL of the created artifact.
import json
import os
import re
import sys

MARKER = 'ROUTINE-PROBE-GUARD-v3'
DESIGN_TYPE = 'https://claude.ai/artifact/QKN21svewxgyPb6SYRqWnd'
STATE = '/tmp/routine-probe-guard-state.json'
MAX_FILLS = 6
CREATE_KEYS = {'action', 'type_url', 'title', 'auto_open', 'description', 'icon'}
FILL_KEYS = {'action', 'url', 'file_path', 'root', 'files', 'description', 'label'}
CREATED = re.compile(r'Created a new Artifact at (https://claude\.ai/artifact/[A-Za-z0-9]+)')


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


def in_scratchpad(path):
    if not isinstance(path, str) or not path:
        return False
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


try:
    ev = json.load(sys.stdin)
except Exception:
    block('unreadable hook input')

tool = ev.get('tool_name') or ''
inp = ev.get('tool_input') or {}

if '--post' in sys.argv:
    # Record the created artifact's URL. Never blocks.
    if tool == 'Artifact' and inp.get('type_url') == DESIGN_TYPE:
        m = CREATED.search(json.dumps(ev.get('tool_response')))
        state = load()
        if m and not state.get('created_url'):
            state['created_url'] = m.group(1)
            save(state)
    sys.exit(0)

action = inp.get('action', 'publish')
state = load()

if tool in ('ToolSearch', 'Read'):
    sys.exit(0)

if tool in ('Write', 'Edit'):
    if in_scratchpad(inp.get('file_path')):
        sys.exit(0)
    block(f'{tool} outside the session scratchpad ({inp.get("file_path")!r})')

if tool == 'Artifact':
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
    # A fill: a publish to the artifact the one create returned. In Test B's cloud run the PostToolUse hook did not
    # record it, so fall back to the create's result text in the session transcript.
    if state.get('create_attempted') and not state.get('created_url'):
        found = created_in_transcript(ev.get('transcript_path'))
        if found:
            state['created_url'] = found
            save(state)
    if not state.get('created_url'):
        block('publish before the Design canvas was created')
    if inp.get('url') != state['created_url']:
        block(f'publish to another artifact ({inp.get("url")!r})')
    if set(inp) - FILL_KEYS:
        block(f'publish with fields {sorted(set(inp) - FILL_KEYS)}')
    if state.get('fills', 0) >= MAX_FILLS:
        block(f'more than {MAX_FILLS} publishes to the canvas')
    for key in ('file_path', 'root'):
        if key in inp and not in_scratchpad(inp[key]):
            block(f'{key} outside the session scratchpad ({inp[key]!r})')
    files = inp.get('files')
    if files is not None:
        sources = list(files.values()) if isinstance(files, dict) else files
        for s in sources:
            if not isinstance(s, (str, dict)) or (isinstance(s, dict) and set(s) - {'from', 'contentType'}):
                block('files entry that copies from another artifact or removes a file')
    state['fills'] = state.get('fills', 0) + 1
    save(state)
    sys.exit(0)

block(f'{tool} is not allowed in this probe')
