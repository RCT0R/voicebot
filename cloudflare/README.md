# Receptionist dashboard

This Cloudflare Worker stores call records in D1 and serves a password-protected dashboard.
It does not place or answer calls.
The Python LiveKit agent sends records after each call.

## Setup

Use Node.js 22 or later.
Run these commands from `cloudflare/`.

```sh
npx wrangler@latest login
npx wrangler@latest d1 create receptionist-calls
```

Replace `REPLACE_WITH_D1_DATABASE_ID` in `wrangler.toml` with the returned database ID.
Set the display values under `[vars]` for your agent.
These values describe configuration, not live agent health.

```sh
npx wrangler@latest d1 execute receptionist-calls --remote --file=schema.sql
npx wrangler@latest secret put CALL_EVENT_TOKEN
npx wrangler@latest secret put DASHBOARD_USERNAME
npx wrangler@latest secret put DASHBOARD_PASSWORD
npx wrangler@latest deploy
```

Use long, unique secrets.
Use a username without a colon.
Open the deployed Worker URL and enter your dashboard credentials in the browser's Basic authentication prompt.
No resources are provisioned or deployed by this repository alone.

## Local checks and development

```sh
npm test
node --check src/index.js
```

For local development, put the three secrets in a local `.dev.vars` file.
Do not commit that file.
Initialize the local database, then start Wrangler:

```sh
npx wrangler@latest d1 execute receptionist-calls --local --file=schema.sql
npx wrangler@latest dev
```

Check the current Cloudflare documentation for Workers free-plan request and CPU limits and D1 free storage, read, and write limits before use:

- https://developers.cloudflare.com/workers/platform/limits/
- https://developers.cloudflare.com/d1/platform/limits/

## Agent integration

Set these environment variables on the Python agent:

```dotenv
CALL_EVENT_WEBHOOK_URL=https://YOUR_WORKER_HOST/api/calls
CALL_EVENT_WEBHOOK_TOKEN=YOUR_CALL_EVENT_TOKEN
```

The agent must send `Authorization: Bearer <CALL_EVENT_WEBHOOK_TOKEN>` and a JSON body of at most 8192 UTF-8 bytes.
The Python agent implements this sender in `../calls.py`.
This directory receives and stores the record.
Send all nine fields, including explicit `null` values for optional text:

```json
{
  "call_id": "call-123",
  "direction": "inbound",
  "started_at": "2026-10-24T10:00:00Z",
  "ended_at": "2026-10-24T10:01:00Z",
  "duration_seconds": 60,
  "outcome": "completed",
  "summary": "The caller requested an appointment.",
  "error": null,
  "caller_number": null
}
```

Use UTC timestamps ending in `Z`.
The Worker stores timestamps in canonical UTC format with milliseconds.
Use a call ID of 1–128 characters and a duration from 0 to 86400 seconds.
Direction accepts `inbound` or `outbound`.
Outcome accepts `completed`, `caller_hangup`, `max_duration`, `failed`, or `shutdown`.
Summary accepts up to 2000 characters, error up to 500, and caller number up to 32.
Unknown fields are rejected.
Accepted records return HTTP 202.
Retries with the same `call_id` update the existing record rather than insert duplicates.

## Endpoints

- `GET /`: Basic-authenticated dashboard with same-origin status and call requests.
- `POST /api/calls`: Bearer-authenticated ingestion.
- `GET /api/calls?limit=50`: Basic-authenticated records, newest start time first.
  The limit defaults to 50 and is clamped to 1–100.
- `GET /api/status`: Basic-authenticated display configuration and database counts.
  Calls today counts starts since midnight UTC.
- `GET /health`: Public response containing only `{"status":"ok"}`.
  This endpoint does not check the agent or database.

Missing dashboard secrets or a missing ingestion token fail closed with HTTP 503.
A missing D1 binding returns HTTP 503 for call endpoints.
Status returns null counts and a warning when the binding is missing.

## Security

Use HTTPS outside local development.
Keep secrets in Wrangler secrets, not display variables or source files.
The Worker compares SHA-256 credential digests with a fixed-length byte comparison.
The dashboard uses the browser's Basic authentication support and does not store passwords in JavaScript.
Shared browsers can retain Basic credentials; close the browser session after use.

The Worker sends no CORS headers, loads no external assets, and makes no outbound requests.
It does not log tokens or request bodies.
Observability is enabled in Wrangler; do not put secrets in URLs or add request-body logging.
Call records can contain personal information.
Restrict access, minimize stored details, and define your own retention and deletion policy.
This implementation does not add automatic deletion or application-level rate limiting.
