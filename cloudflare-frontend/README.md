# NOVI public frontend

A small public landing page hosted on Cloudflare Workers.
It shows a call button for the NOVI phone number and does not handle audio.

The voice agent remains on LiveKit Cloud or Docker.
Cloudflare Workers cannot host the Python media process.

## Local checks

```sh
cd cloudflare-frontend
npm test
node --check src/index.js
```

Local preview:

```sh
npx wrangler@latest dev --local
```

## Deploy

Authenticate the Cloudflare CLI without putting an API token in the repository:

```sh
npx wrangler@latest login
```

Deploy the new Worker:

```sh
cd cloudflare-frontend
npx wrangler@latest deploy
```

Wrangler prints the public `*.workers.dev` URL.
The Worker name is `novi-frontend`.

## Configuration

Edit `wrangler.toml`:

```toml
[vars]
SITE_NAME = "NOVI"
INBOUND_NUMBER = "+918064269449"
```

The number must be E.164.
The fallback number is `+918064269449`.

## Security

The page has no forms, no cookies, no browser JavaScript, and no external assets.
It uses a restrictive Content Security Policy and does not expose any API keys.
The `Call NOVI` link opens the device's phone dialer with a `tel:` URI.

The Worker does not place calls, issue LiveKit tokens, or store call data.
