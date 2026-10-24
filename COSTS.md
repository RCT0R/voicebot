# Cost matrix

Verified on 2026-10-24 against the providers' public documentation.
Prices and quotas change. Check the linked pages and your provider console before you rely on them.

## Summary

The software is free to run locally.
Telephone service is not free.
Deepgram is a credit that runs out.
Groq free-tier quotas are limited and can change.
LiveKit Build includes a monthly allowance, not unlimited usage.

Do not describe the whole system as free.
The unavoidable recurring cost is the Vobiz number and inbound minutes.
The main variable cost after the free allowances is Deepgram speech synthesis.

## Components

| Component | Selected option | Classification | Verified limit or price | Notes |
| --- | --- | --- | --- | --- |
| Language model | Groq `openai/gpt-oss-120b` | Free within a documented quota | Free plan: 30 RPM, 1,000 requests/day, 8,000 tokens/minute, 200,000 tokens/day. Developer plan price: $0.15 per 1M input tokens and $0.60 per 1M output tokens. | Keep replies short. Long call histories can hit the 8,000 tokens/minute limit. |
| Speech recognition | Deepgram Nova-3 streaming | Free within a credit, then paid | $200 signup credit with no expiry. Nova-3 streaming: $0.0048/min monolingual (promotional; $0.29/hour), $0.0058/min multilingual ($0.35/hour). | This project keeps the existing Deepgram integration. Streaming STT has lower latency than Groq Whisper. |
| Speech synthesis | Deepgram Aura-2 | Free within a credit, then paid | $0.030 per 1,000 characters. | Per-call cost depends on how much the agent says. Short answers matter. |
| Alternative speech recognition | Groq `whisper-large-v3-turbo` | Free within a documented quota | Free plan: 20 RPM, 2,000 requests/day, 7,200 audio seconds/hour, 28,800 audio seconds/day. Paid: $0.04 per audio hour. | Batch transcription, not a continuous stream. Expect higher turn latency. |
| Alternative speech synthesis | Groq `canopylabs/orpheus-v1-english` | Free within a small preview quota | Free plan: 10 RPM, 100 requests/day, 1,200 tokens/minute, 3,600 tokens/day. Listed at $22 per 1M characters. | Preview model. 100 requests/day is about 100 spoken replies, not 100 calls. Not suitable as a production default. |
| Voice infrastructure | LiveKit Cloud Build | Free within a documented quota | $0/month. 1,000 agent session minutes, 1,000 third-party SIP minutes, 5,000 WebRTC minutes, 1 agent deployment, 5 concurrent sessions, 1 free LiveKit number. | Third-party SIP overage is $0.004/min. Agent session overage is $0.01/min. The free LiveKit number is not your Vobiz number. |
| Telephone number | Vobiz Indian number | Unverified; requires checking your account (paid or trial-limited) | Number rental and inbound rates are country-specific. The public page shows US local inbound at $0.0055/min and $1.00/month rental. India rates were not available in the page served to this environment. | Vobiz's LiveKit guide requires an account with active balance. Indian numbers require KYC. Trial inbound is not guaranteed. Check the Vobiz console. |
| Inbound telephone minutes | Vobiz | Paid | Per-minute inbound rate for your country and route. | This is the unavoidable PSTN cost. It is not a free API tier. |
| Agent hosting | LiveKit Cloud agent deployment | Free within the Build allowance | Included in the 1,000 agent session minutes. | The alternative is a Docker host or a free-tier VM that you already have. |
| Alternative agent hosting | Docker on a host you control | Free if the host is already available; otherwise paid | Depends on the host. | Use this if you do not want to deploy to LiveKit Cloud. The repository includes a Dockerfile and compose file. |
| Management dashboard | Cloudflare Workers + D1 | Free within documented quotas | Workers Free: 100,000 requests/day and 10 ms CPU per request. D1 has separate free storage, read, and write quotas. | The Worker is stateless apart from D1. It does not run the voice agent. |
| Local call records | SQLite file | Free, local | No service cost. | Disable caller-number storage unless you need it. |
| Audio recording | Not used | Free because disabled | No egress or storage configured. | `record=False` and no transcript storage. |
| Logs | Container stdout or LiveKit Cloud logs | Included | Depends on the host. | No paid logging service is configured. |

## Free and paid boundaries

Free with limits:

- Groq language-model inference within the free-plan quotas.
- LiveKit Build agent minutes and third-party SIP minutes within the monthly allowance.
- Cloudflare Workers and D1 within the free-plan quotas.
- Local SQLite storage.

Free only until a credit runs out:

- Deepgram speech recognition and synthesis after the $200 credit is consumed.
- LiveKit allowances after the monthly quota is consumed.

Paid and unavoidable for a real phone number:

- Vobiz number rental.
- Vobiz inbound minutes.
- Any KYC or compliance fee charged by the provider.

Paid if you exceed a free allowance:

- Groq after upgrading to the Developer plan, or if you use a paid model.
- LiveKit after the monthly agent or SIP minutes.
- Cloudflare after the free plan quotas.
- Any Docker host that is not already free for you.

## Worked example

This example assumes a five-minute inbound call with about 1,500 characters of speech synthesis and eight LLM turns.
It is an estimate, not a quote.

| Item | Calculation | Cost after free allowances |
| --- | --- | --- |
| LiveKit agent session | 5 minutes at $0.01/min after 1,000 included minutes | $0.050 |
| LiveKit third-party SIP | 5 minutes at $0.004/min after 1,000 included minutes | $0.020 |
| Deepgram STT | 5 minutes at $0.0048/min | $0.024 |
| Deepgram TTS | 1,500 characters at $0.030/1,000 | $0.045 |
| Groq LLM | About 6,400 tokens at the listed Developer plan rates | about $0.001 |
| Cloudflare | One call event and a few dashboard requests | $0.00 within the free quota |
| Vobiz | Five inbound minutes plus monthly rental | Account-specific; check the console |

Estimated marginal cost after the free allowances: about $0.14 per five-minute call, plus Vobiz inbound minutes and number rental.
Deepgram and LiveKit allowances cover the first 1,000 minutes of agent and SIP usage, so the first 200 five-minute calls are close to $0 in platform fees.
The Vobiz number and minutes still apply.

## Cost controls in this project

- Replies are limited to one or two short sentences in the system prompt.
- Call summaries are disabled by default to avoid an extra LLM request.
- Transcripts and recordings are not stored.
- The maximum call duration defaults to 600 seconds.
- The LLM output is capped at 200 completion tokens by default.
- The SIP trunk has a hard duration limit 30 seconds above the agent limit.
- The agent does not retry failed outbound calls.
- The Cloudflare dashboard does not use a paid database service.
- Deepgram auto-reload is a provider setting. Check it in the Deepgram console and disable it if you do not want automatic credit purchases.

## Sources

- Groq supported models: https://console.groq.com/docs/models
- Groq rate limits: https://console.groq.com/docs/rate-limits
- Groq speech to text: https://console.groq.com/docs/speech-to-text
- Groq text to speech: https://console.groq.com/docs/text-to-speech
- Deepgram pricing: https://deepgram.com/pricing
- LiveKit pricing: https://livekit.io/pricing
- Vobiz pricing: https://vobiz.ai/pricing
- Vobiz LiveKit integration: https://www.vobiz.ai/docs/integrations/livekit
- Cloudflare Workers limits: https://developers.cloudflare.com/workers/platform/limits/
- Cloudflare D1 limits: https://developers.cloudflare.com/d1/platform/limits/
