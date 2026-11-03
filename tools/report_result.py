#!/usr/bin/env python3
# The routine's completion contract (wemod-design-result/v1). Run ONCE as the last step of a Linear design run:
#   python3 tools/report_result.py --ticket WAND-123 --run-key WAND-123-<16 hex> --status ready|failed \
#       --summary-file <scratchpad>/result/summary.md [--limitations-file <scratchpad>/result/limitations.md] \
#       [--title "<canvas title>"]
# Writes results/<run_key>.json and pushes it as the only commit on claude/design-result-<run_key>; the bridge
# (bridge/bridge.py, on a schedule from main) validates it and posts the Linear comment. This script never talks to
# Linear. The canvas URL is never an argument: a ready result takes it from the guard's own record of the one
# canvas this session created (and refuses if the guard saw no publish to it).
#   --dry-run  print the document and the git commands without writing or pushing
import argparse
import json
import os
import re
import subprocess
import sys
import time

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GUARD_STATE = '/tmp/routine-probe-guard-state.json'
DONE = '/tmp/routine-design-result-reported'
CONTRACT = 'wemod-design-result/v1'
RUN_KEY = re.compile(r'^([A-Z][A-Z0-9]{1,9}-[0-9]{1,6})-([0-9a-f]{16})$')


def fail(msg):
    print(f'report_result: {msg}', file=sys.stderr)
    sys.exit(1)


def read_text(path, limit):
    if not path:
        return ''
    with open(path) as f:
        s = f.read().strip()
    if len(s) > limit:
        fail(f'{path} is longer than {limit} characters')
    return s


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--ticket', required=True)
    ap.add_argument('--run-key', required=True)
    ap.add_argument('--status', required=True, choices=['ready', 'failed'])
    ap.add_argument('--summary-file', required=True)
    ap.add_argument('--limitations-file')
    ap.add_argument('--title', default='')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()

    m = RUN_KEY.match(a.run_key)
    if not m or m.group(1) != a.ticket:
        fail('run key must be <ticket>-<16 hex> from the fire payload, for this ticket')
    if os.path.exists(DONE) and not a.dry_run:
        fail('a result was already reported in this session')
    try:
        with open(GUARD_STATE) as f:
            state = json.load(f)
    except Exception:
        state = {}
    canvas = state.get('created_url')
    if a.status == 'ready':
        if not canvas:
            fail('status ready, but the guard recorded no created canvas')
        if int(state.get('fills', 0)) < 1:
            fail('status ready, but the guard saw no publish to the canvas')
    summary = read_text(a.summary_file, 1200)
    if not summary:
        fail('the summary is empty')
    lims = [re.sub(r'^\s*[-*]\s*', '', x).strip() for x in read_text(a.limitations_file, 2400).splitlines()]
    lims = [x for x in lims if x][:8]
    doc = {
        'contract': CONTRACT,
        'ticket': a.ticket,
        'run_key': a.run_key,
        'status': a.status,
        'canvas_url': canvas if a.status == 'ready' else None,
        'canvas_title': a.title[:120],
        'summary': summary,
        'limitations': lims,
        'session_id': os.environ.get('CLAUDE_CODE_REMOTE_SESSION_ID', ''),
        'reported_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
    }
    rel = f'results/{a.run_key}.json'
    branch = f'claude/design-result-{a.run_key}'
    ident = ['-c', 'user.name=WeMod design routine', '-c', 'user.email=noreply@anthropic.com']
    cmds = [
        ['git', 'checkout', '-B', branch, 'origin/main'],
        ['git', 'add', '--', rel],
        ['git', *ident, 'commit', '-m', f'Design result {a.run_key} ({a.status})', '--', rel],
        ['git', 'push', '--force', 'origin', f'HEAD:refs/heads/{branch}'],
    ]
    if a.dry_run:
        print(json.dumps(doc, indent=2))
        print('\n'.join(' '.join(c) for c in cmds))
        return
    subprocess.run(['git', 'fetch', 'origin', 'main'], cwd=PROJECT, check=True)
    subprocess.run(cmds[0], cwd=PROJECT, check=True)
    os.makedirs(os.path.join(PROJECT, 'results'), exist_ok=True)
    with open(os.path.join(PROJECT, rel), 'w') as f:
        json.dump(doc, f, indent=2)
        f.write('\n')
    for c in cmds[1:]:
        subprocess.run(c, cwd=PROJECT, check=True)
    open(DONE, 'w').close()
    print(f'reported {a.status} for {a.run_key} on {branch}' + (f': {canvas}' if canvas else ''))


if __name__ == '__main__':
    main()
