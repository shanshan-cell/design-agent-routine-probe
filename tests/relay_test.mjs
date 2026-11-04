// Offline tests for relay/worker.js: signed and unsigned deliveries, label transitions, result pushes.
//   node tests/relay_test.mjs
import { createHmac } from 'node:crypto';
import { handle } from '../relay/worker.js';

const env = {
  LINEAR_WEBHOOK_SECRET: 'lin-secret', GITHUB_WEBHOOK_SECRET: 'gh-secret', GITHUB_DISPATCH_TOKEN: 'ghp_test',
  REPO: 'owner/repo', WORKFLOW: 'linear-design-bridge.yml',
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

r = await run(new Request('https://relay.example/linear', { method: 'GET' }));
check('GET: 404', r.status === 404);
r = await run(new Request('https://relay.example/other', { method: 'POST', body: '{}' }));
check('unknown path: 404', r.status === 404);

console.log(`${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
