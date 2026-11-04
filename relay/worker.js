// Webhook relay for the Linear design bridge (Cloudflare Worker, no dependencies).
// It never fires the routine, reads tickets or writes to Linear. It only starts one live tick of the existing
// bridge workflow (bridge/bridge.py on main), which keeps every check: allowlist, ai-design label by id, one claim
// per brief version, result validation, one comment per run.
//
//   POST /linear  Linear webhook (Issue events, Product team). Starts a tick when ai-design is newly on an issue.
//   POST /github  GitHub repository webhook (push). Starts a tick when the routine pushes claude/design-result-*.
//   cron :17      Cloudflare Cron Trigger, hourly. Starts a tick so timeouts are reported without any webhook event.
//
// Both routes verify the sender's HMAC-SHA256 signature over the raw body; Linear deliveries older than 60 s are
// refused (replay). Anything else gets 2xx with "ignored" so the sender doesn't retry, or 401 for a bad signature.
//
// Env (Worker secrets): LINEAR_WEBHOOK_SECRET, GITHUB_WEBHOOK_SECRET, GITHUB_DISPATCH_TOKEN (fine-grained,
// Actions: read and write on the bridge repository only). Vars: REPO, WORKFLOW, AI_DESIGN_LABEL_ID, TEAM_ID.

const enc = new TextEncoder();

async function hmacHex(secret, body) {
  if (typeof secret !== 'string' || secret.length < 16) return null; // unset secret: refuse every delivery
  const key = await crypto.subtle.importKey('raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const sig = new Uint8Array(await crypto.subtle.sign('HMAC', key, enc.encode(body)));
  return [...sig].map((b) => b.toString(16).padStart(2, '0')).join('');
}

function sameText(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string' || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

/** True when this Linear event means "ai-design was just put on an issue in the team". */
export function labelAdded(event, env) {
  if (event?.type !== 'Issue' || !['create', 'update'].includes(event.action)) return false;
  const data = event.data ?? {};
  if (data.teamId !== env.TEAM_ID) return false;
  const now = Array.isArray(data.labelIds) && data.labelIds.includes(env.AI_DESIGN_LABEL_ID);
  if (!now) return false;
  if (event.action === 'create') return true;
  const before = event.updatedFrom?.labelIds;
  return Array.isArray(before) && !before.includes(env.AI_DESIGN_LABEL_ID);
}

/** True when this GitHub push created or updated a routine result branch. */
export function resultPushed(event, headers) {
  return headers.get('x-github-event') === 'push' && typeof event?.ref === 'string'
    && event.ref.startsWith('refs/heads/claude/design-result-') && !event.deleted;
}

async function dispatch(env, why, fetchImpl) {
  const r = await fetchImpl(`https://api.github.com/repos/${env.REPO}/actions/workflows/${env.WORKFLOW}/dispatches`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${env.GITHUB_DISPATCH_TOKEN}`,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
      'User-Agent': 'design-bridge-relay',
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ ref: 'main', inputs: { mode: 'live' } }),
  });
  console.log(`dispatch (${why}): HTTP ${r.status}`);
  return r.status === 204;
}

export async function handle(request, env, fetchImpl = fetch, now = Date.now()) {
  const path = new URL(request.url).pathname;
  if (request.method !== 'POST' || !['/linear', '/github'].includes(path)) return new Response('not found', { status: 404 });
  const body = await request.text();
  if (body.length > 1_000_000) return new Response('too large', { status: 413 });

  if (path === '/linear') {
    const want = await hmacHex(env.LINEAR_WEBHOOK_SECRET, body);
    if (!want || !sameText(request.headers.get('linear-signature') ?? '', want)) {
      return new Response('bad signature', { status: 401 });
    }
    const event = JSON.parse(body);
    if (Math.abs(now - Number(event.webhookTimestamp)) > 60_000) return new Response('stale', { status: 401 });
    if (!labelAdded(event, env)) return new Response('ignored');
    return (await dispatch(env, `linear ${event.data.identifier ?? event.data.id}`, fetchImpl))
      ? new Response('tick started') : new Response('dispatch failed', { status: 502 });
  }

  const sig = request.headers.get('x-hub-signature-256') ?? '';
  const want = await hmacHex(env.GITHUB_WEBHOOK_SECRET, body);
  if (!want || !sameText(sig, `sha256=${want}`)) return new Response('bad signature', { status: 401 });
  const event = JSON.parse(body);
  if (!resultPushed(event, request.headers)) return new Response('ignored');
  return (await dispatch(env, `github ${event.ref}`, fetchImpl))
    ? new Response('tick started') : new Response('dispatch failed', { status: 502 });
}

/** Hourly Cron Trigger: one tick, so runs that never came back get their timeout comment without waiting for a webhook.
 *  Safe to repeat: the bridge fires a brief version at most once (claim tags) and posts one comment per run. */
export async function scheduled(env, fetchImpl = fetch) {
  if (!(await dispatch(env, 'hourly cron', fetchImpl))) throw new Error('dispatch failed');
}

export default {
  fetch: (request, env) => handle(request, env),
  scheduled: (controller, env) => scheduled(env),
};
