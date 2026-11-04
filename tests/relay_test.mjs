// Offline tests for relay/worker.js: signed and unsigned deliveries, label transitions, result pushes.
//   node tests/relay_test.mjs
import { createHmac } from 'node:crypto';
import { handle, scheduled, fingerprint, survey } from '../relay/worker.js';

const env = {
  LINEAR_WEBHOOK_SECRET: 'lin-secret-0123456789', GITHUB_WEBHOOK_SECRET: 'gh-secret-0123456789', GITHUB_DISPATCH_TOKEN: 'ghp_test',
  REPO: 'owner/repo', RELAY_ENABLED: 'on', LINEAR_READ_KEY: 'lin_api_read', IGNORE_TICKETS: 'WAND-8583', WORKFLOW: 'linear-design-bridge.yml',
  AI_DESIGN_LABEL_ID: '56a3977a-dd58-4cec-a0aa-9522df1f27fb', TEAM_ID: '3b01e73d-6636-4ff9-9f8a-c758f4d806ef',
};
const NOW = 1793750000000;
let passed = 0, failed = 0;
const check = (name, cond) => { if (cond) passed++; else { failed++; console.log(`FAIL ${name}`); } };

function fakeFetch(status = 204) {
  const calls = [];
  const f = async (url, init) => { calls.push({ url, init }); return { status }; };
  f.calls = calls;
  return f;
}
const sign = (secret, body) => createHmac('sha256', secret).update(body).digest('hex');
const linearReq = (event, { secret = env.LINEAR_WEBHOOK_SECRET, sig } = {}) => {
  const body = JSON.stringify(event);
  return new Request('https://relay.example/linear', { method: 'POST', body, headers: { 'linear-signature': sig ?? sign(secret, body) } });
};
const githubReq = (event, { secret = env.GITHUB_WEBHOOK_SECRET, kind = 'push' } = {}) => {
  const body = JSON.stringify(event);
  return new Request('https://relay.example/github', { method: 'POST', body,
    headers: { 'x-hub-signature-256': `sha256=${sign(secret, body)}`, 'x-github-event': kind } });
};
const issue = (over = {}) => ({
  type: 'Issue', action: 'update', webhookTimestamp: NOW,
  data: { id: 'i1', identifier: 'WAND-8583', teamId: env.TEAM_ID, labelIds: [env.AI_DESIGN_LABEL_ID] },
  updatedFrom: { labelIds: [] }, ...over,
});

async function run(req, f = fakeFetch()) { const r = await handle(req, env, f, NOW); return { status: r.status, text: await r.text(), calls: f.calls }; }

let r = await run(linearReq(issue()));
check('label added: one dispatch', r.status === 200 && r.calls.length === 1);
const d = r.calls[0] ?? { url: '', init: { body: '{}', headers: {} } };
check('dispatches the bridge workflow on main in live mode', d.url === 'https://api.github.com/repos/owner/repo/actions/workflows/linear-design-bridge.yml/dispatches'
  && JSON.parse(d.init.body).ref === 'main' && JSON.parse(d.init.body).inputs.mode === 'live');
check('dispatch uses the token as Bearer', d.init.headers.Authorization === 'Bearer ghp_test');

r = await run(linearReq(issue({ action: 'create', updatedFrom: undefined })));
check('issue created with the label: dispatch', r.calls.length === 1);
r = await run(linearReq(issue({ updatedFrom: { labelIds: [env.AI_DESIGN_LABEL_ID] } })));
check('label already there (other edit): ignored', r.text === 'ignored' && r.calls.length === 0);
r = await run(linearReq(issue({ updatedFrom: { title: 'old' } })));
check('labels unchanged: ignored', r.calls.length === 0);
r = await run(linearReq(issue({ data: { ...issue().data, labelIds: ['other'] } })));
check('label removed or absent: ignored', r.calls.length === 0);
r = await run(linearReq(issue({ data: { ...issue().data, labelIds: ['claude-analysis-id'] } })));
check('Data team label: ignored', r.calls.length === 0);
r = await run(linearReq(issue({ data: { ...issue().data, teamId: 'another-team' } })));
check('another team: ignored', r.calls.length === 0);
r = await run(linearReq({ ...issue(), type: 'Comment' }));
check('comment events: ignored', r.calls.length === 0);
r = await run(linearReq(issue(), { secret: 'wrong' }));
check('bad Linear signature: 401, no dispatch', r.status === 401 && r.calls.length === 0);
r = await run(linearReq(issue(), { sig: '' }));
check('missing Linear signature: 401', r.status === 401 && r.calls.length === 0);
r = await run(linearReq(issue({ webhookTimestamp: NOW - 120_000 })));
check('stale Linear delivery: 401', r.status === 401 && r.calls.length === 0);
r = await run(linearReq(issue()), fakeFetch(403));
check('dispatch refused: 502 so Linear retries', r.status === 502);

r = await run(githubReq({ ref: 'refs/heads/claude/design-result-WAND-8583-f7224aab3565022d', deleted: false }));
check('result branch pushed: one dispatch', r.status === 200 && r.calls.length === 1);
r = await run(githubReq({ ref: 'refs/heads/main', deleted: false }));
check('push to main: ignored', r.calls.length === 0);
r = await run(githubReq({ ref: 'refs/heads/claude/design-result-X', deleted: true }));
check('result branch deleted: ignored', r.calls.length === 0);
r = await run(githubReq({ ref: 'refs/heads/claude/design-result-X' }, { kind: 'create' }));
check('non-push GitHub event: ignored', r.calls.length === 0);
r = await run(githubReq({ ref: 'refs/heads/claude/design-result-X' }, { secret: 'wrong' }));
check('bad GitHub signature: 401', r.status === 401 && r.calls.length === 0);

for (const [name, secretVar, req] of [
  ['Linear', 'LINEAR_WEBHOOK_SECRET', () => linearReq(issue(), { secret: 'undefined' })],
  ['GitHub', 'GITHUB_WEBHOOK_SECRET', () => githubReq({ ref: 'refs/heads/claude/design-result-X' }, { secret: 'undefined' })],
]) {
  const f = fakeFetch();
  const res = await handle(req(), { ...env, [secretVar]: undefined }, f, NOW);
  check(`${name} secret not set: 401, even when signed with "undefined"`, res.status === 401 && f.calls.length === 0);
}

r = await run(new Request('https://relay.example/linear', { method: 'GET' }));
check('GET: 404', r.status === 404);
r = await run(new Request('https://relay.example/other', { method: 'POST', body: '{}' }));
check('unknown path: 404', r.status === 404);

// --- polling: fingerprints match bridge.fingerprint (values computed with bridge/bridge.py) ---
check('fingerprint matches the bridge', await fingerprint('Game page', 'A brief with ünïcode — and more text here to pass forty chars') === 'ab4980f872f8eac1');
check('fingerprint of an empty description matches the bridge', await fingerprint('T', null) === '678f81a714fbc720');

const BRIEF = 'Design a game discovery page for players looking for mods. '.repeat(2);
const fp = await fingerprint('Discovery', BRIEF);
const ticket = (id, comments = [], over = {}) => ({ identifier: id, title: 'Discovery', description: BRIEF,
  comments: { nodes: comments.map((body) => ({ body })) }, ...over });
let sv = await survey([ticket('WAND-1')]);
check('new brief: waiting', sv.waiting.join() === 'WAND-1' && sv.inFlight.length === 0);
sv = await survey([ticket('WAND-1', [`_design-run:WAND-1-${fp} · started_`])]);
check('started: not waiting, in flight', sv.waiting.length === 0 && sv.inFlight.join() === `WAND-1-${fp}`);
sv = await survey([ticket('WAND-1', [`_design-run:WAND-1-${fp} · started_`, `_design-run:WAND-1-${fp} · result · [run log](x)_`])]);
check('result posted: nothing waiting or in flight', sv.waiting.length === 0 && sv.inFlight.length === 0);
sv = await survey([ticket('WAND-1', [`_design-run:WAND-1-0000000000000000 · result_`])]);
check('edited brief (new fingerprint): waiting again', sv.waiting.join() === 'WAND-1');
sv = await survey([ticket('WAND-1', [`_design-run:WAND-1-${fp} · not-started_`])]);
check('not started (guest or daily limit): not waiting', sv.waiting.length === 0 && sv.inFlight.length === 0);
sv = await survey([ticket('WAND-1', [], { description: 'tbd' })]);
check('no brief: not waiting', sv.waiting.length === 0);
sv = await survey([ticket('WAND-8583')], ['WAND-8583']);
check('ignored ticket: not waiting', sv.waiting.length === 0);

function world(issues, dispatchStatus = 204) {
  const calls = [];
  const f = async (url, init) => {
    calls.push({ url, init });
    if (url === 'https://api.linear.app/graphql') return { status: 200, json: async () => ({ data: { issues: { nodes: issues } } }) };
    return { status: dispatchStatus };
  };
  f.calls = calls;
  f.dispatches = () => calls.filter((c) => c.url.startsWith('https://api.github.com/'));
  return f;
}
const AT = (minute) => Date.UTC(2026, 10, 4, 15, minute);
let f = world([ticket('WAND-1')]);
let out = await scheduled(AT(20), env, f);
check('cron: waiting brief starts one live tick', f.dispatches().length === 1 && JSON.parse(f.dispatches()[0].init.body).inputs.mode === 'live');
check('cron: reads Linear with the read key, bare', f.calls[0].init.headers.Authorization === 'lin_api_read');
check('cron: says why', out.includes('new brief: WAND-1'));
f = world([ticket('WAND-1', [`_design-run:WAND-1-${fp} · started_`])]);
await scheduled(AT(20), env, f);
check('cron: run in flight, not the hourly slot: no tick', f.dispatches().length === 0);
await scheduled(AT(16), env, f);
check('cron: run in flight at :16: one tick', f.dispatches().length === 1);
f = world([]);
await scheduled(AT(16), env, f);
check('cron: nothing labeled: no tick, even hourly', f.dispatches().length === 0);
f = world([ticket('WAND-1')]);
await scheduled(AT(20), { ...env, RELAY_ENABLED: 'off' }, f);
check('kill switch: no Linear read, no tick', f.calls.length === 0);
await scheduled(AT(20), { ...env, RELAY_ENABLED: undefined }, f);
check('kill switch unset counts as off', f.calls.length === 0);
f = world([ticket('WAND-1')], 403);
check('cron: refused dispatch throws so Cloudflare logs a failure', await scheduled(AT(20), env, f).then(() => false, () => true));
f = world([ticket('WAND-1')]);
r = await (async () => { const res = await handle(githubReq({ ref: 'refs/heads/claude/design-result-X' }), { ...env, RELAY_ENABLED: 'off' }, f, NOW); return { status: res.status, text: await res.text() }; })();
check('kill switch: webhooks dispatch nothing', r.text === 'relay is off' && f.calls.length === 0);

console.log(`${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
