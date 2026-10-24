# Outbound dashboard

This Next.js app is the original outbound dialer.
It is optional.
The inbound receptionist runs on the LiveKit agent and the Cloudflare dashboard, not here.

## Security

`proxy.ts` protects the whole app with HTTP Basic authentication.
It fails closed when `DASHBOARD_USERNAME` or `DASHBOARD_PASSWORD` is missing.
Use HTTPS outside localhost.
The API routes validate E.164 numbers and do not return provider error details to the browser.

## Environment

Create `dashboard/.env.local`:

```dotenv
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
OUTBOUND_TRUNK_ID=...
AGENT_NAME=receptionist
DASHBOARD_USERNAME=...
DASHBOARD_PASSWORD=...
```

`OUTBOUND_TRUNK_ID` is required only for outbound calls.
`VOBIZ_SIP_TRUNK_ID` is accepted as a fallback.

## Run

```sh
npm ci
npm run dev
```

Production check:

```sh
npm run lint
npm run build
npm start
```

## Behavior

- `POST /api/dispatch` creates a room, passes outbound metadata, and creates one SIP participant.
- `POST /api/queue` accepts at most 50 unique E.164 numbers and dispatches them sequentially.
- The agent joins the room and does not dial a second time. The room metadata contains `"dial": false`.
- The model and voice selectors in the UI are legacy. The receptionist pipeline is configured on the agent through `.env`. Changing the dropdowns does not replace the agent's STT, LLM, or TTS providers.

## Deploy

Deploy this app only if you need outbound calls.
Vercel's free tier or a host you already use is sufficient.
The inbound dashboard is the Cloudflare Worker in `../cloudflare`.
