// Relay for the Linear design bridge (Cloudflare Worker, no dependencies).
// It never fires the routine and never writes to Linear. It only starts one live tick of the existing bridge
// workflow (bridge/bridge.py on main), which keeps every check: Product team, ai-design label by id, full-member
// requester, one claim per brief version, daily and in-flight limits, the firing switch, one comment per run.
//
//   cron */2      Cloudflare Cron Trigger. Reads Linear (read-only key) and starts a tick when an open Product ticket
//                 with ai-design has a brief version the bridge hasn't answered yet; once an hour (:16) also while a
//                 run is in flight (results and timeouts without a webhook) or a ticket waits for its requester's
//                 routine to be set up (needs-setup, for 7 days).
//   POST /linear  Linear webhook (Issue events, Product team). Starts a tick when ai-design is newly on an issue.
//   POST /github  GitHub repository webhook (push). Starts a tick when the routine pushes claude/design-result-*.
//
// Kill switch: RELAY_ENABLED must be "on" (a dashboard variable, kept across deploys); otherwise nothing is dispatched.
//
// Both routes verify the sender's HMAC-SHA256 signature over the raw body; Linear deliveries older than 60 s are
// refused (replay). Anything else gets 2xx with "ignored" so the sender doesn't retry, or 401 for a bad signature.
//
// Env (Worker secrets): LINEAR_READ_KEY (Linear personal key, read only), LINEAR_WEBHOOK_SECRET, GITHUB_WEBHOOK_SECRET,
// GITHUB_DISPATCH_TOKEN (fine-grained, Actions: read and write on the bridge repository only).
// Vars: RELAY_ENABLED, REPO, WORKFLOW, AI_DESIGN_LABEL_ID, TEAM_ID, IGNORE_TICKETS (comma-separated).

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

// The bridge's comment markers: design-run:<ticket>-<fingerprint> · <kind>. Kinds after which a run is over:
const MARKER = /design-run:([A-Z][A-Z0-9]{1,9}-[0-9]{1,6}-[0-9a-f]{16}) · ([a-z-]+)/g;
const DONE = new Set(['result', 'timeout', 'fire-failed', 'not-started']);
const SETUP_WAIT_MS = 7 * 24 * 3600 * 1000; // same as bridge.SETUP_DAYS
const QUEUE = `query RelayQueue($team: ID!, $label: ID!) {
  issues(first: 25, filter: { team: { id: { eq: $team } }, labels: { id: { eq: $label } },
                              state: { type: { nin: ["completed", "canceled"] } } }) {
    nodes { identifier title description comments(first: 100, filter: { body: { contains: "design-run:" } }) { nodes { body createdAt } } }
  }
}`;

/** Same as bridge.fingerprint: sha256 of "title\ndescription", first 16 hex characters. */
export async function fingerprint(title, description) {
  const d = new Uint8Array(await crypto.subtle.digest('SHA-256', enc.encode(`${title}\n${description ?? ''}`)));
  return [...d].map((b) => b.toString(16).padStart(2, '0')).join('').slice(0, 16);
}

/** { waiting: tickets whose current brief has no marker yet, inFlight: run keys started and not over,
 *    setup: tickets whose current brief waits (under 7 days) for the requester's routine }. */
export async function survey(issues, ignore = [], now = Date.now()) {
  const waiting = [], inFlight = [], setup = [];
  for (const issue of issues) {
    const kinds = new Map();
    const asked = new Map(); // run key -> when its needs-setup comment was posted
    for (const c of issue.comments?.nodes ?? []) {
      for (const [, key, kind] of (c.body ?? '').matchAll(MARKER)) {
        kinds.set(key, (kinds.get(key) ?? new Set()).add(kind));
        if (kind === 'needs-setup') asked.set(key, Date.parse(c.createdAt ?? '') || 0);
      }
    }
    for (const [key, k] of kinds) if (k.has('started') && ![...k].some((x) => DONE.has(x))) inFlight.push(key);
    const key = `${issue.identifier}-${await fingerprint(issue.title, issue.description)}`;
    if (ignore.includes(issue.identifier) || (issue.description ?? '').trim().length < 40) continue;
    if (!kinds.has(key)) waiting.push(issue.identifier);
    else if ([...kinds.get(key)].every((x) => x === 'needs-setup') && now - asked.get(key) < SETUP_WAIT_MS) {
      setup.push(issue.identifier);
    }
  }
  return { waiting, inFlight, setup };
}

async function linearQueue(env, fetchImpl) {
  const key = env.LINEAR_READ_KEY.startsWith('lin_api_') ? env.LINEAR_READ_KEY : `Bearer ${env.LINEAR_READ_KEY}`;
  const r = await fetchImpl('https://api.linear.app/graphql', {
    method: 'POST',
    headers: { Authorization: key, 'Content-Type': 'application/json', 'User-Agent': 'design-bridge-relay' },
    body: JSON.stringify({ query: QUEUE, variables: { team: env.TEAM_ID, label: env.AI_DESIGN_LABEL_ID } }),
  });
  const body = r.status === 200 ? await r.json() : null;
  if (!body?.data?.issues) throw new Error(`Linear HTTP ${r.status}${body?.errors ? ' (GraphQL errors)' : ''}`);
  return body.data.issues.nodes;
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
  const off = env.RELAY_ENABLED !== 'on';
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
    if (off) return new Response('relay is off');
    return (await dispatch(env, `linear ${event.data.identifier ?? event.data.id}`, fetchImpl))
      ? new Response('tick started') : new Response('dispatch failed', { status: 502 });
  }

  const sig = request.headers.get('x-hub-signature-256') ?? '';
  const want = await hmacHex(env.GITHUB_WEBHOOK_SECRET, body);
  if (!want || !sameText(sig, `sha256=${want}`)) return new Response('bad signature', { status: 401 });
  const event = JSON.parse(body);
  if (!resultPushed(event, request.headers)) return new Response('ignored');
  if (off) return new Response('relay is off');
  return (await dispatch(env, `github ${event.ref}`, fetchImpl))
    ? new Response('tick started') : new Response('dispatch failed', { status: 502 });
}

/** Cron Trigger (every 2 minutes). Safe to repeat: the bridge fires a brief version at most once (claim tags) and
 *  posts one comment per run. Returns what it did, for the log and the tests. */
export async function scheduled(scheduledTime, env, fetchImpl = fetch) {
  if (env.RELAY_ENABLED !== 'on') return log('relay is off (RELAY_ENABLED)');
  if (!env.LINEAR_READ_KEY) return log('LINEAR_READ_KEY is not set');
  const ignore = (env.IGNORE_TICKETS ?? '').split(',').map((x) => x.trim()).filter(Boolean);
  const { waiting, inFlight, setup } = await survey(await linearQueue(env, fetchImpl), ignore, scheduledTime);
  const hourly = new Date(scheduledTime).getUTCMinutes() === 16;
  const why = waiting.length ? `new brief: ${waiting.join(', ')}`
    : hourly && (inFlight.length || setup.length)
      ? `hourly check, in flight: ${inFlight.join(', ') || 'none'}, waiting for setup: ${setup.join(', ') || 'none'}`
      : null;
  if (!why) {
    return log(`nothing to do (in flight: ${inFlight.join(', ') || 'none'}; waiting for setup: ${setup.join(', ') || 'none'})`);
  }
  if (!(await dispatch(env, why, fetchImpl))) throw new Error(`dispatch failed (${why})`);
  return log(`tick started (${why})`);
}

function log(msg) {
  console.log(msg);
  return msg;
}

export default {
  fetch: (request, env) => handle(request, env),
  scheduled: (controller, env) => scheduled(controller.scheduledTime, env),
};
