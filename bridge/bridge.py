#!/usr/bin/env python3
# Linear -> Claude Code routine -> Linear bridge (V1). Runs from main on a GitHub Actions schedule; one tick does:
#   1. collect: results the routine pushed to claude/design-result-<run_key> -> ONE comment on that run's ticket
#   2. sweep:   runs that never reported back within result_timeout_minutes -> ONE "didn't finish" comment
#   3. poll:    allowlisted tickets carrying the ai-design label -> claim the brief version, fire the routine
#
#   python3 -I bridge/bridge.py tick [--dry-run]
#
# Env: LINEAR_API_KEY (claude@wand.com; Read + Create comments, Product team only), ROUTINE_FIRE_URL,
# ROUTINE_FIRE_TOKEN, GH_TOKEN (the workflow's GITHUB_TOKEN: contents write for claim tags), GITHUB_REPOSITORY.
# Secrets are only ever sent as headers; nothing here prints a header, a token or a response body.
#
# Safety: tickets outside bridge/config.json allowed_tickets are never read, fired or commented on. The only Linear
# mutation is commentCreate. A claim is an annotated tag design-claim/<run_key>, created atomically before the fire, so
# one brief version (title + description) is fired at most once, even when ticks overlap or a fire fails. A result
# is accepted only from a branch whose single commit changes only results/<run_key>.json, for a run_key that was
# claimed here, and the comment text is built here from validated fields (agent text has its links removed).
import base64
import calendar
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
LINEAR_URL = 'https://api.linear.app/graphql'
GITHUB_API = 'https://api.github.com'
CONTRACT = 'wemod-design-result/v1'
CLAIM = 'design-claim/'
FIRED = 'design-fired/'
CANVAS = re.compile(r'^https://claude\.ai/artifact/[A-Za-z0-9]{10,40}$')
# Never a result canvas: V0, the Design type, the Test B and Test C baselines, Test B's empty first canvas.
NOT_RESULT = {'KE3kJTKgBbXwSgvaaJkrLE', 'QKN21svewxgyPb6SYRqWnd', '6fgFWVXxWpzfaBSzKXFqNX', 'HsTPER1L2A6ctC87FrquQs',
              '5nhZgCLcSgKcpt2gKSSFuJ'}
TICKET = re.compile(r'^[A-Z][A-Z0-9]{1,9}-[0-9]{1,6}$')
RUN_KEY = re.compile(r'^([A-Z][A-Z0-9]{1,9}-[0-9]{1,6})-([0-9a-f]{16})$')
URL = re.compile(r'https?://\S+')
CJK = re.compile(r'[぀-ヿ㐀-鿿가-힯]')

ISSUE_QUERY = '''query DesignBridgeIssue($id: String!) {
  issue(id: $id) {
    id identifier title description url
    state { type }
    labels(first: 50) { nodes { id name } }
    creator { id name }
    comments(first: 100) { nodes { id body user { id } } }
  }
}'''
COMMENT_CREATE = '''mutation DesignBridgeComment($issueId: String!, $body: String!) {
  commentCreate(input: { issueId: $issueId, body: $body }) { success comment { id url } }
}'''


class BridgeError(Exception):
    pass


def load_config(path=os.path.join(HERE, 'config.json')):
    with open(path) as f:
        cfg = json.load(f)
    for t in cfg['allowed_tickets']:
        if not TICKET.match(t):
            raise BridgeError(f'bad ticket id in allowlist: {t!r}')
    return cfg


# ---- pure contract logic (tested in tests/bridge_test.py) ----

def fingerprint(title, description):
    return hashlib.sha256(f'{title}\n{description or ""}'.encode()).hexdigest()[:16]


def run_key(ticket, fp):
    return f'{ticket}-{fp}'


def marker(key, kind):
    return f'design-run:{key} · {kind}'


def has_marker(comments, key, kinds):
    return any(f'design-run:{key} · {k}' in (c.get('body') or '') for c in comments for k in kinds)


def eligible(issue, cfg):
    """(True, '') when the ticket carries the trigger label (ai-design, by id) and has a brief; else (False, why)."""
    if issue['identifier'] not in cfg['allowed_tickets']:
        return False, 'not on the allowlist'
    label = cfg['trigger_label']
    if label['id'] not in {l['id'] for l in (issue.get('labels') or {}).get('nodes', [])}:
        return False, f'no {label["name"]} label'
    if (issue.get('state') or {}).get('type') in ('completed', 'canceled'):
        return False, 'ticket is closed'
    if len((issue.get('description') or '').strip()) < 40:
        return False, 'the description has no brief'
    return True, ''


def fire_text(issue, key):
    desc = issue.get('description') or ''
    head = (f'Linear design brief\nticket: {issue["identifier"]}\nrun_key: {key}\ntitle: {issue["title"]}\n'
            f'url: {issue["url"]}\nrequested_by: {(issue.get("creator") or {}).get("name", "unknown")}\n'
            f'--- description (the brief) ---\n')
    return head + desc[:60000 - len(head)]


def clean_text(s, limit):
    """Agent-written text for a comment: no links, no markers, no mentions, bounded."""
    s = URL.sub('[link removed]', s or '')
    s = s.replace('design-run:', 'design run ').replace('linear.app/', 'linear app/')
    s = s.strip()
    return s if len(s) <= limit else s[:limit - 1].rstrip() + '…'


def validate_result(doc, branch_key, cfg):
    """Errors (strings) for a result document read from claude/design-result-<branch_key>."""
    errs = []
    if not isinstance(doc, dict):
        return ['result is not a JSON object']
    if doc.get('contract') != CONTRACT:
        errs.append(f'contract is not {CONTRACT}')
    if doc.get('run_key') != branch_key:
        errs.append('run_key does not match the branch')
    m = RUN_KEY.match(branch_key or '')
    if not m:
        errs.append('branch run key is malformed')
    elif doc.get('ticket') != m.group(1):
        errs.append('ticket does not match the run key')
    if doc.get('ticket') not in cfg['allowed_tickets']:
        errs.append('ticket is not on the allowlist')
    status = doc.get('status')
    if status not in ('ready', 'failed'):
        errs.append('status must be ready or failed')
    url = doc.get('canvas_url')
    if status == 'ready':
        if not isinstance(url, str) or not CANVAS.match(url) or url.rsplit('/', 1)[-1] in NOT_RESULT:
            errs.append('a ready result needs a new claude.ai canvas URL')
    elif url not in (None, ''):
        errs.append('a failed result has no canvas')
    if not isinstance(doc.get('summary'), str) or not doc['summary'].strip():
        errs.append('summary is missing')
    lims = doc.get('limitations', [])
    if not isinstance(lims, list) or len(lims) > 8 or not all(isinstance(x, str) for x in lims):
        errs.append('limitations must be a list of at most 8 strings')
    for field in [doc.get('summary') or '', doc.get('canvas_title') or ''] + [x for x in lims if isinstance(x, str)]:
        if CJK.search(field):
            errs.append('comment text must be English')
            break
    return errs


def compose_result(doc, issue, cfg, session_url):
    who = cfg['reviewer']['profile_url']
    summary = clean_text(doc['summary'], 1200)
    lims = [clean_text(x, 300) for x in doc.get('limitations', []) if x.strip()]
    run = f' · [run log]({session_url})' if session_url else ''
    if doc['status'] == 'ready':
        title = clean_text(doc.get('canvas_title') or 'Design canvas', 120).replace(']', ')').replace('[', '(')
        lines = [f'First design exploration is ready for **{issue["title"]}**.', '', summary, '',
                 f'**Design:** [{title}]({doc["canvas_url"]}) — desktop (1440) and mobile (390) on one Claude Design '
                 'canvas, built with WeMod Web V0 and the WeMod Page Designer skill.']
        if lims:
            lines += ['', '**Open questions and limitations**'] + [f'- {x}' for x in lims]
        lines += ['', 'This is an exploration for review, not approved for production.', '',
                  f'{who} ready for your review!', '', f'_{marker(doc["run_key"], "result")}{run}_']
    else:
        lines = [f"I couldn't finish the design exploration for **{issue['title']}**.", '', summary]
        if lims:
            lines += [''] + [f'- {x}' for x in lims]
        lines += ['', "No canvas came out of this run, so there's nothing to review yet. To retry, edit the brief "
                  '(title or description); the same brief is never run twice.', '', f'{who} for a look.', '',
                  f'_{marker(doc["run_key"], "result")}{run}_']
    return '\n'.join(lines)


def compose_timeout(issue, key, cfg, minutes, session_url):
    run = f' · [run log]({session_url})' if session_url else ''
    return '\n'.join([f"The design run for **{issue['title']}** hasn't reported back after {minutes} minutes, so "
                      "I'm treating it as not finished. No canvas is attached.", '',
                      'To retry, edit the brief (title or description).', '',
                      f'{cfg["reviewer"]["profile_url"]} for a look.', '', f'_{marker(key, "timeout")}{run}_'])


def compose_fire_failed(issue, key, cfg, why):
    return '\n'.join([f"I couldn't start the design run for **{issue['title']}** ({why}). No design was started.", '',
                      'To retry, edit the brief (title or description).', '',
                      f'{cfg["reviewer"]["profile_url"]} for a look.', '', f'_{marker(key, "fire-failed")}_'])


# ---- transports ----

def http(method, url, headers, body=None, timeout=30):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={**headers, 'User-Agent': 'design-bridge'})
    if data is not None:
        req.add_header('Content-Type', 'application/json')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b'null')
        except Exception:
            return e.code, None


class Linear:
    def __init__(self, key, dry):
        self.key, self.dry = key, dry

    def _call(self, doc, variables):
        status, body = http('POST', LINEAR_URL, {'Authorization': self.key}, {'query': doc, 'variables': variables})
        if status != 200 or not body or body.get('errors'):
            msg = ((body or {}).get('errors') or [{}])[0].get('message', '')
            raise BridgeError(f'Linear HTTP {status} {msg[:120]}')
        return body['data']

    def issue(self, ticket):
        issue = self._call(ISSUE_QUERY, {'id': ticket})['issue']
        if not issue or issue['identifier'] != ticket:
            raise BridgeError(f'Linear did not return {ticket}')
        return issue

    def comment(self, issue, body, cfg):
        if issue['identifier'] not in cfg['allowed_tickets']:
            raise BridgeError(f'refusing to comment on {issue["identifier"]}: not on the allowlist')
        if self.dry:
            print(f'[dry-run] would comment on {issue["identifier"]}:\n{body}\n')
            return 'dry-run'
        r = self._call(COMMENT_CREATE, {'issueId': issue['id'], 'body': body})['commentCreate']
        if not r['success']:
            raise BridgeError('commentCreate reported failure')
        return r['comment']['url']


class GitHub:
    def __init__(self, token, repo, dry):
        self.h = {'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json',
                  'X-GitHub-Api-Version': '2022-11-28'}
        self.repo, self.dry = repo, dry

    def get(self, path):
        return http('GET', f'{GITHUB_API}/repos/{self.repo}/{path}', self.h)

    def refs(self, prefix):
        status, body = self.get(f'git/matching-refs/{prefix}')
        if status != 200:
            raise BridgeError(f'GitHub refs HTTP {status}')
        return [r['ref'] for r in body]

    def tag(self, name):
        """{'message': dict, 'date': epoch} for an annotated tag, or None."""
        status, ref = self.get(f'git/ref/tags/{name}')
        if status == 404:
            return None
        if status != 200 or ref['object']['type'] != 'tag':
            raise BridgeError(f'GitHub tag {name} HTTP {status}')
        status, t = self.get(f'git/tags/{ref["object"]["sha"]}')
        if status != 200:
            raise BridgeError(f'GitHub tag object HTTP {status}')
        try:
            msg = json.loads(t['message'])
        except Exception:
            msg = {}
        return {'message': msg, 'date': calendar.timegm(time.strptime(t['tagger']['date'], '%Y-%m-%dT%H:%M:%SZ'))}

    def create_tag(self, name, message):
        """True if created; False if it already exists (the claim belongs to someone else)."""
        if self.dry:
            print(f'[dry-run] would create tag {name}')
            return True
        status, main = self.get('git/ref/heads/main')
        if status != 200:
            raise BridgeError(f'GitHub main HTTP {status}')
        status, t = http('POST', f'{GITHUB_API}/repos/{self.repo}/git/tags', self.h,
                         {'tag': name, 'message': json.dumps(message), 'object': main['object']['sha'], 'type': 'commit'})
        if status != 201:
            raise BridgeError(f'GitHub tag object create HTTP {status}')
        status, _ = http('POST', f'{GITHUB_API}/repos/{self.repo}/git/refs', self.h,
                         {'ref': f'refs/tags/{name}', 'sha': t['sha']})
        if status == 422:
            return False
        if status != 201:
            raise BridgeError(f'GitHub tag ref create HTTP {status}')
        return True

    def result(self, branch, key):
        """The result document on branch, or raise if the branch changes anything but results/<key>.json."""
        status, cmp_ = self.get(f'compare/main...{branch}')
        if status != 200:
            raise BridgeError(f'GitHub compare HTTP {status}')
        files = [f['filename'] for f in cmp_.get('files', [])]
        if cmp_.get('ahead_by') != 1 or files != [f'results/{key}.json']:
            raise BridgeError(f'{branch} must add exactly one commit touching only results/{key}.json (got {files})')
        status, c = self.get(f'contents/results/{key}.json?ref={branch}')
        if status != 200 or c.get('size', 0) > 20000:
            raise BridgeError(f'GitHub result content HTTP {status}')
        return json.loads(base64.b64decode(c['content']))


def fire(url, token, text):
    if not re.match(r'^https://api\.anthropic\.com/v1/claude_code/routines/trig_[A-Za-z0-9]+/fire$', url or ''):
        raise BridgeError('ROUTINE_FIRE_URL is not a routine fire URL')
    status, body = http('POST', url, {'Authorization': f'Bearer {token}', 'anthropic-version': '2026-10-21'},
                        {'text': text}, timeout=60)
    if status != 200 or not body or body.get('type') != 'routine_fire':
        err = ((body or {}).get('error') or {}).get('type', 'no error type')
        raise BridgeError(f'routine fire HTTP {status} ({err})')
    return {'session_id': body['claude_code_session_id'], 'session_url': body['claude_code_session_url']}


# ---- the tick ----

def session_url(gh, key):
    t = gh.tag(FIRED + key)
    return (t or {}).get('message', {}).get('session_url')


def collect(cfg, lin, gh):
    for ref in gh.refs('heads/' + cfg['result_branch_prefix']):
        branch = ref[len('refs/heads/'):]
        key = branch[len(cfg['result_branch_prefix']):]
        m = RUN_KEY.match(key)
        if not m or m.group(1) not in cfg['allowed_tickets']:
            print(f'collect: ignoring {branch} (not an allowlisted run key)')
            continue
        if not gh.tag(CLAIM + key):
            print(f'collect: ignoring {branch} (no claim: this bridge never started {key})')
            continue
        issue = lin.issue(m.group(1))
        if has_marker(issue['comments']['nodes'], key, ['result']):
            print(f'collect: {key} already delivered')
            continue
        try:
            doc = gh.result(branch, key)
        except (BridgeError, ValueError) as e:
            print(f'collect: rejecting {branch}: {e}')
            continue
        errs = validate_result(doc, key, cfg)
        if errs:
            print(f'collect: rejecting {branch}: {"; ".join(errs)}')
            continue
        url = lin.comment(issue, compose_result(doc, issue, cfg, session_url(gh, key)), cfg)
        print(f'collect: {key} {doc["status"]} -> {url}')


def sweep(cfg, lin, gh, now):
    limit = cfg['result_timeout_minutes']
    for ticket in cfg['allowed_tickets']:
        claims = [r[len('refs/tags/' + CLAIM):] for r in gh.refs(f'tags/{CLAIM}{ticket}-')]
        if not claims:
            continue
        issue = lin.issue(ticket)
        for key in claims:
            if has_marker(issue['comments']['nodes'], key, ['result', 'timeout', 'fire-failed']):
                continue
            claim = gh.tag(CLAIM + key)
            if claim and now - claim['date'] > limit * 60:
                url = lin.comment(issue, compose_timeout(issue, key, cfg, limit, session_url(gh, key)), cfg)
                print(f'sweep: {key} timed out -> {url}')


def poll(cfg, lin, gh, fire_url, fire_token):
    for ticket in cfg['allowed_tickets']:
        issue = lin.issue(ticket)
        ok, why = eligible(issue, cfg)
        if not ok:
            print(f'poll: {ticket} not queued ({why})')
            continue
        key = run_key(ticket, fingerprint(issue['title'], issue['description']))
        if has_marker(issue['comments']['nodes'], key, ['result', 'timeout', 'fire-failed']) or gh.tag(CLAIM + key):
            print(f'poll: {ticket} brief version {key} was already run')
            continue
        if not gh.create_tag(CLAIM + key, {'ticket': ticket, 'claimed_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}):
            print(f'poll: {key} was claimed by another tick')
            continue
        if gh.dry:
            print(f'[dry-run] would fire the routine for {key} with {len(fire_text(issue, key))} chars of brief')
            continue
        try:
            fired = fire(fire_url, fire_token, fire_text(issue, key))
        except BridgeError as e:
            print(f'poll: {key} fire failed: {e}')
            lin.comment(issue, compose_fire_failed(issue, key, cfg, str(e)), cfg)
            continue
        gh.create_tag(FIRED + key, fired)
        print(f'poll: fired {key} -> {fired["session_id"]}')


def main(argv):
    if not argv or argv[0] != 'tick':
        print('usage: bridge.py tick [--dry-run]', file=sys.stderr)
        return 2
    dry = '--dry-run' in argv
    cfg = load_config()
    if not cfg['allowed_tickets']:
        print('No allowlisted tickets; nothing to do.')
        return 0
    env = os.environ
    for k in ('LINEAR_API_KEY', 'GH_TOKEN', 'GITHUB_REPOSITORY') + (() if dry else ('ROUTINE_FIRE_URL', 'ROUTINE_FIRE_TOKEN')):
        if not env.get(k, '').strip():
            raise BridgeError(f'{k} is not set')
    lin = Linear(env['LINEAR_API_KEY'].strip(), dry)
    gh = GitHub(env['GH_TOKEN'].strip(), env['GITHUB_REPOSITORY'], dry)
    failed = False
    for step in (lambda: collect(cfg, lin, gh), lambda: sweep(cfg, lin, gh, time.time()),
                 lambda: poll(cfg, lin, gh, env.get('ROUTINE_FIRE_URL'), env.get('ROUTINE_FIRE_TOKEN'))):
        try:
            step()
        except BridgeError as e:  # one failing step never stops the others
            print(f'error: {e}')
            failed = True
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
