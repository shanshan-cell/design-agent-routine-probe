#!/usr/bin/env python3
# Sequence test for Guard v5 (Test D). Feeds synthetic hook payloads in order; checks allow (0) / block (2).
#   python3 -I tests/guard_v5_test.py .claude/hooks/design_guard.py
# Uses a throwaway session folder under /tmp/claude-<uid>/ shaped like the cloud VM's scratchpad path.
import json, os, shutil, subprocess, sys, tempfile

GUARD = os.path.abspath(sys.argv[1])
HERE = os.path.dirname(os.path.abspath(__file__))
FIX = os.path.join(HERE, 'fixtures')
STATE = '/tmp/routine-probe-guard-state.json'
LOG = '/tmp/routine-probe-guard-log.jsonl'
BASE = f'/tmp/claude-{os.getuid()}/guard-v5-test'
SP = f'{BASE}/sess/scratchpad'
T = 'https://claude.ai/artifact/QKN21svewxgyPb6SYRqWnd'
V0 = 'https://claude.ai/artifact/KE3kJTKgBbXwSgvaaJkrLE'
NEW = 'https://claude.ai/artifact/NewCanvas123'
OTHER = 'https://claude.ai/artifact/SomeoneElses999'
AGENT = 'a0047061eb1ff025e'
AGENT2 = 'a155903b2dd867af9'
OK_ICON = '5dcf496cd897f84de40b87d3ddb05336'      # Production UI Icons/steam.svg
DENIED = '0ec2be3cbdec3dbd4f711823fbb2ca08'      # Production UI Icons/gog.svg
DENIED_ART = 'a28d89f37662030333cfc8f64265118b'  # setup-step-1-bg.svg (store orbit)

for p in (STATE, LOG):
    if os.path.exists(p):
        os.remove(p)
shutil.rmtree(BASE, ignore_errors=True)
os.makedirs(SP + '/gate')
os.makedirs(SP + '/canvas/project')
shutil.copy(os.path.join(FIX, 'Page-1440.ok.dc.html'), SP + '/canvas/project/Page-1440.dc.html')
shutil.copy(os.path.join(FIX, 'Page-390.ok.dc.html'), SP + '/canvas/project/ok-390.dc.html')
shutil.copy(os.path.join(FIX, 'testc-Mobile-390.dc.html'), SP + '/canvas/project/testc-390.dc.html')
shutil.copy(os.path.join(FIX, 'denied-gog.svg'), SP + '/canvas/renamed-icon.svg')
with open(SP + '/canvas/shot.png', 'wb') as f:
    f.write(b'\x89PNG not a denied asset')
NARR = SP + '/gate/page-narratives.md'

tr = tempfile.NamedTemporaryFile('w', suffix='.jsonl', delete=False)
tr.write(json.dumps({'message': {'content': [{'type': 'tool_result', 'content': f'Created a new Artifact at {NEW} (version 1-ab) from the Artifact type {T} (release r).'}]}}) + '\n')
tr.write(json.dumps({'message': {'content': [{'type': 'tool_result', 'content': f'Async agent launched successfully.\nagentId: {AGENT2} (internal ID)'}]}}) + '\n')
tr.close()


def call(tool, inp, post=False, resp=None):
    ev = {'tool_name': tool, 'tool_input': inp, 'transcript_path': tr.name}
    if resp is not None:
        ev['tool_response'] = resp
    p = subprocess.run(['python3', '-I', GUARD] + (['--post'] if post else []), input=json.dumps(ev),
                       capture_output=True, text=True)
    return p.returncode, p.stderr.strip()


def write_narratives(text):
    with open(NARR, 'w') as f:
        f.write(text)


GOOD = '# Page narratives\n\n' + ''.join(
    f'## Narrative {n}\n\nThesis, the visitor question at each step, the phone journey and its next step.\n' + 'x' * 600 + '\n\n'
    for n in 'ABC') + '## Section strategy\n\nEach section, its job and the evidence it shows.\n'

A, B = 0, 2
steps = [
    # --- v4 behaviour kept
    ('Glob HOOK_PROBE (guard check)', 'Glob', {'pattern': 'HOOK_PROBE*'}, B),
    ('Glob other pattern', 'Glob', {'pattern': '**/*.md'}, A),
    ('Read repo file', 'Read', {'file_path': '/home/user/design-agent-routine-probe/inputs/learnings-pre-gate.md'}, A),
    ('Skill wemod-page-designer', 'Skill', {'skill': 'anthropic-skills:wemod-page-designer', 'args': 'brief'}, A),
    ('Skill other', 'Skill', {'skill': 'anthropic-skills:design-to-figma-handoff'}, B),
    ('Write scratchpad', 'Write', {'file_path': SP + '/notes/intake.md'}, A),
    ('Write repo', 'Write', {'file_path': '/home/user/design-agent-routine-probe/x'}, B),
    ('Edit guard file', 'Edit', {'file_path': '/home/user/design-agent-routine-probe/.claude/hooks/design_guard.py'}, B),
    ('npm install playwright', 'Bash', {'command': f'cd {SP} && npm i playwright@1.49.1'}, A),
    ('node check-canvas', 'Bash', {'command': f'node {SP}/check-canvas.js {SP}/canvas/project'}, A),
    ('python3 requirements check', 'Bash', {'command': f'python3 tools/check_requirements.py --desktop {SP}/a --phone {SP}/b'}, A),
    ('git push', 'Bash', {'command': 'git push origin main'}, B),
    ('curl', 'Bash', {'command': 'curl https://api.linear.app/graphql'}, B),
    ('npx', 'Bash', {'command': 'npx something'}, B),
    ('tamper guard state', 'Bash', {'command': 'rm /tmp/routine-probe-guard-state.json'}, B),
    ('edit requirements via shell', 'Bash', {'command': "sed -i '' s/x/y/ requirements/v0-asset-denylist.json"}, B),
    ('edit gate list via shell', 'Bash', {'command': 'echo {} > gate/v0-pre-gate.json'}, B),
    ('WebFetch', 'WebFetch', {'url': 'https://example.com'}, B),
    ('Linear MCP', 'mcp__claude_ai_Linear__save_comment', {}, B),
    ('RemoteTrigger', 'RemoteTrigger', {'action': 'list'}, B),
    ('PushNotification', 'PushNotification', {'message': 'x'}, B),
    ('ListAgents', 'ListAgents', {}, B),
    # --- v5: reviewer subagents can hand back and be messaged
    ('Agent (reviewer)', 'Agent', {'prompt': 'review', 'description': 'review'}, A),
    ('SubagentHandback', 'SubagentHandback', {'message': 'INDEPENDENT DESIGN REVIEW ...'}, A),
    ('SendMessage before the agent id is known', 'SendMessage', {'to': AGENT, 'message': 'deliver your report'}, B),
    ('PostToolUse Agent records its id', 'Agent', {'prompt': 'review'}, A, True,
        {'content': [{'type': 'text', 'text': f'Async agent launched successfully.\nagentId: {AGENT} (internal ID)'}]}),
    ('SendMessage to own subagent', 'SendMessage', {'to': AGENT, 'message': 'deliver your report', 'summary': 'deliver report'}, A),
    ('SendMessage to subagent found in transcript', 'SendMessage', {'to': AGENT2, 'content': 'x', 'message': 'x'}, A),
    ('SendMessage to another session', 'SendMessage', {'to': 'design-agent-poc-session', 'message': 'x'}, B),
    ('SendMessage broadcast', 'SendMessage', {'to': '*', 'message': 'x'}, B),
    ('SendMessage with extra fields', 'SendMessage', {'to': AGENT, 'message': 'x', 'channel': 'slack'}, B),
    # --- v5: artifact reads limited to V0, the type and the canvas
    ('list account artifacts', 'Artifact', {'action': 'list'}, B),
    ('list artifacts of a type', 'Artifact', {'action': 'list', 'type': 'Design'}, B),
    ('list type catalogue', 'Artifact', {'action': 'list', 'scope': 'types'}, A),
    ('list V0 files', 'Artifact', {'action': 'list', 'scope': 'files', 'url': V0}, A),
    ('read another artifact', 'Artifact', {'action': 'read', 'url': OTHER}, B),
    ('read the Design type', 'Artifact', {'action': 'read', 'url': T}, A),
    ('read with out_dir', 'Artifact', {'action': 'read', 'url': V0, 'path': 'project/00-generation-contract.md', 'out_dir': '/'}, B),
    # --- v5: exploration gate (closed)
    ('pre-gate: 00 generation contract', 'Artifact', {'action': 'read', 'url': V0, 'path': 'project/00-generation-contract.md'}, A),
    ('pre-gate: foundations in one call', 'Artifact', {'action': 'read', 'url': V0, 'paths': ['project/11-terminology-and-claims.md', 'project/27-goal-journey-intent.md', 'project/tokens.json']}, A),
    ('pre-gate: 29 pattern library', 'Artifact', {'action': 'read', 'url': V0, 'path': 'project/29-pattern-library-and-verdicts.md'}, B),
    ('pre-gate: 29 hidden in a batch', 'Artifact', {'action': 'read', 'url': V0, 'paths': ['project/00-generation-contract.md', 'project/29-pattern-library-and-verdicts.md']}, B),
    ('pre-gate: 26 gates (calibration verdicts)', 'Artifact', {'action': 'read', 'url': V0, 'path': 'project/26-design-gates.md'}, B),
    ('pre-gate: 24 layout library', 'Artifact', {'action': 'read', 'url': V0, 'path': 'project/24-layout-library.md'}, B),
    ('pre-gate: 13 homepage compositions', 'Artifact', {'action': 'read', 'url': V0, 'path': 'project/13-homepage-layer.md'}, B),
    ('pre-gate: layout-library specimen', 'Artifact', {'action': 'read', 'url': V0, 'path': 'project/layout-library/specimens/HB01.html'}, B),
    ('pre-gate: exemplar canvas', 'Artifact', {'action': 'read', 'url': V0, 'path': 'project/assets/Exemplars/homepage-a-v4.dc.html.txt'}, B),
    ('pre-gate: component preview', 'Artifact', {'action': 'read', 'url': V0, 'path': 'project/components/PageGamePage/preview.html'}, B),
    ('pre-gate: archived history', 'Artifact', {'action': 'read', 'url': V0, 'path': 'project/archived/25-art-direction-pilot-history.md'}, B),
    ('pre-gate: V0 page without a path', 'Artifact', {'action': 'read', 'url': V0}, B),
    ('pre-gate: production icon asset', 'Artifact', {'action': 'read', 'url': V0, 'path': OK_ICON}, A),
    ('pre-gate: specimen asset (not production media)', 'Artifact', {'action': 'read', 'url': V0, 'path': 'f5cc6caa8b397b510919c94d8bc74140'}, B),
    ('denied asset read (gog icon)', 'Artifact', {'action': 'read', 'url': V0, 'path': DENIED}, B),
    ('create Design (the one allowed)', 'Artifact', {'action': 'publish', 'type_url': T, 'title': 'WeMod RDR2 (Test D)', 'auto_open': 'after_first_write'}, A),
    ('second create', 'Artifact', {'type_url': T, 'title': 'again'}, B),
    ('fill before the gate opens', 'Artifact', {'action': 'publish', 'url': NEW, 'root': SP + '/canvas', 'file_path': SP + '/canvas/project/canvas.json'}, B),
    ('read the created canvas', 'Artifact', {'action': 'read', 'url': NEW}, A),
    ('narratives too thin', 'Write', {'file_path': NARR}, A, False, None, lambda: write_narratives('## Narrative A\nshort\n')),
    ('29 still gated with thin narratives', 'Artifact', {'action': 'read', 'url': V0, 'path': 'project/29-pattern-library-and-verdicts.md'}, B),
    ('narratives written', 'Write', {'file_path': NARR}, A, False, None, lambda: write_narratives(GOOD)),
    # --- gate open
    ('post-gate: 29 pattern library', 'Artifact', {'action': 'read', 'url': V0, 'path': 'project/29-pattern-library-and-verdicts.md'}, A),
    ('post-gate: 24 and a specimen', 'Artifact', {'action': 'read', 'url': V0, 'paths': ['project/24-layout-library.md', 'project/layout-library/specimens/HB01.html']}, A),
    ('post-gate: specimen asset', 'Artifact', {'action': 'read', 'url': V0, 'path': 'f5cc6caa8b397b510919c94d8bc74140'}, A),
    ('post-gate: denied asset still denied', 'Artifact', {'action': 'read', 'url': V0, 'path': DENIED_ART}, B),
    ('narratives frozen: Edit', 'Edit', {'file_path': NARR, 'old_string': 'A', 'new_string': 'B'}, B),
    ('narratives frozen: Write', 'Write', {'file_path': NARR}, B),
    ('narratives frozen: shell', 'Bash', {'command': f'cat new.md > {NARR}'}, B),
    ('narratives readable', 'Read', {'file_path': NARR}, A),
    # --- fills and the shared requirements
    ('fill: index + compliant desktop board', 'Artifact', {'action': 'publish', 'url': NEW, 'root': SP + '/canvas', 'file_path': SP + '/canvas/project/canvas.json',
        'files': {'project/Page-1440.dc.html': 'project/Page-1440.dc.html', 'project/ds/wemodweb/tokens.json': {'artifact': V0, 'path': 'project/tokens.json'}}}, A),
    ('fill: compliant phone board', 'Artifact', {'action': 'publish', 'url': NEW, 'root': SP + '/canvas', 'files': {'project/Page-390.dc.html': 'project/ok-390.dc.html'}}, A),
    ('fill: Test C phone board as Page-390 (R1, R2)', 'Artifact', {'action': 'publish', 'url': NEW, 'root': SP + '/canvas', 'files': {'project/Page-390.dc.html': 'project/testc-390.dc.html'}}, B),
    ('fill: Test C phone board, {from} form', 'Artifact', {'action': 'publish', 'url': NEW, 'root': SP + '/canvas', 'files': {'project/Page-390.dc.html': {'from': 'project/testc-390.dc.html', 'contentType': 'text/html'}}}, B),
    ('fill: page board copied from V0', 'Artifact', {'action': 'publish', 'url': NEW, 'files': {'project/Page-390.dc.html': {'artifact': V0, 'path': 'project/components/PageGamePage/preview.html'}}}, B),
    ('fill: other board is not page-checked', 'Artifact', {'action': 'publish', 'url': NEW, 'root': SP + '/canvas', 'files': {'project/Review.dc.html': 'project/testc-390.dc.html'}}, A),
    ('copy production icon from V0', 'Artifact', {'action': 'publish', 'url': NEW, 'asset': True, 'from_url': V0, 'asset_ids': [OK_ICON]}, A),
    ('copy denied store orbit from V0', 'Artifact', {'action': 'publish', 'url': NEW, 'asset': True, 'from_url': V0, 'asset_ids': [OK_ICON, DENIED_ART]}, B),
    ('copy an RDR2 Page Media asset', 'Artifact', {'action': 'publish', 'url': NEW, 'asset': True, 'from_url': V0, 'asset_ids': [None]}, B),
    ('upload a renamed denied asset (sha256)', 'Artifact', {'action': 'publish', 'url': NEW, 'asset': True, 'file_path': SP + '/canvas/renamed-icon.svg'}, B),
    ('upload a screenshot', 'Artifact', {'action': 'publish', 'url': NEW, 'asset': True, 'file_path': SP + '/canvas/shot.png'}, A),
    ('copy assets from another artifact', 'Artifact', {'action': 'publish', 'url': NEW, 'asset': True, 'from_url': OTHER, 'asset_ids': ['a' * 32]}, B),
    ('publish to V0', 'Artifact', {'action': 'publish', 'url': V0, 'file_path': SP + '/canvas/a.html'}, B),
    ('capabilities', 'Artifact', {'action': 'publish', 'url': NEW, 'file_path': SP + '/canvas/a.html', 'capabilities': {'db': {}}}, B),
    ('force', 'Artifact', {'action': 'publish', 'url': NEW, 'file_path': SP + '/canvas/a.html', 'force': True}, B),
    ('pin', 'Artifact', {'action': 'pin', 'url': NEW}, B),
    ('delete', 'Artifact', {'action': 'delete', 'url': NEW}, B),
]

# An RDR2 Page Media id from the denylist for the step that expects one.
deny = json.load(open(os.path.join(HERE, '..', 'requirements', 'v0-asset-denylist.json')))
rdr2 = next(k for k, v in deny['denied'].items() if v['name'].startswith('RDR2 Page Media/'))

ok = True
for step in steps:
    name, tool, inp, want = step[:4]
    post = step[4] if len(step) > 4 else False
    resp = step[5] if len(step) > 5 else None
    before = step[6] if len(step) > 6 else None
    if inp.get('asset_ids') == [None]:
        inp['asset_ids'] = [rdr2]
    rc, err = call(tool, inp, post, resp)
    if before:
        before()  # the tool "runs" after the hook allows it
    ok &= rc == want
    print(f'{"PASS" if rc == want else "FAIL"} {name:48} exit={rc} {err[:110]}')

events = [json.loads(l) for l in open(LOG)]
opened = [e for e in events if e['event'] == 'gate_open']
gate_ok = len(opened) == 1 and opened[0]['path'].endswith('/scratchpad/gate/page-narratives.md')
print(f'{"PASS" if gate_ok else "FAIL"} {"gate log: opened once, on the narratives file":48} {len(events)} events')
ok &= gate_ok

shutil.rmtree(BASE, ignore_errors=True)
for p in (STATE, LOG, tr.name):
    os.remove(p)
print('ALL PASS' if ok else 'SOME FAILED')
sys.exit(0 if ok else 1)
