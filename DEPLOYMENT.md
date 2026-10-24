# Deployment

No deployment was performed while preparing this repository.
These steps require your LiveKit, Vobiz, Groq, Deepgram, and Cloudflare accounts.
Do not add funds or purchase services until you confirm the free allowances in `COSTS.md`.

## Deployment choices

| Component | Recommended target | Why |
| --- | --- | --- |
| Voice agent | LiveKit Cloud agent deployment, or Docker on a host you already have | The agent is a long-running Python worker with WebSocket media connections. It is not a request/response Worker. |
| Inbound routing | LiveKit inbound trunk and dispatch rule | LiveKit owns the SIP ingress and room creation. |
| Management dashboard | Cloudflare Worker with D1 | HTTP handling fits Workers; D1 stores the call records. |
| Optional outbound dashboard | Local Next.js server or Vercel | The Next.js app is a legacy outbound dialer. It is not needed for inbound calls. |

Do not deploy the Python voice agent to Cloudflare Workers.
Workers cannot host the long-running Python media process used by LiveKit Agents.
Cloudflare Containers could run a container, but they require a paid plan and add operational cost without improving the voice path.
LiveKit Cloud's Build plan includes the agent minutes needed for an initial inbound deployment.

## Prerequisites

- Python 3.12.
- `uv`.
- A LiveKit Cloud project.
- A Groq API key.
- A Deepgram API key, unless you explicitly switch both audio providers to Groq.
- A Vobiz account with an inbound-enabled number and active balance.
- A Cloudflare account for the optional dashboard.
- Node.js 22 or later for the Cloudflare Worker and the Next.js dashboard.

## Local setup

```sh
git clone https://github.com/toprmrproducer/LIvekitAIVoice.git
cd LIvekitAIVoice

uv venv --python 3.12
uv pip install -r requirements-dev.txt

cp .env.example .env
```

Edit `.env`.
Set at least:

```dotenv
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
LIVEKIT_SIP_URI=your-sip-subdomain.sip.livekit.cloud
GROQ_API_KEY=...
DEEPGRAM_API_KEY=...
VOBIZ_INBOUND_NUMBER=+91...
AGENT_NAME=receptionist
```

`LIVEKIT_SIP_URI` is the SIP host from **Settings > Project > SIP URI**, not the
project URL subdomain. Do not include the `sip:` prefix.

Validate the environment without starting a call:

```sh
uv run python -c "from config import get_settings; print(get_settings().redacted_summary())"
uv run python setup_inbound.py --dry-run
```

Run the automated tests:

```sh
uv run pytest
```

## LiveKit inbound routing

Create the inbound trunk and dispatch rule once:

```sh
uv run python setup_inbound.py
```

The script reuses an existing trunk for the number and an existing rule for the agent.
It does not delete anything.
Read its output.
It prints the SIP endpoint that Vobiz must use.

If you prefer the LiveKit dashboard, create an inbound trunk with:

```json
{
  "name": "AI receptionist inbound",
  "numbers": ["+91XXXXXXXXXX"],
  "allowed_addresses": ["0.0.0.0/0"],
  "krisp_enabled": true
}
```

Then create an individual dispatch rule with room prefix `call-` and this room configuration:

```json
{
  "agents": [
    {
      "agent_name": "receptionist",
      "metadata": "{\"direction\":\"inbound\"}"
    }
  ]
}
```

The agent name must match `AGENT_NAME` exactly.

For production, replace `0.0.0.0/0` with the Vobiz signalling addresses for your trunk.
Set `INBOUND_SIP_ALLOWED_ADDRESSES` before running `setup_inbound.py`.
If you leave it empty, the script creates the permissive default and prints a warning.

## Vobiz configuration

Use the Vobiz console or API.
The following steps follow Vobiz's official LiveKit integration guide.

1. Create a Vobiz SIP trunk.
   Copy the SIP domain, username, and password if you also want outbound calls.
   Inbound answering does not use those credentials.
2. Link your Indian number to the trunk.
   Complete the provider's KYC and number activation requirements.
3. Set the trunk's inbound destination to the LiveKit SIP endpoint printed by `setup_inbound.py`.
   Remove the `sip:` prefix.
   For example: `your-project.sip.livekit.cloud`.
4. Confirm the number is linked to the trunk and the trunk has an active balance.
5. If inbound calls do not arrive, ask Vobiz support to confirm that inbound routing is enabled for the number and trunk.

API form of the inbound destination update:

```http
PATCH https://api.vobiz.ai/api/v1/Account/{auth_id}/trunks/{trunk_id}
X-Auth-ID: {auth_id}
X-Auth-Token: {auth_token}
Content-Type: application/json

{"inbound_destination":"your-sip-subdomain.sip.livekit.cloud"}
```

Do not put the Vobiz auth token in source code, logs, or this repository.

## Run the agent locally

Development mode reloads on file changes:

```sh
uv run python agent.py dev
```

Production mode:

```sh
uv run python agent.py start
```

The worker connects outbound to LiveKit.
It does not need a public HTTP port or a tunnel.
The LiveKit worker health server listens on port 8081 inside the process.

## Deploy the agent to LiveKit Cloud

Install the LiveKit CLI from the official instructions at https://docs.livekit.io/reference/developer-tools/livekit-cli/.
Then authenticate:

```sh
lk cloud auth
lk project list
lk project set-default "your-project-name"
```

Create a deployment-only environment file.
Do not include `LIVEKIT_URL`, `LIVEKIT_API_KEY`, or `LIVEKIT_API_SECRET`; LiveKit Cloud injects them automatically.

```dotenv
GROQ_API_KEY=...
DEEPGRAM_API_KEY=...
AGENT_NAME=receptionist
LLM_PROVIDER=groq
GROQ_MODEL=openai/gpt-oss-120b
STT_PROVIDER=deepgram
TTS_PROVIDER=deepgram
STT_LANGUAGE=multi
MAX_CALL_DURATION_SECONDS=600
CALL_SUMMARY_ENABLED=false
STORE_CALLER_NUMBER=false
NOISE_CANCELLATION=true
LOG_LEVEL=INFO
LOG_FORMAT=json
CALL_EVENT_WEBHOOK_URL=https://your-worker.example.workers.dev/api/calls
CALL_EVENT_WEBHOOK_TOKEN=the-same-token-you-set-in-the-worker
```

Deploy:

```sh
lk agent create --secrets-file ./deploy.env
lk agent status
lk agent logs
```

The command creates a `livekit.toml` with the deployment ID and builds the root `Dockerfile`.
It may ask for a deployment name.
Use `receptionist` so the dispatch name in the code and the deployment name agree.

To update an existing deployment:

```sh
lk agent update-secrets --secrets-file ./deploy.env
lk agent deploy
```

The Build plan includes one agent deployment and 1,000 agent minutes per month.
Do not add a payment method or upgrade a plan without explicit approval.

If the deployment fails because the container is unhealthy, check `lk agent logs` and confirm that `python agent.py start` is the container command.
The root `Dockerfile` already sets that command.

## Deploy the agent with Docker

Use this option on a host you already pay for, or on a free-tier VM you control.

```sh
cp .env.example .env
# Edit .env with real values.
docker compose up -d --build
docker compose logs -f voice-agent
```

The compose file uses a named volume for SQLite.
It does not use host networking.
The agent makes outbound connections to LiveKit and the AI providers.
Stop it with:

```sh
docker compose down
```

The SQLite records stay in the named volume.
The call-event webhook is the durable record if you deploy to an ephemeral container.

## Deploy the Cloudflare dashboard

The Worker stores call records in D1 and serves a password-protected dashboard.
It does not answer calls.

```sh
cd cloudflare
npx wrangler@latest login
npx wrangler@latest d1 create receptionist-calls
```

Replace `REPLACE_WITH_D1_DATABASE_ID` in `cloudflare/wrangler.toml` with the returned database ID.
Set the display values under `[vars]`.

```sh
npx wrangler@latest d1 execute receptionist-calls --remote --file=schema.sql
npx wrangler@latest secret put CALL_EVENT_TOKEN
npx wrangler@latest secret put DASHBOARD_USERNAME
npx wrangler@latest secret put DASHBOARD_PASSWORD
npx wrangler@latest deploy
```

The Worker prints its URL.
Open it and enter the dashboard username and password in the browser prompt.

Set the same call-event token on the agent:

```dotenv
CALL_EVENT_WEBHOOK_URL=https://your-worker.example.workers.dev/api/calls
CALL_EVENT_WEBHOOK_TOKEN=the-token-from-the-worker
```

Test the Worker locally:

```sh
cd cloudflare
npm test
```

Cloudflare's Workers Free plan currently allows 100,000 requests per day and 10 ms CPU per request.
Check the current D1 free limits at https://developers.cloudflare.com/d1/platform/limits/ before you rely on them.

## Optional Next.js outbound dashboard

The Next.js app dispatches outbound calls.
It is protected by HTTP Basic authentication.
It fails closed when `DASHBOARD_USERNAME` or `DASHBOARD_PASSWORD` is missing.

```sh
cd dashboard
npm ci
```

Create `dashboard/.env.local` with:

```dotenv
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
OUTBOUND_TRUNK_ID=...
AGENT_NAME=receptionist
DASHBOARD_USERNAME=...
DASHBOARD_PASSWORD=...
```

Run it locally:

```sh
npm run dev
```

Production build:

```sh
npm run lint
npm run build
npm start
```

Deploy this app only if you need outbound dialing.
It is not part of the inbound call path.
Vercel's free tier or a host you already use is sufficient.
Deploying Next.js to Cloudflare Workers requires an additional OpenNext adapter and is not included here; the Cloudflare Worker dashboard already covers inbound call records.

## First-call test procedure

1. Run `uv run python setup_inbound.py` and confirm the dispatch rule targets `receptionist`.
2. Set the Vobiz inbound destination to the SIP host from LiveKit **Settings > Project > SIP URI**, without `sip:` or the project URL subdomain.
3. Start the agent with `uv run python agent.py dev`.
4. Confirm the worker registers with LiveKit and the process stays running.
5. Run `uv run python diagnose_inbound.py` and confirm the trunk/rule checks pass.
6. Call the Vobiz number from a different phone.
7. Listen for the greeting. Say a short sentence, then answer the agent's question.
8. Watch the agent log for `job_received`, `call_started`, `provider_selected`, and `call_finished`.
9. Hang up and confirm the log contains `outcome=caller_hangup` or `completed`.
10. Confirm a row exists:
   ```sh
   uv run python -c "from calls import CallStore; print(CallStore('data/calls.db').recent())"
   ```
11. If the Cloudflare webhook is configured, refresh the dashboard and confirm the call appears.

Do not claim a real call succeeded until you complete these steps.
The automated tests in this repository use mocked providers and do not dial a telephone number.

## Verification checklist

```sh
uv run python -m pytest
uv run python -m compileall -q agent.py config.py calls.py providers.py telephony.py logging_setup.py setup_inbound.py
cd dashboard && npm run lint && npm run build
cd ../cloudflare && npm test
```

Record the actual output in your deployment notes.
