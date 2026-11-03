#!/usr/bin/env python3
# Sequence test for Guard v4 (Test C). Feeds synthetic hook payloads in order; checks allow (0) / block (2).
#   python3 -I tests/guard_v4_test.py .claude/hooks/design_guard.py
import json, os, subprocess, sys, tempfile

GUARD = sys.argv[1]
STATE = '/tmp/routine-probe-guard-state.json'
SP = '/tmp/claude-0/-home-user-design-agent-routine-probe/abc/scratchpad/canvas'
T = 'https://claude.ai/artifact/QKN21svewxgyPb6SYRqWnd'
V0 = 'https://claude.ai/artifact/KE3kJTKgBbXwSgvaaJkrLE'
NEW = 'https://claude.ai/artifact/NewCanvas123'
OTHER = 'https://claude.ai/artifact/SomeoneElses999'
if os.path.exists(STATE):
    os.remove(STATE)
tr = tempfile.NamedTemporaryFile('w', suffix='.jsonl', delete=False)
tr.write(json.dumps({'message': {'content': [{'type': 'tool_result', 'content': f'Created a new Artifact at {NEW} (version 1-ab) from the Artifact type {T} (release r).'}]}}) + '\n')
tr.close()

def call(tool, inp):
    p = subprocess.run(['python3', '-I', GUARD], input=json.dumps({'tool_name': tool, 'tool_input': inp, 'transcript_path': tr.name}),
                       capture_output=True, text=True)
    return p.returncode, p.stderr.strip()

A, B = 0, 2
steps = [
    # guard check and read-only tools
    ('Glob HOOK_PROBE (guard check)', 'Glob', {'pattern': 'HOOK_PROBE*'}, B),
    ('Glob other pattern', 'Glob', {'pattern': '**/*.md'}, A),
    ('Read', 'Read', {'file_path': '/home/user/design-agent-routine-probe/README.md'}, A),
    # skill and subagents
    ('Skill wemod-page-designer', 'Skill', {'skill': 'anthropic-skills:wemod-page-designer', 'args': 'brief'}, A),
    ('Skill design-to-figma-handoff', 'Skill', {'skill': 'anthropic-skills:design-to-figma-handoff'}, B),
    ('Skill other', 'Skill', {'skill': 'schedule'}, B),
    ('Agent (independent reviewer)', 'Agent', {'prompt': 'review', 'description': 'review'}, A),
    # files
    ('Write scratchpad', 'Write', {'file_path': SP + '/project/Main.dc.html'}, A),
    ('Write repo', 'Write', {'file_path': '/home/user/design-agent-routine-probe/x'}, B),
    ('Edit hook file', 'Edit', {'file_path': '/home/user/design-agent-routine-probe/.claude/hooks/design_guard.py'}, B),
    # shell
    ('npm install playwright', 'Bash', {'command': f'cd {SP}/.. && npm i playwright@1.49.1'}, A),
    ('node check-canvas', 'Bash', {'command': f'node {SP}/../check-canvas.js {SP}/project --control x'}, A),
    ('ls/mkdir/cp', 'Bash', {'command': f'mkdir -p {SP}/shots && ls {SP} && cp a b'}, A),
    ('git push', 'Bash', {'command': 'git push origin main'}, B),
    ('git status', 'Bash', {'command': 'cd /home/user/design-agent-routine-probe && git status'}, B),
    ('gh api', 'Bash', {'command': 'gh api repos/x/y'}, B),
    ('curl', 'Bash', {'command': 'curl https://api.linear.app/graphql'}, B),
    ('python urllib to linear', 'Bash', {'command': 'python3 -c "import urllib.request;urllib.request.urlopen(\'https://api.linear.app\')"'}, B),
    ('playwright install', 'Bash', {'command': 'node node_modules/playwright/cli.js install chromium && npx playwright install'}, B),
    ('npx', 'Bash', {'command': 'npx something'}, B),
    ('npm publish', 'Bash', {'command': 'npm publish'}, B),
    ('pip install', 'Bash', {'command': 'pip install requests'}, B),
    ('sed on hooks', 'Bash', {'command': 'sed -i s/x/y/ .claude/hooks/design_guard.py'}, B),
    ('tamper guard state', 'Bash', {'command': 'rm /tmp/routine-probe-guard-state.json'}, B),
    ('Monitor with curl', 'Monitor', {'command': 'curl https://example.com', 'description': 'x'}, B),
    # other tools
    ('WebFetch', 'WebFetch', {'url': 'https://example.com'}, B),
    ('Linear MCP', 'mcp__Linear__save_comment', {}, B),
    ('ArtifactData', 'ArtifactData', {'action': 'list'}, B),
    ('DesignSync', 'DesignSync', {'method': 'list_projects'}, B),
    ('RemoteTrigger', 'RemoteTrigger', {'action': 'list'}, B),
    # artifacts
    ('read V0 file', 'Artifact', {'action': 'read', 'url': V0, 'paths': ['project/00-generation-contract.md']}, A),
    ('list Design Systems', 'Artifact', {'action': 'list', 'type': 'Design System'}, A),
    ('read with out_dir', 'Artifact', {'action': 'read', 'url': V0, 'out_dir': '/'}, B),
    ('publish to V0', 'Artifact', {'action': 'publish', 'url': V0, 'file_path': SP + '/a.html'}, B),
    ('fill before create', 'Artifact', {'action': 'publish', 'url': NEW, 'file_path': SP + '/a.html'}, B),
    ('create other type', 'Artifact', {'type_url': 'https://claude.ai/artifact/Slides', 'title': 't'}, B),
    ('create Design (the one allowed)', 'Artifact', {'action': 'publish', 'type_url': T, 'title': 'WeMod RDR2', 'auto_open': 'after_first_write'}, A),
    ('second create', 'Artifact', {'type_url': T, 'title': 'again'}, B),
    ('fill index + entry (+V0 tokens copy)', 'Artifact', {'action': 'publish', 'url': NEW, 'root': SP, 'file_path': SP + '/project/canvas.json',
        'files': {'project/Main.dc.html': 'project/Main.dc.html', 'project/ds/wemod-web-v0/tokens.json': {'artifact': V0, 'path': 'project/tokens.json'}}}, A),
    ('copy V0 assets into canvas', 'Artifact', {'action': 'publish', 'url': NEW, 'asset': True, 'from_url': V0, 'asset_ids': ['a' * 32]}, A),
    ('copy assets from another artifact', 'Artifact', {'action': 'publish', 'url': NEW, 'asset': True, 'from_url': OTHER, 'asset_ids': ['a' * 32]}, B),
    ('upload scratchpad screenshot as asset', 'Artifact', {'action': 'publish', 'url': NEW, 'asset': True, 'file_path': SP + '/shots/a.png'}, A),
    ('upload repo file as asset', 'Artifact', {'action': 'publish', 'url': NEW, 'asset': True, 'file_path': '/home/user/design-agent-routine-probe/README.md'}, B),
    ('files entry copied from other artifact', 'Artifact', {'action': 'publish', 'url': NEW, 'files': {'x.css': {'artifact': OTHER, 'path': 'x.css'}}}, B),
    ('files entry relative escaping root', 'Artifact', {'action': 'publish', 'url': NEW, 'root': SP, 'file_path': SP + '/project/a.dc.html', 'files': {'project/b': '../../../../../../home/user/.ssh/id_rsa'}}, B),
    ('capabilities', 'Artifact', {'action': 'publish', 'url': NEW, 'file_path': SP + '/a.html', 'capabilities': {'db': {}}}, B),
    ('force', 'Artifact', {'action': 'publish', 'url': NEW, 'file_path': SP + '/a.html', 'force': True}, B),
    ('contract', 'Artifact', {'action': 'publish', 'url': NEW, 'file_path': SP + '/a.html', 'contract': 'latest'}, B),
    ('pin', 'Artifact', {'action': 'pin', 'url': NEW}, B),
    ('delete', 'Artifact', {'action': 'delete', 'url': NEW}, B),
    ('read canvas back', 'Artifact', {'action': 'read', 'url': NEW}, A),
]
ok = True
for name, tool, inp, want in steps:
    rc, err = call(tool, inp)
    ok &= rc == want
    print(f'{"PASS" if rc == want else "FAIL"} {name:40} exit={rc} {err[:96]}')
os.remove(STATE); os.remove(tr.name)
print('ALL PASS' if ok else 'SOME FAILED')
sys.exit(0 if ok else 1)
