import test from "node:test";
import assert from "node:assert/strict";
import worker, { validateCall, parseLimit, constantTimeEqual, verifyBasicAuth } from "../src/index.js";

const payload = {
  call_id: "call-123",
  direction: "inbound",
  started_at: "2026-10-24T10:00:00Z",
  ended_at: "2026-10-24T10:01:00Z",
  duration_seconds: 60,
  outcome: "completed",
  summary: "The caller requested an appointment.",
  error: null,
  caller_number: "+15555550123",
};
const secrets = {
  CALL_EVENT_TOKEN: "event-test-token",
  DASHBOARD_USERNAME: "operator",
  DASHBOARD_PASSWORD: "test-password:with-colon",
};
const basic = "Basic " + Buffer.from(`${secrets.DASHBOARD_USERNAME}:${secrets.DASHBOARD_PASSWORD}`).toString("base64");

function fakeD1() {
  const statements = [];
  const calls = new Map();
  return {
    statements,
    calls,
    prepare(sql) {
      const statement = {
        sql,
        params: [],
        bind(...params) { this.params = params; return this; },
        async run() { calls.set(this.params[0], this.params); return { success: true }; },
        async all() { return { results: [{ ...payload }] }; },
        async first() { return { total_calls: 4, calls_today: 2, last_call_at: payload.started_at }; },
      };
      statements.push(statement);
      return statement;
    },
  };
}

function request(path, { authorization, body, method = "GET" } = {}) {
  const headers = {};
  if (authorization) headers.Authorization = authorization;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  return new Request(`https://receptionist.example${path}`, {
    method, headers, ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });
}

test("call validation accepts the contract and rejects invalid payloads", () => {
  assert.equal(validateCall(payload), null);
  for (const changed of [
    { ...payload, unknown: true },
    { ...payload, outcome: "busy" },
    Object.fromEntries(Object.entries(payload).filter(([key]) => key !== "call_id")),
    { ...payload, call_id: "" },
    { ...payload, summary: "a".repeat(2001) },
    { ...payload, started_at: "October 24, 2026" },
    { ...payload, started_at: "2026-02-30T10:00:00Z" },
    { ...payload, ended_at: "2026-10-24T10:01:00+01:00" },
    { ...payload, duration_seconds: -1 },
    { ...payload, duration_seconds: 86401 },
    { ...payload, duration_seconds: "60" },
    { ...payload, caller_number: "a".repeat(33) },
    { ...payload, error: false },
    [], null,
  ]) assert.equal(typeof validateCall(changed), "string");
});

test("POST requires the correct bearer token", async () => {
  for (const authorization of [undefined, "Bearer wrong-token", basic]) {
    const response = await worker.fetch(request("/api/calls", {
      method: "POST", body: payload, authorization,
    }), { ...secrets, DB: fakeD1() });
    assert.equal(response.status, 401);
  }
});

test("POST accepts a record and binds the expected values", async () => {
  const DB = fakeD1();
  const response = await worker.fetch(request("/api/calls", {
    method: "POST", body: payload, authorization: `Bearer ${secrets.CALL_EVENT_TOKEN}`,
  }), { ...secrets, DB });
  assert.equal(response.status, 202);
  assert.deepEqual(await response.json(), { accepted: true });
  assert.deepEqual(DB.statements[0].params.slice(0, 9), [
    "call-123", "inbound", "2026-10-24T10:00:00.000Z", "2026-10-24T10:01:00.000Z",
    60, "completed", payload.summary, null, "+15555550123",
  ]);
  assert.ok(Number.isFinite(Date.parse(DB.statements[0].params[9])));
});

test("POST rejects invalid and oversized bodies before database writes", async () => {
  const DB = fakeD1();
  for (const [body, status] of [
    [{ ...payload, unknown: true }, 400],
    [{ ...payload, summary: "a".repeat(9000) }, 413],
  ]) {
    const response = await worker.fetch(request("/api/calls", {
      method: "POST", body, authorization: `Bearer ${secrets.CALL_EVENT_TOKEN}`,
    }), { ...secrets, DB });
    assert.equal(response.status, status);
  }
  assert.equal(DB.statements.length, 0);
});

test("GET calls requires Basic auth and returns calls with clamped limits", async () => {
  const DB = fakeD1();
  const denied = await worker.fetch(request("/api/calls"), { ...secrets, DB });
  assert.equal(denied.status, 401);
  assert.equal(denied.headers.get("WWW-Authenticate"), 'Basic realm="Receptionist", charset="UTF-8"');
  for (const [limit, expected] of [["999", 100], ["0", 1], ["-20", 1], ["12", 12]]) {
    const response = await worker.fetch(request(`/api/calls?limit=${limit}`, { authorization: basic }), { ...secrets, DB });
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), { calls: [payload] });
    assert.equal(DB.statements.at(-1).params[0], expected);
  }
});

test("limit parsing uses a safe default", () => {
  assert.equal(parseLimit(null), 50);
  assert.equal(parseLimit("invalid"), 50);
  assert.equal(parseLimit(""), 50);
  assert.equal(parseLimit("12.5"), 12);
});

test("health is public and exposes only the health status", async () => {
  const response = await worker.fetch(request("/health"), secrets);
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { status: "ok" });
});

test("Basic auth fails closed when either credential is unset", async () => {
  for (const env of [{}, { DASHBOARD_USERNAME: "operator" }, { DASHBOARD_PASSWORD: "password" }]) {
    for (const path of ["/", "/api/status", "/api/calls"]) {
      const response = await worker.fetch(request(path, { authorization: basic }), env);
      assert.equal(response.status, 503);
    }
  }
});

test("Basic auth rejects incorrect and malformed credentials", async () => {
  for (const authorization of ["Basic !!!", "Basic " + btoa("operator:wrong"), "Basic " + btoa("wrong:test-password:with-colon")]) {
    const response = await verifyBasicAuth(request("/", { authorization }), secrets);
    assert.equal(response.status, 401);
  }
  assert.equal(await verifyBasicAuth(request("/", { authorization: basic }), secrets), null);
});

test("digest comparison accepts equal strings and rejects unequal strings", async () => {
  assert.equal(await constantTimeEqual("same", "same"), true);
  assert.equal(await constantTimeEqual("same", "different"), false);
  assert.equal(await constantTimeEqual("", "x"), false);
});

test("missing bearer secret fails closed", async () => {
  const response = await worker.fetch(request("/api/calls", {
    method: "POST", body: payload, authorization: "Bearer anything",
  }), { DB: fakeD1() });
  assert.equal(response.status, 503);
});

test("missing D1 returns a clear calls error and nullable status counts", async () => {
  const response = await worker.fetch(request("/api/calls", { authorization: basic }), secrets);
  assert.equal(response.status, 503);
  assert.match((await response.json()).error, /D1 binding DB/);
  const status = await worker.fetch(request("/api/status", { authorization: basic }), {
    ...secrets, AGENT_NAME: "Receptionist",
  });
  assert.equal(status.status, 200);
  const body = await status.json();
  assert.equal(body.AGENT_NAME, "Receptionist");
  assert.equal(body.total_calls, null);
  assert.equal(body.calls_today, null);
  assert.equal(body.last_call_at, null);
  assert.match(body.warning, /D1 binding DB/);
  for (const key of Object.keys(secrets)) assert.equal(Object.hasOwn(body, key), false);
});

test("status returns display values and D1 counts without secrets", async () => {
  const response = await worker.fetch(request("/api/status", { authorization: basic }), {
    ...secrets, DB: fakeD1(), INBOUND_NUMBER: "+15555550100", AGENT_NAME: "Receptionist",
    STT_PROVIDER: "STT", LLM_PROVIDER: "LLM", TTS_PROVIDER: "TTS", MAX_CALL_DURATION_SECONDS: "300",
  });
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), {
    INBOUND_NUMBER: "+15555550100", AGENT_NAME: "Receptionist", STT_PROVIDER: "STT",
    LLM_PROVIDER: "LLM", TTS_PROVIDER: "TTS", MAX_CALL_DURATION_SECONDS: "300",
    total_calls: 4, calls_today: 2, last_call_at: payload.started_at,
  });
});
