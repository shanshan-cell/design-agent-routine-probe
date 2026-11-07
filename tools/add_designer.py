#!/usr/bin/env python3
# Onboard a teammate to the Linear design bridge (run by the repository owner, on a Mac, with gh signed in).
#
#   python3 tools/add_designer.py invite <github-username>
#       Invites them to this repository with write access. Their routine pushes its result branch here, and the
#       setup plugin (/plugin marketplace add shanshan-cell/design-agent-routine-probe) is read from here.
#   python3 tools/add_designer.py add --email name@wemod.com --name "Name" --fire-url https://api.anthropic.com/...
#       Copy their routine token from 1Password to the clipboard first. Stores it as the repository secret
#       ROUTINE_TOKEN_<NAME> (straight from the clipboard to gh; it is never printed), adds them to
#       bridge/designers.json, and commits and pushes that file to main.
#   python3 tools/add_designer.py remove --email name@wemod.com
#       Removes them from bridge/designers.json and deletes their secret. Their routine stays in their account.
import argparse
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DESIGNERS = os.path.join(ROOT, 'bridge', 'designers.json')
FIRE_URL = re.compile(r'^https://api\.anthropic\.com/v1/claude_code/routines/trig_[A-Za-z0-9]+/fire$')
EMAIL = re.compile(r'^[a-z0-9._+-]+@[a-z0-9.-]+\.[a-z]{2,}$')
TOKEN = re.compile(r'^sk-ant-oat01-[A-Za-z0-9_-]{40,200}$')


def run(*cmd, **kw):
    return subprocess.run(cmd, check=True, cwd=ROOT, **kw)


def repo():
    return run('gh', 'repo', 'view', '--json', 'nameWithOwner', '-q', '.nameWithOwner',
               capture_output=True, text=True).stdout.strip()


def secret_name(email):
    return 'ROUTINE_TOKEN_' + re.sub(r'[^A-Z0-9]+', '_', email.split('@')[0].upper()).strip('_')


def save(doc, message):
    with open(DESIGNERS, 'w') as f:
        f.write(json.dumps(doc, indent=2) + '\n')
    run('git', 'add', 'bridge/designers.json')
    run('git', 'commit', '-q', '-m', message)
    run('git', 'push', '-q', 'origin', 'HEAD:main')


def main(argv):
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest='cmd', required=True)
    i = sub.add_parser('invite')
    i.add_argument('github_username')
    a = sub.add_parser('add')
    a.add_argument('--email', required=True)
    a.add_argument('--name', required=True)
    a.add_argument('--fire-url', required=True)
    r = sub.add_parser('remove')
    r.add_argument('--email', required=True)
    args = p.parse_args(argv)

    if args.cmd == 'invite':
        if not re.match(r'^[A-Za-z0-9-]{1,39}$', args.github_username):
            sys.exit('not a GitHub username')
        run('gh', 'api', '-X', 'PUT', f'repos/{repo()}/collaborators/{args.github_username}', '-f', 'permission=push',
            '--silent')
        print(f'Invited {args.github_username} (write access). They accept the email from GitHub, then run the setup.')
        return 0

    email = args.email.strip().lower()
    if not EMAIL.match(email):
        sys.exit('not an email address')
    with open(DESIGNERS) as f:
        doc = json.load(f)

    if args.cmd == 'remove':
        d = doc['designers'].pop(email, None)
        if not d:
            sys.exit(f'{email} is not in bridge/designers.json')
        if d['token_secret'] != 'ROUTINE_FIRE_TOKEN':
            run('gh', 'secret', 'delete', d['token_secret'])
        save(doc, f'Design bridge: remove {d["name"]}')
        print(f'Removed {d["name"]}. Their routine stays in their account; they can delete it at claude.ai/code/routines.')
        return 0

    if not FIRE_URL.match(args.fire_url.strip()):
        sys.exit('not a routine fire URL (https://api.anthropic.com/v1/claude_code/routines/trig_.../fire)')
    token = subprocess.run(['pbpaste'], capture_output=True, text=True, check=True).stdout.strip()
    if not TOKEN.match(token):
        # Shape only: never print the clipboard.
        sys.exit(f'the clipboard does not hold a routine token (length {len(token)}, '
                 f'{"one line" if chr(10) not in token else "several lines"}). Copy it from 1Password and retry.')
    name = secret_name(email)
    run('gh', 'secret', 'set', name, input=token, text=True, capture_output=True)
    del token
    doc['designers'][email] = {'name': args.name.strip(), 'fire_url': args.fire_url.strip(), 'token_secret': name}
    save(doc, f'Design bridge: add {args.name.strip()}')
    print(f'Added {args.name.strip()} ({email}): secret {name} set, designers.json pushed to main.')
    print('Clear the clipboard now (copy something else). Their ai-design tickets fire from the next tick.')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
