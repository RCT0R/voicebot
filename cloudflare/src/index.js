const MAX_BODY_BYTES = 8192;
const CALL_FIELDS = [
  "call_id", "direction", "started_at", "ended_at", "duration_seconds",
  "outcome", "summary", "error", "caller_number",
];
const DISPLAY_FIELDS = [
  "INBOUND_NUMBER", "AGENT_NAME", "STT_PROVIDER", "LLM_PROVIDER",
  "TTS_PROVIDER", "MAX_CALL_DURATION_SECONDS",
];
const OUTCOMES = ["completed", "caller_hangup", "max_duration", "failed", "shutdown"];

function isUtcTimestamp(value) {
  if (typeof value !== "string" ||
      !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?Z$/.test(value)) return false;
  const date = new Date(value);
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 19) === value.slice(0, 19);
}

export function validateCall(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return "Expected a JSON object";
  if (Object.keys(value).some((key) => !CALL_FIELDS.includes(key))) return "Unknown call field";
  if (CALL_FIELDS.some((key) => !Object.hasOwn(value, key))) return "Missing call field";
  if (typeof value.call_id !== "string" || value.call_id.length < 1 || value.call_id.length > 128) {
    return "call_id must contain 1 to 128 characters";
  }
  if (!["inbound", "outbound"].includes(value.direction)) return "Invalid direction";
  if (!isUtcTimestamp(value.started_at) || !isUtcTimestamp(value.ended_at)) {
    return "Timestamps must be ISO-8601 UTC strings ending in Z";
  }
  if (typeof value.duration_seconds !== "number" || !Number.isFinite(value.duration_seconds) ||
      value.duration_seconds < 0 || value.duration_seconds > 86400) return "Invalid duration_seconds";
  if (!OUTCOMES.includes(value.outcome)) return "Invalid outcome";
  for (const [key, limit] of [["summary", 2000], ["error", 500], ["caller_number", 32]]) {
    if (value[key] !== null && (typeof value[key] !== "string" || value[key].length > limit)) {
      return `${key} must be null or a string of at most ${limit} characters`;
    }
  }
  return null;
}

export function parseLimit(value) {
  if (value === null || value === undefined || value.trim() === "") return 50;
  const number = Number(value);
  if (!Number.isFinite(number)) return 50;
  return Math.max(1, Math.min(100, Math.trunc(number)));
}

// Hash both inputs so the byte comparison always covers equal-length digests.
export async function constantTimeEqual(left, right) {
  const encoder = new TextEncoder();
  const [leftHash, rightHash] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(left)),
    crypto.subtle.digest("SHA-256", encoder.encode(right)),
  ]);
  const a = new Uint8Array(leftHash);
  const b = new Uint8Array(rightHash);
  let difference = 0;
  for (let index = 0; index < a.length; index++) difference |= a[index] ^ b[index];
  return difference === 0;
}

function json(body, status = 200, headers = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store", ...headers },
  });
}

export async function verifyBasicAuth(request, env) {
  if (!env.DASHBOARD_USERNAME || !env.DASHBOARD_PASSWORD) {
    return json({ error: "Dashboard credentials are not configured" }, 503);
  }
  const unauthorized = () => json({ error: "Authentication required" }, 401, {
    "WWW-Authenticate": 'Basic realm="Receptionist", charset="UTF-8"',
  });
  const match = /^Basic ([A-Za-z0-9+/]+={0,2})$/i.exec(request.headers.get("Authorization") || "");
  if (!match) return unauthorized();
  let credentials;
  try {
    credentials = new TextDecoder("utf-8", { fatal: true }).decode(
      Uint8Array.from(atob(match[1]), (character) => character.charCodeAt(0)),
    );
  } catch {
    return unauthorized();
  }
  const separator = credentials.indexOf(":");
  if (separator < 0) return unauthorized();
  const [usernameMatches, passwordMatches] = await Promise.all([
    constantTimeEqual(credentials.slice(0, separator), env.DASHBOARD_USERNAME),
    constantTimeEqual(credentials.slice(separator + 1), env.DASHBOARD_PASSWORD),
  ]);
  return usernameMatches && passwordMatches ? null : unauthorized();
}

async function verifyBearerAuth(request, env) {
  if (!env.CALL_EVENT_TOKEN) return json({ error: "Call event token is not configured" }, 503);
  const match = /^Bearer (\S+)$/i.exec(request.headers.get("Authorization") || "");
  if (!match || !await constantTimeEqual(match[1], env.CALL_EVENT_TOKEN)) {
    return json({ error: "Authentication required" }, 401);
  }
  return null;
}

async function readCall(request) {
  const reader = request.body?.getReader();
  if (!reader) return { response: json({ error: "Expected a JSON body" }, 400) };
  const chunks = [];
  let length = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > MAX_BODY_BYTES) {
        await reader.cancel();
        return { response: json({ error: "Body exceeds 8192 bytes" }, 413) };
      }
      chunks.push(value);
    }
    const bytes = new Uint8Array(length);
    let offset = 0;
    for (const chunk of chunks) {
      bytes.set(chunk, offset);
      offset += chunk.byteLength;
    }
    return { value: JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) };
  } catch {
    return { response: json({ error: "Invalid JSON body" }, 400) };
  } finally {
    reader.releaseLock();
  }
}

async function handleRequest(request, env) {
  const url = new URL(request.url);
  if (url.pathname === "/health" && request.method === "GET") return json({ status: "ok" });
  if (url.pathname === "/api/calls" && request.method === "POST") {
    const denied = await verifyBearerAuth(request, env);
    if (denied) return denied;
    if (!env.DB) return json({ error: "D1 binding DB is not configured" }, 503);
    const { value, response } = await readCall(request);
    if (response) return response;
    const error = validateCall(value);
    if (error) return json({ error }, 400);
    await env.DB.prepare(`
      INSERT INTO calls (call_id, direction, started_at, ended_at, duration_seconds,
                         outcome, summary, error, caller_number, received_at)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
      ON CONFLICT(call_id) DO UPDATE SET
        direction = excluded.direction, started_at = excluded.started_at,
        ended_at = excluded.ended_at, duration_seconds = excluded.duration_seconds,
        outcome = excluded.outcome, summary = excluded.summary, error = excluded.error,
        caller_number = excluded.caller_number, received_at = excluded.received_at
    `).bind(
      value.call_id, value.direction, new Date(value.started_at).toISOString(),
      new Date(value.ended_at).toISOString(), value.duration_seconds, value.outcome,
      value.summary, value.error, value.caller_number, new Date().toISOString(),
    ).run();
    return json({ accepted: true }, 202);
  }
  if (["/", "/api/status", "/api/calls"].includes(url.pathname)) {
    const denied = await verifyBasicAuth(request, env);
    if (denied) return denied;
    if (request.method !== "GET") return json({ error: "Method not allowed" }, 405, {
      Allow: url.pathname === "/api/calls" ? "GET, POST" : "GET",
    });
    if (url.pathname === "/") return new Response(DASHBOARD, { headers: {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
      "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "no-referrer",
    } });
    if (url.pathname === "/api/calls") {
      if (!env.DB) return json({ error: "D1 binding DB is not configured" }, 503);
      const { results } = await env.DB.prepare(`
        SELECT call_id, direction, started_at, ended_at, duration_seconds,
               outcome, summary, error, caller_number, received_at
        FROM calls ORDER BY started_at DESC LIMIT ?
      `).bind(parseLimit(url.searchParams.get("limit"))).all();
      return json({ calls: results });
    }
    const display = Object.fromEntries(DISPLAY_FIELDS.map((key) => [key, env[key] ?? null]));
    if (!env.DB) return json({ ...display, total_calls: null, calls_today: null,
      last_call_at: null, warning: "D1 binding DB is not configured" });
    const counts = await env.DB.prepare(`
      SELECT COUNT(*) AS total_calls,
             COALESCE(SUM(CASE WHEN substr(started_at, 1, 10) = ? THEN 1 ELSE 0 END), 0) AS calls_today,
             MAX(started_at) AS last_call_at FROM calls
    `).bind(new Date().toISOString().slice(0, 10)).first();
    return json({ ...display, ...counts });
  }
  return json({ error: "Not found" }, 404);
}

export default {
  async fetch(request, env) {
    try {
      return await handleRequest(request, env);
    } catch {
      // Do not log credentials, request bodies, or database error details.
      return json({ error: "Service unavailable. Check the D1 binding and schema." }, 503);
    }
  },
};

const DASHBOARD = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Receptionist dashboard</title>
<style>
:root { color-scheme: light dark; font-family: system-ui, sans-serif; }
body { max-width: 1200px; margin: auto; padding: 1.25rem; line-height: 1.5; }
h1 { font-size: 1.7rem; } h2 { font-size: 1.25rem; }
dl { display: grid; grid-template-columns: repeat(auto-fit,minmax(180px,1fr)); gap: 1rem; }
dl div { border: 1px solid #888; border-radius: .4rem; padding: .8rem; }
dt { font-weight: 600; } dd { margin: .3rem 0 0; overflow-wrap: anywhere; }
.table-scroll { overflow-x: auto; } table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: .65rem; border-bottom: 1px solid #888; vertical-align: top; }
td { min-width: 7rem; max-width: 22rem; overflow-wrap: anywhere; }
button { font: inherit; padding: .4rem .8rem; cursor: pointer; }
:focus-visible { outline: 3px solid #3679dd; outline-offset: 3px; }
</style>
</head>
<body>
<main>
<h1>Receptionist dashboard</h1>
<button type="button" id="refresh">Refresh data</button>
<p id="message" role="status" aria-live="polite">Loading call data.</p>
<section aria-labelledby="status-heading">
<h2 id="status-heading">Status</h2><dl id="status"></dl>
</section>
<section aria-labelledby="calls-heading">
<h2 id="calls-heading">Recent calls</h2>
<p>Times use UTC. Today's count uses the call start date in UTC.</p>
<div class="table-scroll" role="region" aria-label="Recent calls table" tabindex="0">
<table><caption>Up to 50 calls, newest start time first</caption>
<thead><tr><th scope="col">Started</th><th scope="col">Caller</th><th scope="col">Direction</th>
<th scope="col">Duration (seconds)</th><th scope="col">Outcome</th><th scope="col">Summary</th>
<th scope="col">Error</th></tr></thead><tbody id="calls"></tbody></table>
</div></section>
<noscript>Enable JavaScript to load status and recent calls.</noscript>
</main>
<script>
const labels = {
  INBOUND_NUMBER: 'Inbound number', AGENT_NAME: 'Agent name', STT_PROVIDER: 'Speech recognition',
  LLM_PROVIDER: 'Language model', TTS_PROVIDER: 'Speech synthesis',
  MAX_CALL_DURATION_SECONDS: 'Maximum duration (seconds)', total_calls: 'Total calls',
  calls_today: 'Calls today (UTC)', last_call_at: 'Last call (UTC)'
};
async function load() {
  const button = document.getElementById('refresh');
  const message = document.getElementById('message');
  button.disabled = true;
  message.textContent = 'Loading call data.';
  const errors = [];
  await Promise.all([
    (async () => {
      try {
        const response = await fetch('/api/status');
        if (!response.ok) throw new Error('Could not load status. Check your credentials and database configuration.');
        const status = await response.json();
        const cards = Object.entries(labels).map(([key, label]) => {
          const card = document.createElement('div');
          const term = document.createElement('dt');
          const value = document.createElement('dd');
          term.textContent = label;
          value.textContent = status[key] ?? 'Not available';
          card.append(term, value);
          return card;
        });
        document.getElementById('status').replaceChildren(...cards);
        if (status.warning) errors.push(status.warning);
      } catch (error) { errors.push(error.message); }
    })(),
    (async () => {
      try {
        const response = await fetch('/api/calls?limit=50');
        if (!response.ok) throw new Error('Could not load calls. Check your credentials and database configuration.');
        const { calls } = await response.json();
        const rows = calls.map((call) => {
          const row = document.createElement('tr');
          for (const key of ['started_at', 'caller_number', 'direction', 'duration_seconds', 'outcome', 'summary', 'error']) {
            const cell = document.createElement('td');
            cell.textContent = call[key] ?? '—';
            row.append(cell);
          }
          return row;
        });
        if (!rows.length) {
          const row = document.createElement('tr');
          const cell = document.createElement('td');
          cell.colSpan = 7;
          cell.textContent = 'No calls recorded.';
          row.append(cell);
          rows.push(row);
        }
        document.getElementById('calls').replaceChildren(...rows);
      } catch (error) { errors.push(error.message); }
    })()
  ]);
  message.textContent = errors.length ? errors.join(' ') : 'Call data loaded.';
  button.disabled = false;
}
document.getElementById('refresh').addEventListener('click', load);
load();
</script>
</body>
</html>`;
