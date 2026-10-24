import test from "node:test";
import assert from "node:assert/strict";

import worker, { phoneNumber } from "../src/index.js";

test("phone number configuration accepts E.164 and rejects invalid values", () => {
  assert.equal(phoneNumber({ INBOUND_NUMBER: "+918064269449" }), "+918064269449");
  assert.equal(phoneNumber({ INBOUND_NUMBER: "not-a-number" }), "+918064269449");
  assert.equal(phoneNumber({}), "+918064269449");
});

test("landing page contains a callable number and security headers", async () => {
  const response = await worker.fetch(
    new Request("https://novi.example/"),
    { SITE_NAME: "NOVI", INBOUND_NUMBER: "+918064269449" },
  );
  const body = await response.text();

  assert.equal(response.status, 200);
  assert.match(response.headers.get("Content-Type"), /text\/html/);
  assert.match(body, /href="tel:\+918064269449"/);
  assert.match(body, /Call NOVI/);
  assert.match(response.headers.get("Content-Security-Policy"), /default-src 'none'/);
  assert.equal(response.headers.get("X-Content-Type-Options"), "nosniff");
});

test("health endpoint returns only the health status", async () => {
  const response = await worker.fetch(
    new Request("https://novi.example/health"),
    { SITE_NAME: "NOVI", INBOUND_NUMBER: "+918064269449" },
  );

  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { status: "ok" });
});

test("unknown paths return 404", async () => {
  const response = await worker.fetch(
    new Request("https://novi.example/unknown"),
    { SITE_NAME: "NOVI", INBOUND_NUMBER: "+918064269449" },
  );

  assert.equal(response.status, 404);
});

test("HTML escapes the configured site name", async () => {
  const response = await worker.fetch(
    new Request("https://novi.example/"),
    { SITE_NAME: "<script>", INBOUND_NUMBER: "+918064269449" },
  );
  const body = await response.text();

  assert.doesNotMatch(body, /<script>/);
  assert.match(body, /&lt;script&gt;/);
});
