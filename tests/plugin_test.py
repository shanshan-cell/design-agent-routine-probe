#!/usr/bin/env python3
# The setup plugin creates routines that match the bridge: same prompt stub as prompts/routine-stub.md, same model,
# repository and tools as the reference routine, a fire URL shape the bridge accepts.
#   python3 -I tests/plugin_test.py
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
sys.path.insert(0, os.path.join(ROOT, 'bridge'))
import add_designer  # noqa: E402
import bridge  # noqa: E402

passed = failed = 0


def check(name, cond):
    global passed, failed
    passed += bool(cond)
    failed += not cond
    if not cond:
        print(f'FAIL {name}')


skill = open(os.path.join(ROOT, 'plugins/wemod-design-routine/skills/setup/SKILL.md')).read()
body = json.loads(re.search(r'```json\n(.*?)\n```', skill, re.S).group(1))
stub = open(os.path.join(ROOT, 'prompts/routine-stub.md')).read().split('-->', 1)[1].strip()
ccr = body['job_config']['ccr']
check('the skill creates the stub prompt', ccr['events'][0]['data']['message']['content'] == stub)
check('the stub checks the guard first', 'ROUTINE-PROBE-GUARD-v5' in stub and 'prompts/linear-design.md' in stub)
check('model', ccr['session_context']['model'] == 'claude-opus-5-5')
check('repository', ccr['session_context']['sources'] == [{'git_repository': {'url': 'https://github.com/shanshan-cell/design-agent-routine-probe'}}])
check('no connectors', body['clear_mcp_connections'] is True and 'mcp_connections' not in body)
check('created off', body['enabled'] is False)
check('no recurring schedule', 'cron_expression' not in body and body['run_once_at'].startswith('2030-'))
check('the prompt file still has STEP 1 the stub points at', 'STEP 1 - load the skill' in open(os.path.join(ROOT, 'prompts/linear-design.md')).read())
check('secret names fit the bridge', bridge.SECRET_NAME.match(add_designer.secret_name('anna.lee@wemod.com')) is not None
      and add_designer.secret_name('anna.lee@wemod.com') == 'ROUTINE_TOKEN_ANNA_LEE')
check('the token shape matches a real routine token', add_designer.TOKEN.match('sk-ant-oat01-' + 'a' * 80) is not None
      and not add_designer.TOKEN.match('sk-ant-api03-' + 'a' * 80))
check('the skill never runs the routine', '"run"' not in skill.replace('{action: "run"}', ''))
print(f'{passed} passed, {failed} failed')
sys.exit(1 if failed else 0)
