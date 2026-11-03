#!/usr/bin/env python3
# Checks tools/check_requirements.py against compliant fixtures and the two baselines' boards.
#   python3 -I tests/check_requirements_test.py
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'tools'))
import check_requirements as cr  # noqa: E402

FIX = os.path.join(HERE, 'fixtures')
deny = cr.load_denylist()


def fails(name, role):
    with open(os.path.join(FIX, name), errors='replace') as f:
        return cr.check_board(f.read(), role, deny)


def has(found, prefix):
    return any(f.startswith(prefix) for f in found)


cases = [
    # (name, board, role, expectation, test)
    ('compliant desktop', 'Page-1440.ok.dc.html', 'desktop', 'no failures', lambda f: not f),
    ('compliant phone', 'Page-390.ok.dc.html', 'phone', 'no failures', lambda f: not f),
    ('Test C desktop', 'testc-Main.dc.html', 'desktop', 'R1 fails (no "WeMod by Wand")', lambda f: has(f, 'R1 desktop')),
    ('Test C phone', 'testc-Mobile-390.dc.html', 'phone', 'R1 and R2 fail (download offered, no PC line)',
        lambda f: has(f, 'R1 phone') and has(f, 'R2 phone: offers a download') and has(f, 'R2 phone: the verified line')),
    ('Test C phone', 'testc-Mobile-390.dc.html', 'phone', 'R3 fails (sample "Your Game" capture)', lambda f: has(f, "R3 phone: names 'Your Game'")),
    ('manual desktop', 'manual-Main.dc.html', 'desktop', 'R1 passes (has the brand line)', lambda f: not has(f, 'R1')),
    ('manual phone', 'manual-Phone-390.dc.html', 'phone', 'R2 fails (download offered)', lambda f: has(f, 'R2 phone: offers a download')),
    ('desktop rules', 'testc-Main.dc.html', 'desktop', 'desktop keeps its download (no R2 on 1440)', lambda f: not has(f, 'R2')),
]
ok = True
for label, name, role, want, test in cases:
    found = fails(name, role)
    passed = test(found)
    ok &= passed
    print(f'{"PASS" if passed else "FAIL"} {label:18} {want:52} {"; ".join(found)[:120]}')

# A denied V0 asset referenced by its V0 id is caught without --blobs.
src = '<x-dc>WeMod by Wand <img src="/_blob/a28d89f37662030333cfc8f64265118b"></x-dc>'
passed = has(cr.check_board(src, 'desktop', deny), 'R3 desktop: uses denied V0 asset')
ok &= passed
print(f'{"PASS" if passed else "FAIL"} {"denied V0 id":18} {"R3 fails on the store-orbit art":52}')
# The PC line split by inline markup still counts; an action before it does not.
src = '<x-dc>WeMod by Wand <a href="https://www.wemod.com/cheats">x</a> …or visit us on your <strong>PC</strong> to download the app</x-dc>'
passed = cr.check_board(src, 'phone', deny) == ['R2 phone: no link to the game page or all games after the PC line']
ok &= passed
print(f'{"PASS" if passed else "FAIL"} {"phone order":18} {"R2 needs the action after the PC line":52}')
print('ALL PASS' if ok else 'SOME FAILED')
sys.exit(0 if ok else 1)
