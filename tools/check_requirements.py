#!/usr/bin/env python3
# Checks requirements/wemod-page-requirements.md R1-R3 on a canvas's page boards.
#   python3 -I tools/check_requirements.py --desktop <Page-1440.dc.html> --phone <Page-390.dc.html> [--blobs <dir>]
# --blobs: a folder of the canvas's assets saved by id (<id>.<ext>); every /_blob/<id> a board references is then
# hashed and compared with the denylist. Without it, R3 checks text and denied V0 ids only.
# Exit 0 when every check passes, 1 otherwise. The guard imports check_board() for publishes of the page boards.
import argparse
import glob
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DENYLIST = os.path.join(HERE, '..', 'requirements', 'v0-asset-denylist.json')
BRAND_LINE = 'WeMod by Wand'
PC_LINE = re.compile(r'visit us on your\s+(?:<[^>]+>\s*)*PC(?:\s*</[^>]+>)*\s+to download the app', re.I)
PHONE_ACTION = re.compile(r'https://www\.wemod\.com/cheats(?:/red-dead-redemption-2-trainers)?/?["\'#?]')
PHONE_DOWNLOAD = re.compile(r'wemod\.com/download|data-app-download-button|Free download|Download for Windows', re.I)
BLOB = re.compile(r'/_blob/([0-9a-f]{32})')


def load_denylist(path=DENYLIST):
    with open(path) as f:
        return json.load(f)


def strip_comments(src):
    return re.sub(r'<!--.*?-->', '', src, flags=re.S)


def check_board(src, role, deny, blob_dir=None):
    """Failures (strings) for one board. role is 'desktop' or 'phone'."""
    src = strip_comments(src)
    fails = []
    if BRAND_LINE not in src:
        fails.append(f'R1 {role}: "{BRAND_LINE}" does not appear')
    if role == 'phone':
        m = PHONE_DOWNLOAD.search(src)
        if m:
            fails.append(f'R2 phone: offers a download ({m.group(0)!r})')
        pc = PC_LINE.search(src)
        if not pc:
            fails.append('R2 phone: the verified line "…or visit us on your PC to download the app" is missing')
        elif not PHONE_ACTION.search(src, pc.end()):
            fails.append('R2 phone: no link to the game page or all games after the PC line')
    for word in deny.get('unverified_text', []):
        if re.search(r'(?<![\w-])' + re.escape(word) + r'(?![\w-])', src):
            fails.append(f'R3 {role}: names {word!r}')
    denied_sha = {v['sha256']: v['name'] for v in deny['denied'].values() if v.get('sha256')}
    for blob in sorted(set(BLOB.findall(src))):
        if blob in deny['denied']:
            fails.append(f'R3 {role}: uses denied V0 asset {deny["denied"][blob]["name"]}')
        elif blob_dir:
            files = glob.glob(os.path.join(blob_dir, blob + '*'))
            if files:
                with open(files[0], 'rb') as f:
                    sha = hashlib.sha256(f.read()).hexdigest()
                if sha in denied_sha:
                    fails.append(f'R3 {role}: uses {denied_sha[sha]} (as {blob})')
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--desktop', required=True)
    ap.add_argument('--phone', required=True)
    ap.add_argument('--blobs')
    a = ap.parse_args()
    deny = load_denylist()
    fails = []
    for role, path in (('desktop', a.desktop), ('phone', a.phone)):
        with open(path, errors='replace') as f:
            fails += check_board(f.read(), role, deny, a.blobs)
    for line in fails:
        print('FAIL', line)
    print('REQUIREMENTS PASS' if not fails else f'REQUIREMENTS FAIL ({len(fails)})')
    sys.exit(0 if not fails else 1)


if __name__ == '__main__':
    main()
