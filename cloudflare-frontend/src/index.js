const FALLBACK_NUMBER = "+918064269449";
const E164 = /^\+[1-9]\d{7,14}$/;

function phoneNumber(env) {
  const candidate = (env?.INBOUND_NUMBER || "").trim();
  return E164.test(candidate) ? candidate : FALLBACK_NUMBER;
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[character]);
}

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json; charset=utf-8",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

function page(env) {
  const number = phoneNumber(env);
  const tel = `tel:${number}`;
  const siteName = escapeHtml(env?.SITE_NAME || "NOVI");

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${siteName} — AI phone receptionist</title>
<style>
:root { color-scheme: dark; font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; }
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 1.5rem; background: #080b12; color: #f5f7fb; }
main { width: min(100%, 42rem); padding: clamp(1.5rem, 5vw, 3rem); border: 1px solid #273043; border-radius: 1.25rem; background: linear-gradient(145deg, #101624, #0b0f18); box-shadow: 0 2rem 5rem rgb(0 0 0 / 45%); }
.eyebrow { margin: 0 0 0.75rem; color: #8ea4c8; font-size: 0.8rem; font-weight: 700; letter-spacing: 0.14em; text-transform: uppercase; }
h1 { margin: 0; font-size: clamp(2.5rem, 9vw, 4.5rem); line-height: 0.95; letter-spacing: -0.05em; }
.tagline { margin: 1rem 0 0; color: #c7d2e5; font-size: 1.05rem; line-height: 1.6; }
.call { display: inline-flex; align-items: center; justify-content: center; min-height: 3.5rem; margin-top: 2rem; padding: 0.9rem 1.4rem; border-radius: 0.8rem; background: #4f8cff; color: #07101f; font-size: 1.05rem; font-weight: 800; text-decoration: none; }
.call:hover, .call:focus-visible { background: #79a6ff; }
.number { margin: 1rem 0 0; color: #8ea4c8; font-variant-numeric: tabular-nums; }
.info { display: grid; gap: 0.8rem; margin: 2rem 0 0; padding-top: 1.5rem; border-top: 1px solid #273043; color: #aebbd0; font-size: 0.92rem; line-height: 1.6; }
.info p { margin: 0; }
a { color: inherit; }
@media (max-width: 30rem) { .call { width: 100%; } }
</style>
</head>
<body>
<main>
<p class="eyebrow">${siteName} · AI phone receptionist</p>
<h1>Call ${siteName}.</h1>
<p class="tagline">Speak naturally with an AI assistant. No app or account is required.</p>
<a class="call" href="${tel}" aria-label="Call ${siteName} at ${number}">Call ${siteName}</a>
<p class="number">${number}</p>
<div class="info">
<p>When you call, you speak with an AI assistant. It can answer general questions and help direct your request.</p>
<p>The assistant does not have access to private business systems in this deployment.</p>
</div>
</main>
</body>
</html>`;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (request.method === "GET" && url.pathname === "/health") {
      return json({ status: "ok" });
    }

    if (request.method !== "GET" || url.pathname !== "/") {
      return new Response("Not found", {
        status: 404,
        headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" },
      });
    }

    return new Response(page(env), {
      headers: {
        "Content-Type": "text/html; charset=utf-8",
        "Cache-Control": "public, max-age=300",
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
      },
    });
  },
};

export { phoneNumber };
