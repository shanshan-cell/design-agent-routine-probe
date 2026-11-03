#!/usr/bin/env python3
# Sequence test for Guard v2: feeds synthetic hook payloads in order and checks allow (0) / block (2).
import json, os, subprocess, sys

GUARD = sys.argv[1]
STATE = '/tmp/routine-probe-guard-state.json'
SP = '/tmp/claude-0/-home-user-design-agent-routine-probe/abc/scratchpad/canvas'
T = 'https://claude.ai/artifact/QKN21svewxgyPb6SYRqWnd'
NEW = 'https://claude.ai/artifact/NewCanvas123'
OTHER = 'https://claude.ai/artifact/KE3kJTKgBbXwSgvaaJkrLE'
if os.path.exists(STATE):
    os.remove(STATE)

def call(tool, inp, post=False, resp=None):
    ev = {'tool_name': tool, 'tool_input': inp}
    if resp is not None:
        ev['tool_response'] = resp
    p = subprocess.run(['python3', '-I', GUARD] + (['--post'] if post else []), input=json.dumps(ev),
                       capture_output=True, text=True)
    return p.returncode, p.stderr.strip()

steps = [
    ('Glob hook probe', 'Glob', {'pattern': 'HOOK_PROBE*'}, 2),
    ('Bash', 'Bash', {'command': 'ls'}, 2),
    ('Skill', 'Skill', {'skill': 'anthropic-skills:wemod-page-designer'}, 2),
    ('Linear MCP', 'mcp__Linear__save_comment', {}, 2),
    ('Write into repo', 'Write', {'file_path': '/home/user/design-agent-routine-probe/x.html'}, 2),
    ('Write into scratchpad', 'Write', {'file_path': SP + '/project/canvas.json'}, 0),
    ('Artifact read V0', 'Artifact', {'action': 'read', 'url': OTHER}, 0),
    ('fill before create', 'Artifact', {'action': 'publish', 'url': NEW, 'file_path': SP + '/a.html'}, 2),
    ('create from Slides-like other type', 'Artifact', {'action': 'publish', 'type_url': 'https://claude.ai/artifact/Other', 'title': 't'}, 2),
    ('create with extra field', 'Artifact', {'action': 'publish', 'type_url': T, 'title': 't', 'file_path': SP + '/a'}, 2),
    ('create Design (the one allowed)', 'Artifact', {'action': 'publish', 'type_url': T, 'title': 'Probe', 'auto_open': 'after_first_write'}, 0),
    ('second create', 'Artifact', {'type_url': T, 'title': 'again'}, 2),
]
ok = True
for name, tool, inp, want in steps:
    rc, err = call(tool, inp)
    ok &= rc == want
    print(f'{"PASS" if rc == want else "FAIL"} {name:38} exit={rc} {err[:110]}')
# PostToolUse records the created URL from the create result text.
rc, _ = call('Artifact', {'action': 'publish', 'type_url': T, 'title': 'Probe'}, post=True,
             resp=f'Created a new Artifact at {NEW} (version 1-ab) from the Artifact type {T} (release r).')
print('post-hook recorded:', json.load(open(STATE)))
steps2 = [
    ('fill the created canvas', 'Artifact', {'action': 'publish', 'url': NEW, 'root': SP, 'file_path': SP + '/project/canvas.json'}, 0),
    ('publish to another artifact', 'Artifact', {'action': 'publish', 'url': OTHER, 'file_path': SP + '/a.html'}, 2),
    ('fill with asset copy', 'Artifact', {'action': 'publish', 'url': NEW, 'asset': True, 'from_url': OTHER, 'asset_ids': ['a' * 32]}, 2),
    ('fill copying another artifact file', 'Artifact', {'action': 'publish', 'url': NEW, 'files': {'x.css': {'artifact': OTHER, 'path': 'x.css'}}}, 2),
    ('fill with capabilities', 'Artifact', {'action': 'publish', 'url': NEW, 'file_path': SP + '/a.html', 'capabilities': {'db': {}}}, 2),
    ('fill with force', 'Artifact', {'action': 'publish', 'url': NEW, 'file_path': SP + '/a.html', 'force': True}, 2),
    ('fill from outside scratchpad', 'Artifact', {'action': 'publish', 'url': NEW, 'file_path': '/home/user/design-agent-routine-probe/README.md'}, 2),
    ('delete canvas', 'Artifact', {'action': 'delete', 'url': NEW}, 2),
    ('pin canvas', 'Artifact', {'action': 'pin', 'url': NEW}, 2),
    ('read the canvas back', 'Artifact', {'action': 'read', 'url': NEW}, 0),
]
for name, tool, inp, want in steps2:
    rc, err = call(tool, inp)
    ok &= rc == want
    print(f'{"PASS" if rc == want else "FAIL"} {name:38} exit={rc} {err[:110]}')
for i in range(6):
    rc, err = call('Artifact', {'action': 'publish', 'url': NEW, 'file_path': SP + f'/f{i}.html'})
print(f'{"PASS" if rc == 2 else "FAIL"} {"7th fill over the cap":38} exit={rc} {err[:110]}')
ok &= rc == 2
os.remove(STATE)
print('ALL PASS' if ok else 'SOME FAILED')
