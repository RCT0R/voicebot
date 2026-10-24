# AI phone receptionist

An inbound AI receptionist that answers real telephone calls with LiveKit, Groq, Deepgram, and Vobiz.

The caller dials a Vobiz number.
Vobiz sends the call over SIP to LiveKit.
A LiveKit dispatch rule creates a private room and starts the receptionist worker.
The caller hears a short greeting, speaks naturally, and the agent responds until the call ends.

The original outbound calling workflow is retained as an optional path for the existing dashboard and `make_call.py`.

## Project status

| Area | Status |
| --- | --- |
| Inbound call flow | Implemented |
| Groq LLM pipeline | Implemented; provider selection unit-tested |
| Deepgram STT/TTS pipeline | Implemented; provider selection unit-tested without live audio |
| Vobiz inbound routing | Implemented and provisioning plan unit-tested; not run against a live LiveKit project |
| Error handling and cleanup | Implemented, including maximum duration and disconnect paths |
| Call records | Implemented with SQLite and optional Cloudflare D1 delivery |
| Automated tests | 67 Python tests and 13 Cloudflare Worker tests pass |
| Local LiveKit worker registration | Verified against a local LiveKit server; registered as `receptionist` |
| LiveKit SIP provisioning | Blocked locally because the open-source server requires Redis for SIP; not run against LiveKit Cloud |
| Docker image | Builds for arm64 and linux/amd64 locally; imports and entrypoint verified; not deployed |
| Next.js proxy | Runtime checks return 401 without credentials, 200 with credentials, and 503 when credentials are unset |
| Next.js SDK | Created a room and explicit agent dispatch against a local LiveKit server using `wss://` |
| Cloudflare Worker local D1 | Verified end-to-end with Wrangler: auth, ingest, upsert, and status |
| Real telephone call | Not performed in this environment |
| LiveKit Cloud deployment | Not performed; requires your account |
| Vobiz account configuration | Requires your account, number, KYC, and inbound enablement |
| Cloudflare deployment | Not performed; requires your account |

No funds were added and no paid service was purchased.

## Architecture

```text
 Caller
   |
   | PSTN
   v
 Vobiz number and SIP trunk
   |
   | SIP INVITE to <project>.sip.livekit.cloud
   v
 LiveKit SIP ingress
   |
   | inbound trunk: your Vobiz number
   | dispatch rule: individual room "call-..." + agent "receptionist"
   v
 LiveKit room
   |-- SIP participant: caller audio
   |-- Agent participant: LiveKit Agents worker
          Silero VAD
             |
          Deepgram Nova-3 STT (streaming)
             |
          Groq openai/gpt-oss-120b
             |
          Deepgram Aura-2 TTS (streaming)
   |
   | call ends
   v
 SQLite call record
   |
   | optional HTTPS call event
   v
 Cloudflare Worker + D1 dashboard
```

The voice agent is a long-running Python process.
It runs on LiveKit Cloud or in Docker on a host you control.
It is not a Cloudflare Worker.

The Cloudflare Worker is a separate management dashboard with a small D1 database.
It stores call metadata and does not handle audio.

## Verified provider choices

The choices below were checked against current provider documentation on 2026-10-24.

| Stage | Default | Why |
| --- | --- | --- |
| LLM | Groq `openai/gpt-oss-120b` | Current Groq production model. Fast and available on the free plan with limits. The old `llama-3.3-70b-versatile` and `llama-3.1-8b-instant` IDs are retired for normal use. |
| STT | Deepgram Nova-3 streaming, language `multi` | Streaming recognition with low telephone latency. Deepgram is already part of the original project. |
| TTS | Deepgram Aura-2 | Streaming speech synthesis with telephony-friendly latency. |
| VAD | Silero | Local voice activity detection bundled with LiveKit Agents. |
| Noise cancellation | LiveKit BVC telephony, when available | Suppresses background noise on telephone audio. The agent continues without it if the plugin is unavailable. |
| Agent framework | LiveKit Agents 1.8.9 | Current installed version. Uses `AgentServer`, `AgentSession`, and inbound SIP dispatch. |
| Telephone provider | Vobiz | Existing provider and number. Inbound uses a Vobiz SIP trunk with the LiveKit SIP endpoint as its inbound destination. |
| Dashboard | Cloudflare Worker and D1 | Stateless HTTP and a small database fit the free plan. It is not in the audio path. |

Groq Whisper and Groq Orpheus TTS are available as optional settings.
Groq Whisper is batch-only and adds latency.
Groq Orpheus is a preview model with very small free quotas.
Deepgram remains the default because it preserves conversational latency.

You can change the LLM, STT, and TTS providers with environment variables.
The agent validates provider names and required keys at startup.

## Repository layout

| Path | Purpose |
| --- | --- |
| `agent.py` | LiveKit worker. Detects inbound or outbound dispatch, greets the caller, runs the session, records the outcome, and cleans up. |
| `config.py` | Central environment parsing and validation. Reports all missing keys at once without printing values. |
| `providers.py` | Builds Groq, Deepgram, OpenAI, Silero, and noise-cancellation components. |
| `calls.py` | SQLite call records, transcript text building, optional summaries, and Cloudflare call-event delivery. |
| `telephony.py` | E.164 validation, phone masking, SIP endpoint derivation, and safe transfer targets. |
| `logging_setup.py` | Text or JSON logs with credential redaction. |
| `setup_inbound.py` | Creates a LiveKit inbound trunk and dispatch rule for the Vobiz number. Reuses existing objects and never deletes. |
| `make_call.py` | Optional outbound dispatch for manual testing. |
| `create_trunk.py`, `setup_trunk.py`, `list_trunks.py` | Optional Vobiz outbound trunk utilities. |
| `tests/` | Pytest suite for configuration, routing plans, call lifecycle, providers, summaries, and webhook delivery. |
| `dashboard/` | Optional Next.js outbound dialer, protected by Basic authentication. |
| `cloudflare/` | Cloudflare Worker, D1 schema, tests, and dashboard documentation. |
| `DEPLOYMENT.md` | Exact deployment, Vobiz, LiveKit, Cloudflare, and first-call commands. |
| `COSTS.md` | Cost matrix, free-tier limits, and a worked example. |
| `SECURITY.md` | Security model, secret handling, personal data, and incident response. |

## Quick start

You need Python 3.12, `uv`, a LiveKit Cloud project, a Groq key, a Deepgram key, and a Vobiz number that can receive calls.

```sh
git clone https://github.com/toprmrproducer/LIvekitAIVoice.git
cd LIvekitAIVoice

uv venv --python 3.12
uv pip install -r requirements-dev.txt

cp .env.example .env
```

Edit `.env`.
Set the LiveKit credentials, `GROQ_API_KEY`, `DEEPGRAM_API_KEY`, and `VOBIZ_INBOUND_NUMBER`.
Leave `BUSINESS_NAME` blank until you have a real business identity to give the agent.
Do not paste real credentials into issues or source files.

Check the configuration without placing a call:

```sh
uv run python -c "from config import get_settings; print(get_settings().redacted_summary())"
uv run python setup_inbound.py --dry-run
```

Create the LiveKit inbound routing:

```sh
uv run python setup_inbound.py
```

The script prints the SIP endpoint for Vobiz.
It also prints the next manual steps.

Configure Vobiz:

1. Create or open the SIP trunk for your number.
2. Link the Indian number and complete KYC and number activation.
3. Set the trunk's inbound destination to the printed endpoint.
   Remove the `sip:` prefix.
4. Confirm the trunk has an active balance.
5. If inbound calls do not arrive, ask Vobiz support to enable or confirm inbound routing on the trunk.

Start the agent:

```sh
uv run python agent.py dev
```

Development mode reloads on file changes.
Use `uv run python agent.py start` for a production-style process.

Call the Vobiz number from another phone.
The full first-call checklist is in `DEPLOYMENT.md`.

## Environment variables

`.env.example` is the complete template.
The important settings are:

| Variable | Required | Default | Meaning |
| --- | --- | --- | --- |
| `LIVEKIT_URL` | Yes | none | LiveKit Cloud URL, for example `wss://project.livekit.cloud`. |
| `LIVEKIT_API_KEY` | Yes | none | LiveKit API key. Treat it as project control access. |
| `LIVEKIT_API_SECRET` | Yes | none | LiveKit API secret. |
| `GROQ_API_KEY` | Yes for the default LLM | none | Groq key. |
| `DEEPGRAM_API_KEY` | Yes for the default STT/TTS | none | Deepgram key. |
| `VOBIZ_INBOUND_NUMBER` | Yes for setup | none | The E.164 number linked to the Vobiz trunk. |
| `AGENT_NAME` | No | `receptionist` | LiveKit dispatch name. It must match the dispatch rule. |
| `BUSINESS_NAME` | No | empty | Optional business name. If empty, the prompt tells the agent not to invent one. |
| `AGENT_DISPLAY_NAME` | No | `AI receptionist` | Name the agent uses for itself. |
| `AGENT_LANGUAGE` | No | `en-IN` | Default reply language. Use a custom greeting for non-English first lines. |
| `GREETING` | No | generated | Exact first line. Leave blank for the generated greeting. |
| `SYSTEM_PROMPT` | No | built-in | Full prompt override. Leave blank to use the safe default. |
| `LLM_PROVIDER` | No | `groq` | `groq` or `openai`. |
| `GROQ_MODEL` | No | `openai/gpt-oss-120b` | Check current Groq availability before changing. |
| `LLM_MAX_COMPLETION_TOKENS` | No | `200` | Caps reply length, latency, and token use. |
| `STT_PROVIDER` | No | `deepgram` | `deepgram` or `groq`. |
| `TTS_PROVIDER` | No | `deepgram` | `deepgram`, `groq`, or `openai`. |
| `STT_LANGUAGE` | No | `multi` | Deepgram language mode or Groq auto-detect when set to `multi`. |
| `MAX_CALL_DURATION_SECONDS` | No | `600` | Agent-side maximum call duration. |
| `CALL_SUMMARY_ENABLED` | No | `false` | Enables an extra LLM request after each call. |
| `STORE_CALLER_NUMBER` | No | `false` | Stores the caller number in SQLite and sends it to the dashboard if enabled. |
| `CALL_EVENT_WEBHOOK_URL` | No | empty | Cloudflare Worker `/api/calls` URL. |
| `CALL_EVENT_WEBHOOK_TOKEN` | With the URL | empty | Shared secret, at least 16 characters. |
| `ENABLE_TRANSFER` | No | `false` | Enables the human-transfer tool. |
| `DEFAULT_TRANSFER_NUMBER` | With transfer | empty | E.164 transfer destination. |
| `INBOUND_SIP_ALLOWED_ADDRESSES` | Recommended | empty | Comma-separated Vobiz signalling IPs or CIDR ranges. |
| `DASHBOARD_USERNAME`, `DASHBOARD_PASSWORD` | For the Next.js dashboard | empty | Basic authentication for the optional outbound dashboard. |

The agent does not read `DASHBOARD_USERNAME` or `DASHBOARD_PASSWORD`.
The Cloudflare Worker uses its own Wrangler secrets.

## AI behavior

The default prompt is configurable and intentionally conservative:

- It is friendly, professional, and concise.
- It keeps answers to one or two short sentences.
- It asks one clarifying question at a time.
- It replies in the caller's language when it can do so confidently.
- It never invents a business name, hours, prices, services, or policies.
- It never claims to have booked, changed, cancelled, transferred, or messaged anything unless a tool confirmed it.
- It does not ask for payment cards, passwords, or one-time codes.
- It identifies itself as an AI receptionist.
- It ends the call with `end_call` when the conversation is finished.
- It can transfer only when `ENABLE_TRANSFER=true`, and only to an E.164 number.

Set `BUSINESS_NAME` and `SYSTEM_PROMPT` only after you have real information to provide.
Do not give the model a knowledge base it does not have.

## Call lifecycle

The inbound entrypoint does the following:

1. Connect to the dispatched LiveKit room. The connection is bounded by a 15-second timeout.
2. Build the STT, LLM, TTS, VAD, and noise-cancellation components.
3. Start the agent session with recording disabled. Session startup is bounded by a 30-second timeout.
4. Wait up to 15 seconds for the SIP caller and fail the call if it does not join.
5. Speak the configured greeting.
6. Run the conversation until the caller disconnects, the agent ends the call, an unrecoverable pipeline error occurs, or the maximum duration is reached.
7. Generate an optional summary from the in-memory transcript.
8. Store one SQLite record.
9. Send the record to Cloudflare if a webhook is configured.
10. Close the session and the room.

The maximum duration is enforced twice:

- The agent speaks a timeout message and closes at `MAX_CALL_DURATION_SECONDS`.
- The LiveKit inbound trunk has a hard duration limit 30 seconds above that value.

Call outcomes are stored as `completed`, `caller_hangup`, `max_duration`, `failed`, or `shutdown`.
The tracker's finish operation is idempotent, so a shutdown callback and the main cleanup path cannot create two records.

Outbound dispatch metadata controls the same worker:

- `phone_number` plus `dial: true` tells the agent to place the call.
- `phone_number` plus `dial: false` tells the agent that the dashboard already created the SIP participant, so it must not dial again.
- Inbound dispatch metadata is `{"direction":"inbound"}`.

## Call records and summaries

Records are written to `data/calls.db` by default.

Each row contains:

- Call ID.
- Direction.
- Start and end time in UTC.
- Duration in seconds.
- Outcome.
- Optional summary.
- Optional redacted error.
- Optional caller number, only when `STORE_CALLER_NUMBER=true`.

The application does not create a transcript table and does not record audio.
`AgentSession.start` is called with `record=False`.

Summaries are disabled by default.
If you enable them, the in-memory transcript is sent to the configured LLM after the call.
The summary prompt tells the model to omit names, phone numbers, email addresses, account numbers, and other personal data.
Review the result before relying on it.

The Cloudflare Worker accepts call events and upserts them by call ID.
Webhook failure does not change the call outcome and is not retried automatically.
The Worker is idempotent, so a manual retry is safe.

## Tests

Run the Python tests:

```sh
uv run pytest
```

Current result:

```text
67 passed
```

Run the Cloudflare Worker tests:

```sh
cd cloudflare
npm test
```

Current result:

```text
13 tests, 13 pass, 0 fail
```

Run the Next.js checks:

```sh
cd dashboard
npm ci
npm run lint
npm run build
```

Current result: lint and production build pass.
Next.js reports the `/` page as static and the two API routes as dynamic.
The proxy is compiled as middleware.

Runtime proxy checks:

```text
GET / without credentials                        401
GET / with correct credentials                   200
POST /api/dispatch without credentials           401
POST /api/dispatch with credentials and bad E.164 400
GET / when dashboard credentials are unset       503
```

Build the production container:

```sh
docker build -t ai-receptionist:test .
docker build --platform linux/amd64 -t ai-receptionist:test-amd64 .
docker run --rm ai-receptionist:test python -c "import agent, calls, providers, config"
```

Current result: the arm64 and linux/amd64 images build, the container imports the agent modules, and the linux/amd64 entrypoint starts.
The amd64 build required a retry after a PyPI download timeout.
That is a network issue, not a dependency or code failure.

Worker registration was also checked against a local open-source LiveKit server.
The worker registered with the dispatch name `receptionist`.
SIP provisioning could not complete on that server because its SIP service requires Redis.
That is a local server limitation, not a code path result.
Use a LiveKit Cloud project or a SIP-enabled self-hosted deployment for the first real provisioning run.

The Next.js server SDK also created a room and explicit agent dispatch against a local LiveKit server using `wss://`.
That verifies the outbound dashboard's LiveKit URL format and dispatch path.

The Cloudflare Worker was checked locally with Wrangler and a local D1 database:

```text
GET /health                        200 {"status":"ok"}
GET / without credentials          401
POST /api/calls with valid token   202
POST the same call again           202; the row was updated, not duplicated
GET /api/calls with Basic auth     200; one updated row
GET /api/status with Basic auth    200; total_calls and calls_today were 1
```

These checks did not create remote Cloudflare resources.

The tests cover:

- Missing and invalid environment values, including aggregated errors and no secret leakage.
- Provider-specific key requirements.
- Greeting and prompt behavior with and without a business name.
- E.164 validation, masking, SIP endpoint derivation, and transfer target restrictions.
- Inbound trunk and dispatch rule plans, including reuse and conflict warnings.
- SQLite persistence, outcome validation, redaction, and idempotent finish.
- Close-reason mapping, timeout precedence, and fallback behavior.
- Transcript building and 500-character summary bounds.
- Groq, Deepgram, and OpenAI provider selection.
- Bearer-authenticated call-event delivery, rejection handling, and timeouts.
- Cloudflare Worker payload validation, authentication, fail-closed behavior, and D1 queries with a fake binding.

These tests use fake API clients and fake SIP metadata.
No real telephone call was placed.
No live Groq or Deepgram request was made by the test suite.

## Deployment

See `DEPLOYMENT.md` for complete commands.

Recommended initial deployment:

1. Deploy the agent to LiveKit Cloud with `lk agent create`.
   The Build plan includes 1,000 agent minutes and 1,000 third-party SIP minutes per month.
2. Deploy the Cloudflare Worker and D1 database for the dashboard.
3. Configure Vobiz inbound routing to the LiveKit SIP endpoint.
4. Place a real test call.

Alternative:

- Run `docker compose up -d --build` on a host you already have.
  The compose file uses a named volume for SQLite and no host networking.

Cloudflare is used for the management dashboard, not the voice agent.
Workers cannot host the long-running Python media worker.
Cloudflare Containers would require a paid plan and do not improve the voice path.

The optional Next.js outbound dashboard can run locally or on Vercel.
It is protected by Basic authentication and fails closed when credentials are missing.
The inbound dashboard is the Cloudflare Worker.

## Costs

The full matrix is in `COSTS.md`.

Short version:

- Groq LLM: free within the free-plan quotas; paid after upgrading or changing plans.
- Deepgram STT/TTS: covered by a $200 signup credit, then paid.
- LiveKit Build: free within 1,000 agent minutes, 1,000 third-party SIP minutes, and related limits per month.
- Cloudflare Workers and D1: free within their quotas.
- Vobiz number and inbound minutes: paid and account-specific.
- Telephone service is not free, and the Vobiz India rate cannot be verified without your account.

A five-minute call after the free allowances is roughly $0.14 in platform and API usage, before Vobiz minutes and number rental.
See `COSTS.md` for the calculation and caveats.

Deepgram's console has an auto-reload setting.
Check it and disable automatic purchases if you do not want charges after the credit is used.

## Security

See `SECURITY.md` for the full model.

Key points:

- No secrets are committed to the repository.
- `.env`, `.env.local`, local databases, and Cloudflare local state are ignored.
- Configuration errors do not print secret values.
- Logs redact bearer tokens, API-key prefixes, and token query parameters.
- The Cloudflare Worker requires a Bearer token for call events and Basic authentication for the dashboard.
- The Next.js dashboard fails closed when its Basic authentication credentials are unset.
- The agent exposes no public HTTP endpoint.
- The agent has no shell, HTTP, or outbound-call tools.
- Transfers accept E.164 numbers only.
- Recordings and transcripts are disabled by default.
- Caller-number storage is disabled by default.
- Restrict `INBOUND_SIP_ALLOWED_ADDRESSES` to Vobiz addresses before production.

LiveKit's individual dispatch rule includes the caller's phone number in the room name.
LiveKit logs may retain that value.
This project does not control that provider behavior.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Caller hears silence after dialing | The worker is not running, the agent name does not match, or the dispatch rule has no agent dispatch. | Check `AGENT_NAME`, run `setup_inbound.py`, and read the agent and LiveKit SIP logs. |
| Call drops with 408 or never reaches LiveKit | The Vobiz inbound destination is wrong or includes `sip:`. | Set it to `<project>.sip.livekit.cloud` with no scheme. |
| Vobiz reports no route or no balance | The number is not linked, KYC is incomplete, or the balance is zero. | Complete Vobiz number activation and add the balance required by your account. Do not add funds without approval. |
| Agent joins but cannot hear the caller | The caller track is missing, the trunk is not matched, or the number format differs. | Confirm the number is E.164 on both sides and check LiveKit SIP participant events. |
| Groq returns 429 | Free-plan token or request limits were reached. | Wait for the quota reset, shorten the prompt and replies, or upgrade only with approval. |
| Deepgram returns 402 | The credit is exhausted or auto-reload is disabled. | Check the Deepgram console. Do not enable auto-reload without approval. |
| No speech from the agent | TTS key, provider name, or model is invalid. | Check the `provider_selected` and `session_error` logs. Test with the default Deepgram TTS. |
| `Address already in use` on port 8081 | Another agent process is running. | Stop the other process or change the worker port. |
| Next.js dashboard returns 503 | Dashboard credentials are not configured. | Set `DASHBOARD_USERNAME` and `DASHBOARD_PASSWORD`; the proxy fails closed by design. |
| Cloudflare dashboard returns 503 | D1 binding or schema is missing. | Replace the database ID, apply `schema.sql`, and redeploy. |
| Call record missing | SQLite path is not writable or the Cloudflare token is wrong. | Check the `call_record_failed` or `call_event_rejected` log. The call itself still completes. |
| macOS certificate errors | The Python environment is using unexpected certificates. | Use Python 3.12 from `uv`. Do not disable TLS verification. |

## Known limitations

- No real Vobiz call was placed while preparing this repository.
- Vobiz inbound availability, Indian number KYC, and India pricing depend on your account.
- Groq free-plan quotas can change and are not unlimited.
- Groq TTS is a preview with a low request quota.
- Groq Whisper is batch transcription, so it adds latency compared with Deepgram streaming.
- The agent uses LiveKit's default turn detection and interruption behavior.
  Tune it only after testing real callers.
- There is no application-level rate limiting or caller blocklist.
- There is no multi-tenant business directory or booking system.
- There is no call recording, transcript retention, or consent workflow.
- Transfer depends on Vobiz SIP REFER support.
- The Cloudflare Worker has no automated data-retention deletion.
- LiveKit Cloud Build allows one agent deployment on the free plan.
- SQLite on an ephemeral LiveKit Cloud container is not durable across redeploys.
  Use the Cloudflare dashboard as the durable call record.
- Inbound LiveKit room names include the caller's phone number.
- The optional Next.js dashboard uses Basic authentication, not individual user accounts.

## Files added and changed

Added:

- `providers.py`, `calls.py`, `telephony.py`, `logging_setup.py`.
- `setup_inbound.py`.
- `tests/` with 67 tests.
- `cloudflare/` with the Worker, D1 schema, 13 tests, and documentation.
- `proxy.ts` and `lib/validation.ts` in `dashboard/`.
- `COSTS.md`, `DEPLOYMENT.md`, `SECURITY.md`.
- `.dockerignore`.

Changed:

- `agent.py`: inbound and outbound worker, lifecycle, errors, records, cleanup.
- `config.py`: centralized validation and prompt construction.
- `requirements.txt`: pinned current LiveKit, Deepgram, OpenAI, and Groq-compatible dependencies.
- `requirements-dev.txt`: test dependencies.
- `.env.example`: complete safe template.
- `.gitignore`: local data, Cloudflare state, and test cache.
- `Dockerfile`, `docker-compose.yml`: Python 3.12, non-root user, named data volume, no host networking.
- `make_call.py`, `create_trunk.py`, `setup_trunk.py`, `list_trunks.py`: explicit LiveKit API clients, validation, no SSL workaround.
- `dashboard/` routes and components: Basic authentication, E.164 validation, generic errors, no duplicate outbound dialing.
- `README.md`, `transfer_call.md`, `dashboard/README.md`.

## Required manual configuration

Complete these before expecting a real call:

- LiveKit: create a project, copy the API credentials, confirm the SIP endpoint.
- LiveKit: run `setup_inbound.py` or create the inbound trunk and dispatch rule manually.
- Vobiz: create or open the SIP trunk, link the Indian number, complete KYC, set the inbound destination, and confirm balance.
- Groq: create a key and confirm `openai/gpt-oss-120b` is available to your account.
- Deepgram: create a key, confirm credit, and review auto-reload.
- Cloudflare: create the D1 database, apply the schema, set the three Worker secrets, deploy, and set the agent webhook URL and token.
- Optional: deploy the Next.js dashboard and set its Basic authentication credentials.

## First incoming call

1. Run `uv run python setup_inbound.py` and confirm the agent name is `receptionist`.
2. Set the Vobiz inbound destination to the printed SIP hostname without `sip:`.
3. Start `uv run python agent.py dev`.
4. Confirm the worker registers and stays running.
5. Dial the Vobiz number from another phone.
6. Listen for the greeting and answer the agent's question.
7. Check the log for `call_started`, `provider_selected`, and `call_finished`.
8. Hang up and confirm the outcome is `caller_hangup` or `completed`.
9. Check `data/calls.db` or the Cloudflare dashboard.
10. If the call fails, use the troubleshooting table and the LiveKit SIP logs.

## Verification sources

- LiveKit inbound SIP and dispatch: https://docs.livekit.io/telephony/
- LiveKit agent deployment: https://docs.livekit.io/deploy/agents/
- LiveKit pricing: https://livekit.io/pricing
- Vobiz LiveKit integration: https://www.vobiz.ai/docs/integrations/livekit
- Vobiz pricing: https://vobiz.ai/pricing
- Groq models: https://console.groq.com/docs/models
- Groq rate limits: https://console.groq.com/docs/rate-limits
- Groq speech to text: https://console.groq.com/docs/speech-to-text
- Groq text to speech: https://console.groq.com/docs/text-to-speech
- Deepgram pricing: https://deepgram.com/pricing
- Cloudflare Workers limits: https://developers.cloudflare.com/workers/platform/limits/
- Cloudflare D1 limits: https://developers.cloudflare.com/d1/platform/limits/
