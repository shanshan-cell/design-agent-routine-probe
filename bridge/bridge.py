#!/usr/bin/env python3
# Linear -> Claude Code routine -> Linear bridge (V1). Runs from main when the relay (relay/worker.js) dispatches the
# workflow; one tick does:
#   1. collect: results the routine pushed to claude/design-result-<run_key> -> ONE comment on that run's ticket
#   2. sweep:   runs that never reported back within result_timeout_minutes -> ONE "didn't finish" comment
#   3. poll:    open Product tickets carrying the ai-design label -> claim the brief version, fire the routine, post
#               ONE "started" comment with the GitHub run and Claude session links
#
#   python3 -I bridge/bridge.py tick [--dry-run]
#
# Env: LINEAR_API_KEY (Linear OAuth app token, client credentials, scopes read + comments:create), ROUTINE_TOKENS
# (JSON object of repository secrets; only the ROUTINE_* names that bridge/designers.json points at are used),
# GH_TOKEN (the workflow's GITHUB_TOKEN: contents write for claim tags), GITHUB_REPOSITORY,
# DESIGN_BRIDGE_FIRING (kill switch: a routine is fired only when it is exactly "on").
#
# Each teammate has their own routine in their own Claude account (set up with the wemod-design-routine plugin), so
# the canvas is theirs. bridge/designers.json maps a Linear email to that routine's fire URL and the name of the
# repository secret holding its token. The requester is whoever added the ai-design label (else the ticket creator);
# a requester without a routine gets one "needs-setup" comment, and the run starts on a later tick once they're added.
# Secrets are only ever sent as headers; nothing here prints a header, a token or a response body.
#
# Safety: only open tickets in the configured team that carry the ai-design label (by id) and were requested by a full,
# active workspace member are fired; ignore_tickets are never fired again. At most max_fires_per_day claims per 24 h
# (max_fires_per_person_per_day for one requester) and max_in_flight unfinished runs. The only Linear mutation is commentCreate, and only on tickets of the configured
# team. A claim is an annotated tag design-claim/<run_key>, created atomically before the fire, so
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
FIRE_URL = re.compile(r'^https://api\.anthropic\.com/v1/claude_code/routines/trig_[A-Za-z0-9]+/fire$')
SECRET_NAME = re.compile(r'^ROUTINE_[A-Z0-9_]{1,60}$')
SETUP_DAYS = 7  # a needs-setup ticket is retried hourly (relay) for this long
TICKET = re.compile(r'^[A-Z][A-Z0-9]{1,9}-[0-9]{1,6}$')
RUN_KEY = re.compile(r'^([A-Z][A-Z0-9]{1,9}-[0-9]{1,6})-([0-9a-f]{16})$')
URL = re.compile(r'https?://\S+')
CJK = re.compile(r'[぀-ヿ㐀-鿿가-힯]')

ISSUE_FIELDS = '''id identifier title description url
    team { id }
    state { type }
    labels(first: 50) { nodes { id name } }
    creator { id name email url guest active }
    history(first: 100) { nodes { createdAt addedLabelIds actor { id name email url guest active } } }
    comments(first: 100, filter: { body: { contains: "design-run:" } }) { nodes { id body createdAt user { id } } }'''
ISSUE_QUERY = '''query DesignBridgeIssue($id: String!) {
  issue(id: $id) { %s }
}''' % ISSUE_FIELDS
QUEUE_QUERY = '''query DesignBridgeQueue($team: ID!, $label: ID!) {
  issues(first: 25, filter: { team: { id: { eq: $team } }, labels: { id: { eq: $label } },
                              state: { type: { nin: ["completed", "canceled"] } } }) { nodes { %s } }
}''' % ISSUE_FIELDS
# Kinds of marker comment that end a run (no more comments for that run_key, except a late result after a timeout).
DONE = ['result', 'timeout', 'fire-failed', 'not-started']
COMMENT_CREATE = '''mutation DesignBridgeComment($issueId: String!, $body: String!) {
  commentCreate(input: { issueId: $issueId, body: $body }) { success comment { id url } }
}'''


class BridgeError(Exception):
    pass


def load_config(path=os.path.join(HERE, 'config.json')):
    with open(path) as f:
        cfg = json.load(f)
    for t in cfg['ignore_tickets']:
        if not TICKET.match(t):
            raise BridgeError(f'bad ticket id in ignore_tickets: {t!r}')
    return cfg


def load_designers(path=os.path.join(HERE, 'designers.json')):
    """{lowercase Linear email: {'name', 'fire_url', 'token_secret'}}."""
    with open(path) as f:
        designers = json.load(f)['designers']
    out = {}
    for email, d in designers.items():
        if not FIRE_URL.match(d.get('fire_url', '')) or not SECRET_NAME.match(d.get('token_secret', '')):
            raise BridgeError(f'bad designers.json entry for {email!r}')
        out[email.strip().lower()] = d
    return out


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
    if (issue.get('team') or {}).get('id') != cfg['team']['id']:
        return False, f'not a {cfg["team"]["name"]} ticket'
    if issue['identifier'] in cfg['ignore_tickets']:
        return False, 'on ignore_tickets'
    label = cfg['trigger_label']
    if label['id'] not in {l['id'] for l in (issue.get('labels') or {}).get('nodes', [])}:
        return False, f'no {label["name"]} label'
    if (issue.get('state') or {}).get('type') in ('completed', 'canceled'):
        return False, 'ticket is closed'
    if len((issue.get('description') or '').strip()) < 40:
        return False, 'the description has no brief'
    return True, ''


def requester(issue, cfg):
    """Who asked for the design: the person who last added the trigger label, else the ticket's creator."""
    adds = [h for h in (issue.get('history') or {}).get('nodes', [])
            if h.get('actor') and cfg['trigger_label']['id'] in (h.get('addedLabelIds') or [])]
    if adds:
        return max(adds, key=lambda h: h.get('createdAt') or '')['actor']
    return issue.get('creator')


def requester_ok(issue, cfg):
    """(True, '') when a full, active workspace member asked for the run; else (False, why) for the comment."""
    who = requester(issue, cfg)
    if not who:
        return False, "the ticket has no human creator (it came from an integration)"
    if who.get('guest') or not who.get('active', True):
        return False, 'only full workspace members can request a design run'
    return True, ''


def reviewer_url(issue, cfg):
    """The requester gets the review mention; the configured reviewer if they have no profile."""
    return (requester(issue, cfg) or {}).get('url') or cfg['reviewer']['profile_url']


def routine_for(issue, cfg, designers):
    """The requester's designers.json entry, or None when they have no routine set up yet."""
    return designers.get(((requester(issue, cfg) or {}).get('email') or '').strip().lower())


def iso_epoch(s):
    """Epoch seconds for a Linear timestamp (2026-11-06T12:00:00.000Z); 0 when missing."""
    return calendar.timegm(time.strptime(s[:19], '%Y-%m-%dT%H:%M:%S')) if s else 0


def session_link(url):
    """The fire API answers .../code/cse_<id>; the session opens at .../code/session_<id>."""
    return re.sub(r'^(https://claude\.ai/code/)cse_', r'\1session_', url or '')


def fire_text(issue, key, cfg):
    desc = issue.get('description') or ''
    head = (f'Linear design brief\nticket: {issue["identifier"]}\nrun_key: {key}\ntitle: {issue["title"]}\n'
            f'url: {issue["url"]}\nrequested_by: {(requester(issue, cfg) or {}).get("name", "unknown")}\n'
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
    who = reviewer_url(issue, cfg)
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
                      f'{reviewer_url(issue, cfg)} for a look.', '', f'_{marker(key, "timeout")}{run}_'])


def compose_fire_failed(issue, key, cfg, why):
    return '\n'.join([f"I couldn't start the design run for **{issue['title']}** ({why}). No design was started.", '',
                      'To retry, edit the brief (title or description).', '',
                      f'{reviewer_url(issue, cfg)} for a look.', '', f'_{marker(key, "fire-failed")}_'])


def compose_started(issue, key, fired, run_url):
    links = ' · '.join(x for x in [f'[GitHub run]({run_url})' if run_url else '',
                                   f'[Claude session]({fired["session_url"]})'] if x)
    return '\n'.join([f'Design run started for **{issue["title"]}**. The canvas will be posted here when it\'s ready, '
                      'usually in 20 to 40 minutes.', '', links, '', f'_{marker(key, "started")}_'])


def compose_needs_setup(issue, key, cfg):
    who = requester(issue, cfg) or {}
    return '\n'.join([f"Design runs use the requester's own Claude account, and {who.get('name', 'yours')} isn't set up "
                      'yet, so nothing has started.', '',
                      f'To get set up (about 10 minutes, once), ask {cfg["reviewer"]["name"]} for an invite to the '
                      'design routine. Once you\'re added, this ticket starts by itself within an hour. You don\'t '
                      f'need to change it. It waits {SETUP_DAYS} days.', '', f'_{marker(key, "needs-setup")}_'])


def compose_not_started(issue, key, why, retry):
    return '\n'.join([f"I didn't start a design run for **{issue['title']}**: {why}.", '', retry, '',
                      f'_{marker(key, "not-started")}_'])


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
        # A personal key (lin_api_…) is sent bare; an OAuth app token (client credentials, actor app) as Bearer.
        self.key = key if key.startswith('lin_api_') else f'Bearer {key}'
        self.dry = dry

    def _call(self, doc, variables):
        status, body = http('POST', LINEAR_URL, {'Authorization': self.key}, {'query': doc, 'variables': variables})
        if status != 200 or not body or body.get('errors'):
            msg = ((body or {}).get('errors') or [{}])[0].get('message', '')
            raise BridgeError(f'Linear HTTP {status} {msg[:120]}')
        return body['data']

    def queue(self, cfg):
        """Open tickets of the configured team with the trigger label (by id)."""
        return self._call(QUEUE_QUERY, {'team': cfg['team']['id'], 'label': cfg['trigger_label']['id']})['issues']['nodes']

    def issue(self, ticket):
        issue = self._call(ISSUE_QUERY, {'id': ticket})['issue']
        if not issue or issue['identifier'] != ticket:
            raise BridgeError(f'Linear did not return {ticket}')
        return issue

    def comment(self, issue, body, cfg):
        if (issue.get('team') or {}).get('id') != cfg['team']['id']:
            raise BridgeError(f'refusing to comment on {issue["identifier"]}: not a {cfg["team"]["name"]} ticket')
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
        self._tags = {}  # annotated tags never change, so a found one is read once per tick

    def get(self, path):
        return http('GET', f'{GITHUB_API}/repos/{self.repo}/{path}', self.h)

    def refs(self, prefix):
        status, body = self.get(f'git/matching-refs/{prefix}')
        if status != 200:
            raise BridgeError(f'GitHub refs HTTP {status}')
        return [r['ref'] for r in body]

    def tag(self, name):
        """{'message': dict, 'date': epoch} for an annotated tag, or None."""
        if name in self._tags:
            return self._tags[name]
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
        self._tags[name] = {'message': msg, 'date': calendar.timegm(time.strptime(t['tagger']['date'], '%Y-%m-%dT%H:%M:%SZ'))}
        return self._tags[name]

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
    if not FIRE_URL.match(url or ''):
        raise BridgeError('not a routine fire URL')
    status, body = http('POST', url, {'Authorization': f'Bearer {token}', 'anthropic-version': '2026-10-21'},
                        {'text': text}, timeout=60)
    if status != 200 or not body or body.get('type') != 'routine_fire':
        err = ((body or {}).get('error') or {}).get('type', 'no error type')
        raise BridgeError(f'routine fire HTTP {status} ({err})')
    return {'session_id': body['claude_code_session_id'], 'session_url': session_link(body['claude_code_session_url'])}


# ---- the tick ----

def session_url(gh, key):
    t = gh.tag(FIRED + key)
    return session_link((t or {}).get('message', {}).get('session_url'))


class Issues:
    """Linear issues read at most once per tick."""

    def __init__(self, lin):
        self.lin, self.seen = lin, {}

    def get(self, ticket):
        if ticket not in self.seen:
            self.seen[ticket] = self.lin.issue(ticket)
        return self.seen[ticket]


def claims(gh):
    """[(run_key, claimed_at epoch)] for every claim tag."""
    out = []
    for ref in gh.refs('tags/' + CLAIM):
        key = ref[len('refs/tags/' + CLAIM):]
        t = gh.tag(CLAIM + key) if RUN_KEY.match(key) else None
        if t:
            out.append((key, t['date']))
    return out


def collect(cfg, lin, gh, issues):
    for ref in gh.refs('heads/' + cfg['result_branch_prefix']):
        branch = ref[len('refs/heads/'):]
        key = branch[len(cfg['result_branch_prefix']):]
        m = RUN_KEY.match(key)
        if not m:
            print(f'collect: ignoring {branch} (not a run key)')
            continue
        if not gh.tag(CLAIM + key):
            print(f'collect: ignoring {branch} (no claim: this bridge never started {key})')
            continue
        issue = issues.get(m.group(1))
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


def sweep(cfg, lin, gh, issues, now):
    limit = cfg['result_timeout_minutes']
    for key, claimed in claims(gh):
        # Runs older than a day past the limit were swept by an earlier tick; don't re-read their tickets forever.
        if not limit * 60 < now - claimed < (limit + 24 * 60) * 60:
            continue
        issue = issues.get(RUN_KEY.match(key).group(1))
        if has_marker(issue['comments']['nodes'], key, DONE):
            continue
        url = lin.comment(issue, compose_timeout(issue, key, cfg, limit, session_url(gh, key)), cfg)
        print(f'sweep: {key} timed out -> {url}')


def usage(cfg, gh, issues, now):
    """(claims in the last 24 h, runs still in flight, {requester email: claims in the last 24 h})."""
    today = in_flight = 0
    per_person = {}
    for key, claimed in claims(gh):
        age = now - claimed
        today += age < 24 * 3600
        if age < 24 * 3600:
            who = gh.tag(CLAIM + key)['message'].get('requester')
            if who:
                per_person[who] = per_person.get(who, 0) + 1
        if age < cfg['result_timeout_minutes'] * 60:
            issue = issues.get(RUN_KEY.match(key).group(1))
            in_flight += not has_marker(issue['comments']['nodes'], key, DONE)
    return today, in_flight, per_person


def poll(cfg, lin, gh, issues, designers, tokens, firing, run_url, now):
    used = None
    for issue in lin.queue(cfg):
        ticket = issue['identifier']
        issues.seen[ticket] = issue
        ok, why = eligible(issue, cfg)
        if not ok:
            print(f'poll: {ticket} not queued ({why})')
            continue
        key = run_key(ticket, fingerprint(issue['title'], issue['description']))
        if has_marker(issue['comments']['nodes'], key, DONE + ['started']) or gh.tag(CLAIM + key):
            print(f'poll: {ticket} brief version {key} was already run')
            continue
        if not firing and not gh.dry:
            print(f'poll: {key} is waiting; firing is off (repo variable DESIGN_BRIDGE_FIRING is not "on")')
            continue
        ok, why = requester_ok(issue, cfg)
        if not ok:
            lin.comment(issue, compose_not_started(issue, key, why, 'Ask a full workspace member to add the label.'), cfg)
            print(f'poll: {key} not started ({why})')
            continue
        routine = routine_for(issue, cfg, designers)
        waited = [iso_epoch(c.get('createdAt')) for c in issue['comments']['nodes']
                  if marker(key, 'needs-setup') in (c.get('body') or '')]
        if routine and waited and now - min(waited) > SETUP_DAYS * 86400:
            print(f'poll: {key} waited for setup more than {SETUP_DAYS} days; edit the brief to run it')
            continue
        if not routine:
            if not has_marker(issue['comments']['nodes'], key, ['needs-setup']):
                lin.comment(issue, compose_needs_setup(issue, key, cfg), cfg)
            print(f'poll: {key} waits: {(requester(issue, cfg) or {}).get("name")} has no routine in designers.json')
            continue
        email = requester(issue, cfg)['email'].strip().lower()
        used = used or list(usage(cfg, gh, issues, now))
        if used[1] >= cfg['max_in_flight']:
            print(f'poll: {key} waits: {used[1]} runs in flight (max {cfg["max_in_flight"]})')
            continue
        if used[0] >= cfg['max_fires_per_day']:
            lin.comment(issue, compose_not_started(
                issue, key, f'the daily limit of {cfg["max_fires_per_day"]} design runs is used up',
                'To retry later, edit the brief (title or description).'), cfg)
            print(f'poll: {key} not started (daily limit)')
            continue
        if used[2].get(email, 0) >= cfg['max_fires_per_person_per_day']:
            lin.comment(issue, compose_not_started(
                issue, key, f'{routine["name"]} has used today\'s {cfg["max_fires_per_person_per_day"]} design runs',
                'To retry tomorrow, edit the brief (title or description).'), cfg)
            print(f'poll: {key} not started (personal daily limit)')
            continue
        token = tokens.get(routine['token_secret'], '').strip()
        if not token and not gh.dry:
            print(f'poll: {key} waits: secret {routine["token_secret"]} for {routine["name"]} is not set')
            continue
        if not gh.create_tag(CLAIM + key, {'ticket': ticket, 'requester': email,
                                           'claimed_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}):
            print(f'poll: {key} was claimed by another tick')
            continue
        used[0] += 1
        used[1] += 1
        used[2][email] = used[2].get(email, 0) + 1
        if gh.dry:
            print(f'[dry-run] would fire {routine["name"]}\'s routine for {key} with '
                  f'{len(fire_text(issue, key, cfg))} chars of brief')
            continue
        try:
            fired = fire(routine['fire_url'], token, fire_text(issue, key, cfg))
        except BridgeError as e:
            print(f'poll: {key} fire failed: {e}')
            lin.comment(issue, compose_fire_failed(issue, key, cfg, str(e)), cfg)
            continue
        gh.create_tag(FIRED + key, fired)
        print(f'poll: fired {key} -> {fired["session_url"]}')
        print(f'poll: started comment -> {lin.comment(issue, compose_started(issue, key, fired, run_url), cfg)}')


def main(argv):
    if not argv or argv[0] != 'tick':
        print('usage: bridge.py tick [--dry-run]', file=sys.stderr)
        return 2
    dry = '--dry-run' in argv
    cfg = load_config()
    designers = load_designers()
    env = os.environ
    firing = env.get('DESIGN_BRIDGE_FIRING', '').strip() == 'on'
    for k in ('LINEAR_API_KEY', 'GH_TOKEN', 'GITHUB_REPOSITORY'):
        if not env.get(k, '').strip():
            raise BridgeError(f'{k} is not set')
    secrets = json.loads(env.get('ROUTINE_TOKENS') or '{}')
    tokens = {d['token_secret']: secrets.get(d['token_secret'], '') for d in designers.values()}
    del secrets
    lin = Linear(env['LINEAR_API_KEY'].strip(), dry)
    gh = GitHub(env['GH_TOKEN'].strip(), env['GITHUB_REPOSITORY'], dry)
    issues = Issues(lin)
    run_url = (f'{env["GITHUB_SERVER_URL"]}/{env["GITHUB_REPOSITORY"]}/actions/runs/{env["GITHUB_RUN_ID"]}'
               if env.get('GITHUB_SERVER_URL') and env.get('GITHUB_RUN_ID') else None)
    print(f'firing is {"on" if firing else "off"}; {len(designers)} designers, '
          f'{sum(1 for t in tokens.values() if t.strip())} with a token')
    failed = False
    for step in (lambda: collect(cfg, lin, gh, issues), lambda: sweep(cfg, lin, gh, issues, time.time()),
                 lambda: poll(cfg, lin, gh, issues, designers, tokens, firing, run_url, time.time())):
        try:
            step()
        except BridgeError as e:  # one failing step never stops the others
            print(f'error: {e}')
            failed = True
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
