#!/usr/bin/env python3
# Offline tests for bridge/bridge.py and tools/report_result.py: a fake Linear, GitHub and fire endpoint, driven
# through whole ticks.
#   python3 -I tests/bridge_test.py
import base64
import calendar
import copy
import json
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, 'bridge'))
import bridge  # noqa: E402

CLAUDE = 'd3ff2737-0bdc-41a7-855b-3168295c4823'
AI_DESIGN = {'id': '56a3977a-dd58-4cec-a0aa-9522df1f27fb', 'name': 'ai-design'}
T = 'WAND-9001'
OTHER = 'WAND-9002'
FIRE_URL = 'https://api.anthropic.com/v1/claude_code/routines/trig_01TestTestTest/fire'
CANVAS = 'https://claude.ai/artifact/AbCdEfGhIjKlMnOp'
BRIEF = '# WeMod - RDR2 Unlimited Health\nDesign a full page for players searching for the mod. ' * 3

passed = failed = 0


def check(name, cond):
    global passed, failed
    if cond:
        passed += 1
    else:
        failed += 1
        print(f'FAIL {name}')


def cfg():
    c = bridge.load_config()
    c['allowed_tickets'] = [T]
    return c


class World:
    """In-memory Linear + GitHub + fire endpoint behind bridge.http."""

    def __init__(self):
        self.issues = {
            T: {'id': 'uuid-1', 'identifier': T, 'title': 'RDR2 Unlimited Health page', 'description': BRIEF,
                'url': f'https://linear.app/wemod/issue/{T}', 'state': {'type': 'unstarted'},
                'labels': {'nodes': [AI_DESIGN]}, 'creator': {'id': 'u2', 'name': 'A PM'}, 'comments': {'nodes': []}},
            OTHER: {'id': 'uuid-2', 'identifier': OTHER, 'title': 'Other', 'description': BRIEF,
                    'url': 'x', 'state': {'type': 'unstarted'}, 'labels': {'nodes': [AI_DESIGN]}, 'creator': None,
                    'comments': {'nodes': []}},
        }
        self.read = []          # Linear issue reads (identifiers)
        self.comments = []      # (identifier, body)
        self.refs = {}          # 'refs/tags/x' -> tag object sha
        self.tags = {}          # sha -> {'message', 'date'}
        self.branches = {}      # branch -> {'files': [...], 'ahead': n, 'doc': {...}}
        self.fires = []
        self.fire_status = 200
        self.race = False       # the next ref create returns 422

    def http(self, method, url, headers, body=None, timeout=30):
        if url == bridge.LINEAR_URL:
            q, v = body['query'], body['variables']
            if 'commentCreate' in q:
                ident = next(k for k, i in self.issues.items() if i['id'] == v['issueId'])
                self.comments.append((ident, v['body']))
                self.issues[ident]['comments']['nodes'].append({'id': 'c', 'body': v['body'], 'user': {'id': CLAUDE}})
                return 200, {'data': {'commentCreate': {'success': True, 'comment': {'id': 'c', 'url': 'https://linear.app/c'}}}}
            self.read.append(v['id'])
            return 200, {'data': {'issue': copy.deepcopy(self.issues.get(v['id']))}}
        if url == FIRE_URL:
            self.fires.append(body['text'])
            if self.fire_status != 200:
                return self.fire_status, {'type': 'error', 'error': {'type': 'rate_limit_error'}}
            return 200, {'type': 'routine_fire', 'claude_code_session_id': f'session_{len(self.fires)}',
                         'claude_code_session_url': f'https://claude.ai/code/session_{len(self.fires)}'}
        path = url.split('/repos/owner/repo/', 1)[1]
        if method == 'GET' and path.startswith('git/matching-refs/'):
            pre = 'refs/' + path[len('git/matching-refs/'):]
            refs = list(self.refs) + [f'refs/heads/{b}' for b in self.branches]
            return 200, [{'ref': r} for r in refs if r.startswith(pre)]
        if method == 'GET' and path.startswith('git/ref/tags/'):
            sha = self.refs.get('refs/tags/' + path[len('git/ref/tags/'):])
            return (200, {'object': {'type': 'tag', 'sha': sha}}) if sha else (404, None)
        if method == 'GET' and path.startswith('git/tags/'):
            t = self.tags[path[len('git/tags/'):]]
            return 200, {'message': t['message'], 'tagger': {'date': t['date']}}
        if method == 'GET' and path == 'git/ref/heads/main':
            return 200, {'object': {'sha': 'mainsha'}}
        if method == 'POST' and path == 'git/tags':
            sha = f'tag{len(self.tags)}'
            self.tags[sha] = {'message': body['message'], 'date': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
            return 201, {'sha': sha}
        if method == 'POST' and path == 'git/refs':
            if self.race or body['ref'] in self.refs:
                self.race = False
                return 422, None
            self.refs[body['ref']] = body['sha']
            return 201, None
        if method == 'GET' and path.startswith('compare/main...'):
            b = self.branches[path[len('compare/main...'):]]
            return 200, {'ahead_by': b['ahead'], 'files': [{'filename': f} for f in b['files']]}
        if method == 'GET' and path.startswith('contents/'):
            b = self.branches[path.split('?ref=')[1]]
            raw = json.dumps(b['doc']).encode()
            return 200, {'size': len(raw), 'content': base64.b64encode(raw).decode()}
        raise AssertionError(f'unexpected {method} {url}')

    def age_claims(self, minutes):
        for t in self.tags.values():
            then = calendar.timegm(time.strptime(t['date'], '%Y-%m-%dT%H:%M:%SZ')) - minutes * 60
            t['date'] = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(then))


def tick(w, c, dry=False):
    bridge.http = w.http
    lin = bridge.Linear('lin_api_test', dry)
    gh = bridge.GitHub('ghs_test', 'owner/repo', dry)
    for step in (lambda: bridge.collect(c, lin, gh), lambda: bridge.sweep(c, lin, gh, time.time()),
                 lambda: bridge.poll(c, lin, gh, FIRE_URL, 'sk-ant-oat01-test')):
        step()


def key_for(w, t=T):
    i = w.issues[t]
    return bridge.run_key(t, bridge.fingerprint(i['title'], i['description']))


def ready_doc(key, **over):
    d = {'contract': bridge.CONTRACT, 'ticket': T, 'run_key': key, 'status': 'ready', 'canvas_url': CANVAS,
         'canvas_title': 'WAND-9001 - RDR2 Unlimited Health - Design exploration',
         'summary': 'A question-led page: what it does, how to turn it on, story mode only. See https://evil.example',
         'limitations': ['Review verdict Revise (A70/B62).', 'No RDR2 media approved yet.']}
    d.update(over)
    return d


def push_result(w, key, doc, files=None, ahead=1):
    w.branches[f'claude/design-result-{key}'] = {'files': files or [f'results/{key}.json'], 'ahead': ahead, 'doc': doc}


c = cfg()

# --- eligibility and fingerprints ---
w = World()
i = w.issues[T]
check('eligible with the ai-design label', bridge.eligible(i, c) == (True, ''))
check('not eligible off the allowlist', not bridge.eligible(w.issues[OTHER], c)[0])
check('not eligible without labels', not bridge.eligible({**i, 'labels': {'nodes': []}}, c)[0])
check('not eligible with a same-named label from another team', not bridge.eligible({**i, 'labels': {'nodes': [{'id': 'other', 'name': 'ai-design'}]}}, c)[0])
check('not eligible with the Data team label', not bridge.eligible({**i, 'labels': {'nodes': [{'id': 'x', 'name': 'claude-analysis'}]}}, c)[0])
check('assignment alone does not trigger', not bridge.eligible({**i, 'labels': {'nodes': []}, 'assignee': {'id': CLAUDE}}, c)[0])
check('not eligible when closed', not bridge.eligible({**i, 'state': {'type': 'completed'}}, c)[0])
check('not eligible without a brief', not bridge.eligible({**i, 'description': 'tbd'}, c)[0])
check('fingerprint is stable', bridge.fingerprint('a', 'b') == bridge.fingerprint('a', 'b'))
check('fingerprint follows the brief', bridge.fingerprint('a', 'b') != bridge.fingerprint('a', 'c'))
check('fire text carries ticket and run key', f'run_key: {key_for(w)}' in bridge.fire_text(i, key_for(w)))
check('fire text bounded', len(bridge.fire_text({**i, 'description': 'x' * 100000}, 'k')) <= 60000)

# --- poll: one fire per brief version ---
w = World()
tick(w, c)
k = key_for(w)
check('first tick fires once', len(w.fires) == 1 and f'ticket: {T}' in w.fires[0])
check('claim and fired tags exist', f'refs/tags/design-claim/{k}' in w.refs and f'refs/tags/design-fired/{k}' in w.refs)
check('non-allowlisted ticket never read', OTHER not in w.read)
tick(w, c)
check('second tick does not fire again', len(w.fires) == 1)
check('no comment while the run is in flight', w.comments == [])
w.issues[T]['description'] += '\nAlso: mobile first.'
tick(w, c)
check('an edited brief fires a new run', len(w.fires) == 2)

w = World()
w.race = True
tick(w, c)
check('lost claim race: no fire', w.fires == [])

w = World()
w.fire_status = 429
tick(w, c)
check('failed fire posts one fire-failed comment', len(w.comments) == 1 and '· fire-failed' in w.comments[0][1])
tick(w, c)
check('failed fire is not retried for the same brief', len(w.fires) == 1 and len(w.comments) == 1)

w = World()
w.issues[T]['labels'] = {'nodes': []}
tick(w, c)
check('ticket without ai-design: no fire', w.fires == [])

w = World()
tick(w, c, dry=True)
check('dry run fires nothing, tags nothing, comments nothing', w.fires == [] and w.refs == {} and w.comments == [])

# --- collect: one comment per result ---
w = World()
tick(w, c)
k = key_for(w)
push_result(w, k, ready_doc(k))
tick(w, c)
check('ready result posts one comment', len(w.comments) == 1)
body = w.comments[0][1] if w.comments else ''
check('comment links the canvas', f']({CANVAS})' in body)
check('comment mentions the reviewer', 'https://linear.app/wemod/profiles/shanshan ready for your review' in body)
check('comment says not approved', 'not approved for production' in body)
check('comment carries limitations', 'Review verdict Revise' in body)
check('comment strips agent links', 'evil.example' not in body)
check('comment links the run log', 'https://claude.ai/code/session_1' in body)
check('comment has the result marker', f'design-run:{k} · result' in body)
tick(w, c)
check('redelivery does not duplicate', len(w.comments) == 1)

for name, doc, files, ahead in [
    ('extra file in the branch', None, ['results/K.json', '.github/workflows/x.yml'], 1),
    ('two commits on the branch', None, None, 2),
    ('baseline canvas', {'canvas_url': 'https://claude.ai/artifact/HsTPER1L2A6ctC87FrquQs'}, None, 1),
    ('ready without a canvas', {'canvas_url': None}, None, 1),
    ('wrong contract', {'contract': 'other'}, None, 1),
    ('run key mismatch', {'run_key': f'{T}-0000000000000000'}, None, 1),
    ('non-English text', {'summary': '设计已完成'}, None, 1),
]:
    w = World()
    tick(w, c)
    k = key_for(w)
    files = [f.replace('K', k) for f in files] if files else None
    push_result(w, k, ready_doc(k, **(doc or {})), files, ahead)
    tick(w, c)
    check(f'rejects result: {name}', w.comments == [])

w = World()
k = key_for(w)
push_result(w, k, ready_doc(k))
tick(w, c, dry=True)
check('result without a claim is ignored', w.comments == [])

w = World()
k2 = key_for(w, OTHER)
w.refs[f'refs/tags/design-claim/{k2}'] = 'x'
push_result(w, k2, ready_doc(k2, ticket=OTHER))
tick(w, c, dry=True)
check('result for a non-allowlisted ticket is never read or posted', w.comments == [] and OTHER not in w.read)

w = World()
tick(w, c)
k = key_for(w)
push_result(w, k, ready_doc(k, status='failed', canvas_url=None, summary='The gate never opened.'))
tick(w, c)
check('failed result posts an honest failure', len(w.comments) == 1 and "couldn't finish" in w.comments[0][1]
      and 'claude.ai/artifact' not in w.comments[0][1])

# --- sweep: runs that never report back ---
w = World()
tick(w, c)
w.age_claims(c['result_timeout_minutes'] - 5)
tick(w, c)
check('no timeout before the limit', w.comments == [])
w.age_claims(10)
tick(w, c)
check('timeout posts once', len(w.comments) == 1 and '· timeout' in w.comments[0][1])
tick(w, c)
check('timeout not repeated', len(w.comments) == 1)
k = key_for(w)
push_result(w, k, ready_doc(k))
tick(w, c)
check('a late result still posts after a timeout', len(w.comments) == 2 and '· result' in w.comments[1][1])

# --- auth header: personal key bare, OAuth app token as Bearer ---
check('personal key sent bare', bridge.Linear('lin_api_abc', True).key == 'lin_api_abc')
check('OAuth app token sent as Bearer', bridge.Linear('oauth-token-abc', True).key == 'Bearer oauth-token-abc')

# --- the comment refuses off-allowlist tickets even if called directly ---
w = World()
bridge.http = w.http
try:
    bridge.Linear('k', False).comment(w.issues[OTHER], 'x', c)
    check('comment refused off the allowlist', False)
except bridge.BridgeError:
    check('comment refused off the allowlist', w.comments == [])

# --- report_result.py (dry run) ---
REPORT = os.path.join(ROOT, 'tools', 'report_result.py')
GS = '/tmp/routine-probe-guard-state.json'
saved = open(GS).read() if os.path.exists(GS) else None
with tempfile.TemporaryDirectory() as d:
    summ = os.path.join(d, 'summary.md')
    lims = os.path.join(d, 'limitations.md')
    open(summ, 'w').write('A question-led page.')
    open(lims, 'w').write('- Verdict Revise\n- No RDR2 media\n')
    run = lambda *a: subprocess.run([sys.executable, '-I', REPORT, '--ticket', T, '--summary-file', summ,
                                     '--limitations-file', lims, '--dry-run', *a], capture_output=True, text=True)
    k = f'{T}-0123456789abcdef'
    json.dump({'created_url': None, 'fills': 0}, open(GS, 'w'))
    check('report refuses ready without a canvas', run('--run-key', k, '--status', 'ready').returncode == 1)
    r = run('--run-key', k, '--status', 'failed')
    check('report allows failed without a canvas', r.returncode == 0 and '"canvas_url": null' in r.stdout)
    json.dump({'created_url': CANVAS, 'fills': 0}, open(GS, 'w'))
    check('report refuses ready before any publish', run('--run-key', k, '--status', 'ready').returncode == 1)
    json.dump({'created_url': CANVAS, 'fills': 3}, open(GS, 'w'))
    r = run('--run-key', k, '--status', 'ready')
    doc = json.loads(r.stdout.split('\ngit ')[0]) if r.returncode == 0 else {}
    check('report takes the canvas from the guard', doc.get('canvas_url') == CANVAS)
    check('report document validates in the bridge', bridge.validate_result(doc, k, c) == [])
    check('report pushes only to its result branch', f'HEAD:refs/heads/claude/design-result-{k}' in r.stdout)
    check('report refuses a run key for another ticket', run('--run-key', f'{OTHER}-0123456789abcdef', '--status', 'failed').returncode == 1)
if saved is None:
    os.remove(GS)
else:
    open(GS, 'w').write(saved)

print(f'{passed} passed, {failed} failed')
sys.exit(1 if failed else 0)
