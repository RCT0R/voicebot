# Security

This document describes the security model and the configuration you must complete before exposing the receptionist to real callers.

## Secret inventory

| Secret | Used by | Storage |
| --- | --- | --- |
| `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` | Agent, setup scripts, Next.js outbound dashboard | `.env` locally, host secret manager or LiveKit Cloud secrets in production |
| `GROQ_API_KEY` | Agent | `.env` or host secret manager |
| `DEEPGRAM_API_KEY` | Agent | `.env` or host secret manager |
| `VOBIZ_USERNAME`, `VOBIZ_PASSWORD` | Optional outbound trunk scripts | `.env` or host secret manager |
| `CALL_EVENT_WEBHOOK_TOKEN` | Agent to Cloudflare Worker | Agent secret and Cloudflare Worker secret |
| `DASHBOARD_USERNAME`, `DASHBOARD_PASSWORD` | Cloudflare Worker and Next.js proxy | Host secrets or Cloudflare secrets |
| Vobiz auth ID and auth token | Manual provider API calls | Password manager or secret manager |

Rules:

- Do not commit `.env`, `.env.local`, `.dev.vars`, or filled-in deployment secret files.
- Do not put secrets in browser JavaScript.
- Do not return secrets from HTTP endpoints.
- Do not print secrets in logs.
- Use different values for the dashboard password and the call-event token.
- Use at least 16 random characters for the call-event token. The agent rejects shorter values when a webhook URL is configured.
- Use a password manager to generate and store dashboard credentials.

The repository's `.gitignore` excludes `.env`, `.env.local`, local call records, and Cloudflare local state.
A pattern scan of the existing Git history found placeholder values such as `LIVEKIT_API_SECRET=...`, not live credentials.
Run your own secret scanner before publishing a fork.

## Transport and endpoints

- The agent connects outbound to LiveKit over WebSocket and to Groq and Deepgram over HTTPS.
- The agent does not expose an application HTTP API.
  LiveKit starts a local worker health server on port 8081.
  Do not expose that port publicly unless you need it for monitoring.
- The optional Next.js dashboard exposes HTTP endpoints. Its proxy requires HTTP Basic authentication and fails closed when credentials are missing.
- The Cloudflare Worker exposes:
  - `GET /health`, public and limited to `{"status":"ok"}`.
  - `POST /api/calls`, Bearer-token authenticated.
  - `GET /`, `GET /api/status`, `GET /api/calls`, Basic-authenticated.
- The Worker sends no CORS headers and makes no outbound requests.
- Use HTTPS for the dashboard. Basic authentication is not safe over plain HTTP.
- Do not expose the LiveKit API key or secret to the dashboard. The Next.js server uses them server-side only.

## Inbound SIP

The LiveKit inbound trunk accepts calls for the configured number.
Restrict `INBOUND_SIP_ALLOWED_ADDRESSES` to the Vobiz signalling addresses for your trunk.
If you leave it empty, `setup_inbound.py` creates `0.0.0.0/0` so the first call can connect, and prints a warning.
That permissive default accepts SIP traffic from any source and should not be used for a public production number.

Optional digest authentication is available through `INBOUND_SIP_AUTH_USERNAME` and `INBOUND_SIP_AUTH_PASSWORD`.
Confirm with Vobiz that your trunk sends the matching credentials before you enable it.
If the credentials do not match, calls fail to connect.

The agent name in the LiveKit dispatch rule is a security boundary in practice.
Only a caller with LiveKit API credentials can create a dispatch, but anyone with those credentials can direct calls to rooms.
Treat `LIVEKIT_API_KEY` and `LIVEKIT_API_SECRET` as full project control credentials.

## Call control and tools

The model can call only two tools:

- `end_call`, which ends the current call after a short grace period.
- `transfer_call`, only when `ENABLE_TRANSFER=true`.

`transfer_call` accepts only E.164 phone numbers.
It rejects arbitrary SIP URIs, hostnames, and schemes.
This prevents the model from dialing an unintended SIP destination.
The transfer uses the existing SIP participant in the room and requires that the Vobiz trunk supports SIP REFER.

There is no HTTP tool, shell tool, database tool, or outbound-call tool available to the model.
Outbound calls require a LiveKit dispatch with the expected metadata and API credentials.
A prompt-injection attempt can at most affect the current conversation.
It cannot create new calls through the application.

## Personal data

By default:

- `STORE_CALLER_NUMBER=false`. The caller's phone number is not stored in SQLite or sent to Cloudflare.
- `CALL_SUMMARY_ENABLED=false`. No post-call LLM summary is generated.
- `record=False` is passed to `AgentSession.start`. No audio or transcript recording is created.
- No transcript table is created.

If you enable summaries:

- The transcript text is sent to Groq (or OpenAI if configured) after the call.
- The generated summary is stored in SQLite and may be sent to Cloudflare D1.
- The summary prompt tells the model not to include names, phone numbers, email addresses, account numbers, or other personal data.
- You must still review the summary before relying on it and define a retention policy.

If you enable caller-number storage:

- The number is stored in SQLite and may be sent to Cloudflare D1.
- The number is masked in application logs.
- Define who can access the dashboard and how long records are kept.

LiveKit's individual dispatch rule names inbound rooms after the caller's phone number.
LiveKit logs and traces may therefore contain the caller's number even when this application does not store it.
This is a LiveKit behavior documented in its dispatch rule guide.
If that is unacceptable, use a routing design that controls the SIP `To` header and uses a non-PII room name.

## Logging

Application logs use structured JSON when `LOG_FORMAT=json`.
The logging layer redacts common bearer tokens, API-key prefixes, and token query parameters.
Logs include call IDs, outcomes, durations, provider names, and model names.
They do not include API keys, raw prompts, transcripts, or full caller numbers.

Do not add request-body logging to the Cloudflare Worker.
Do not paste full error objects from provider SDKs into logs without redaction.

## Abuse and cost control

- The maximum call duration defaults to 600 seconds.
- The SIP trunk has a hard limit 30 seconds above the agent limit.
- Outbound calls are never retried automatically.
- The dashboard validates E.164 numbers and limits bulk requests to 50 numbers.
- Cloudflare Workers and D1 have free quotas, but a public endpoint can still consume them.
- Restrict the dashboard with Cloudflare Access or a firewall rule if it is publicly reachable.
- Monitor LiveKit usage, Deepgram credit, Groq quota, and Vobiz balance.
- A malicious caller can consume paid telephone minutes and speech minutes. Treat the public number as an untrusted input.

The application does not implement per-caller rate limiting or blocklists.
Add a provider-level or edge-level control if you need them.

## Account security

- Enable multi-factor authentication on LiveKit, Groq, Deepgram, Vobiz, and Cloudflare.
- Use separate API keys for development and production when the provider supports it.
- Do not reuse the LiveKit API secret for other services.
- Do not put production secrets in a shell command that is recorded in history.
- Rotate a key immediately if it appears in a log, screenshot, chat, commit, or support ticket.

## Legal and compliance

- Tell callers that they are speaking to an AI assistant when required by local law or regulation.
- Do not record calls without the consent required in your jurisdiction.
- This project does not record calls by default.
- Summaries and caller-number storage can create personal-data obligations. Define a lawful basis, retention period, access policy, and deletion process.
- Indian telephone numbers require provider KYC and may be subject to telecom regulations. Follow Vobiz's requirements.
- Do not use the receptionist for emergency, medical, legal, or financial advice.
- Review the privacy policies and data-retention settings of LiveKit, Groq, Deepgram, Vobiz, and Cloudflare.

## Incident response

1. Stop the agent process or deployment.
2. Rotate the LiveKit API key and secret, Groq key, Deepgram key, call-event token, and dashboard password as applicable.
3. Remove the leaked value from Git history if it was committed. Rotate first; history rewriting is not a substitute for rotation.
4. Review LiveKit room logs, Vobiz call records, Cloudflare Worker logs, and provider billing for unauthorized activity.
5. Redeploy with the new secrets.
6. Document the cause and add a check that prevents the same leak.

## Known security gaps

- The Cloudflare Worker has no application-level rate limiting.
- The Next.js outbound dashboard uses Basic authentication, not per-user accounts or MFA.
- The optional transfer feature depends on Vobiz SIP REFER support and the destination number's own security.
- The inbound trunk defaults to accepting all source addresses until you restrict it.
- There is no automated secret scanner in this repository. Add one to CI if the repository becomes public.
