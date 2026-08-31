// The zustand store, on bare node -- no React, no DOM, no dependencies. This
// is where the state logic the UI only reflects actually lives: the JSON-mode
// toggle, submit, the open-row set, and what does and does not survive a
// refresh. `npm test` in frontend/ runs it.
import assert from "node:assert/strict";
import { beforeEach, test } from "node:test";

// store.js -> api.js reads `location` at import time and `fetch` at call time.
const saved = new Map();
globalThis.localStorage = {
  getItem: (k) => (saved.has(k) ? saved.get(k) : null),
  setItem: (k, v) => saved.set(k, v),
  removeItem: (k) => saved.delete(k),
};
globalThis.location = { port: "8000" };

const { useStore, BLANK_DRAFT } = await import("../frontend/src/store.js");

const fresh = useStore.getState();
beforeEach(() => {
  saved.clear();
  useStore.setState(fresh, true);
});

// --- the JSON-mode toggle ----------------------------------------------------

test("switching to JSON mode fills the textarea from the rows", () => {
  const s = useStore.getState();
  s.patchDraft({ fields: [{ name: "title", type: "string", required: true }] });
  s.toggleJsonMode();

  const { draft, formError } = useStore.getState();
  assert.equal(formError, null);
  assert.equal(draft.jsonMode, true);
  assert.deepEqual(JSON.parse(draft.jsonText), {
    type: "object",
    properties: { title: { type: "string" } },
    required: ["title"],
  });
});

test("switching back fills the rows from the textarea", () => {
  const s = useStore.getState();
  s.patchDraft({
    jsonMode: true,
    jsonText: '{"type":"object","properties":{"price":{"type":"number"}}}',
  });
  s.toggleJsonMode();

  const { draft } = useStore.getState();
  assert.equal(draft.jsonMode, false);
  assert.deepEqual(draft.fields, [{ name: "price", type: "number", required: false }]);
});

test("broken JSON reports the parse error and stays in JSON mode", () => {
  const s = useStore.getState();
  s.patchDraft({ jsonMode: true, jsonText: "{not json" });
  s.toggleJsonMode();

  const { draft, formError } = useStore.getState();
  assert.equal(draft.jsonMode, true, "must not drop what the user typed");
  assert.match(formError, /not valid JSON/);
});

test("a nested schema stays in JSON mode rather than losing its shape", () => {
  const s = useStore.getState();
  s.patchDraft({
    jsonMode: true,
    jsonText: '{"type":"object","properties":{"seller":{"type":"object"}}}',
  });
  s.toggleJsonMode();

  assert.equal(useStore.getState().draft.jsonMode, true);
  assert.match(useStore.getState().formError, /nested or unsupported/);
});

// --- submit ------------------------------------------------------------------

test("submitting posts the built schema and starts watching the job", async () => {
  let sent = null;
  globalThis.fetch = async (url, init) => {
    sent = { url, body: JSON.parse(init.body) };
    return { ok: true, json: async () => ({ job_id: "job-1" }) };
  };

  const s = useStore.getState();
  s.patchDraft({ url: "https://shop.test", prompt: "get the shoes" });
  await s.submitJob();

  assert.match(sent.url, /\/jobs$/);
  assert.equal(sent.body.url, "https://shop.test");
  assert.equal(sent.body.json_schema.properties.title.type, "string");
  assert.equal(useStore.getState().jobId, "job-1");
  assert.equal(useStore.getState().posting, false);
});

test("a 422 surfaces the API's own body, and no job is watched", async () => {
  globalThis.fetch = async () => ({
    ok: false,
    json: async () => ({ detail: [{ loc: ["body", "url"], msg: "bad scheme" }] }),
  });

  await useStore.getState().submitJob();

  assert.equal(useStore.getState().jobId, null);
  assert.match(useStore.getState().formError, /bad scheme/);
});

test("a schema with no fields never reaches the API", async () => {
  let called = false;
  globalThis.fetch = async () => {
    called = true;
    return { ok: true, json: async () => ({}) };
  };

  useStore.getState().patchDraft({ fields: [] });
  await useStore.getState().submitJob();

  assert.equal(called, false);
  assert.match(useStore.getState().formError, /at least one field/);
});

// --- browse ------------------------------------------------------------------

test("toggling a row adds it, toggling again removes it", () => {
  const { toggleRow } = useStore.getState();
  toggleRow("jobs:abc");
  assert.deepEqual(useStore.getState().openRows, { "jobs:abc": true });
  toggleRow("jobs:abc");
  assert.deepEqual(useStore.getState().openRows, {});
});

test("a cached tab is not fetched twice, and Refresh drops the cache", async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    return { ok: true, json: async () => [{ id: "a" }] };
  };

  await useStore.getState().loadTab("jobs");
  await useStore.getState().loadTab("jobs");
  assert.equal(calls, 1);
  assert.deepEqual(useStore.getState().rows.jobs, [{ id: "a" }]);

  useStore.getState().refreshBrowse();
  assert.equal(useStore.getState().rows.jobs, undefined);
  await useStore.getState().loadTab("jobs");
  assert.equal(calls, 2);
});

test("an unreachable API leaves a readable message, not an empty table", async () => {
  globalThis.fetch = async () => {
    throw new Error("connection refused");
  };

  await useStore.getState().loadTab("jobs");

  assert.equal(useStore.getState().rows.jobs, undefined);
  assert.match(useStore.getState().browseError, /connection refused/);
});

// --- what survives a refresh -------------------------------------------------

test("the draft, the view and the watched job id are persisted", () => {
  const s = useStore.getState();
  s.patchDraft({ url: "https://shop.test", prompt: "get the shoes" });
  s.setPage("browse");
  s.setBrowseTab("scripts");
  s.toggleRow("scripts:xyz");
  useStore.setState({ jobId: "job-1" });

  const kept = JSON.parse(saved.get("scarper")).state;
  assert.equal(kept.draft.url, "https://shop.test");
  assert.equal(kept.page, "browse");
  assert.equal(kept.browseTab, "scripts");
  assert.deepEqual(kept.openRows, { "scripts:xyz": true });
  assert.equal(kept.jobId, "job-1");
});

test("fetched rows and the polled job are deliberately not persisted", async () => {
  globalThis.fetch = async () => ({ ok: true, json: async () => [{ id: "a" }] });
  await useStore.getState().loadTab("jobs");
  useStore.getState().setJob({ status: "done", result: [{ title: "x" }] });

  // A cache that outlived the page would show yesterday's jobs; `jobId` comes
  // back instead and the poller refetches.
  const kept = JSON.parse(saved.get("scarper")).state;
  assert.equal("rows" in kept, false);
  assert.equal("job" in kept, false);
});

test("dismiss clears the job but leaves the draft alone", () => {
  const s = useStore.getState();
  s.patchDraft({ url: "https://shop.test" });
  useStore.setState({ jobId: "job-1", job: { status: "done" } });

  useStore.getState().clearJob();

  assert.equal(useStore.getState().jobId, null);
  assert.equal(useStore.getState().job, null);
  assert.equal(useStore.getState().draft.url, "https://shop.test");
});

// --- derived selectors -------------------------------------------------------

test("busy covers posting, a job with no status yet, and a running one", async () => {
  const { selectBusy } = await import("../frontend/src/store.js");

  assert.equal(selectBusy({ posting: true, jobId: null, job: null }), true);
  assert.equal(selectBusy({ posting: false, jobId: "j", job: null }), true);
  assert.equal(selectBusy({ posting: false, jobId: "j", job: { status: "running" } }), true);
  assert.equal(selectBusy({ posting: false, jobId: "j", job: { status: "done" } }), false);
  assert.equal(selectBusy({ posting: false, jobId: null, job: null }), false);
});

test("the attempt line tells a replay apart from a generation", async () => {
  const { selectAttemptLine } = await import("../frontend/src/store.js");

  assert.equal(selectAttemptLine({ job: null }), null);
  assert.equal(selectAttemptLine({ job: { attempts: 2, replayed: false } }), "attempt 2 / 3");
  // Attempt 0 is the replay itself, so it spent no generation.
  assert.equal(
    selectAttemptLine({ job: { attempts: 1, replayed: true } }),
    "replayed a saved script",
  );
  // The replay was stale and one generation followed it.
  assert.equal(
    selectAttemptLine({ job: { attempts: 2, replayed: true } }),
    "saved script was stale, attempt 1 / 3",
  );
});

test("a fresh draft is the example, not an empty form", () => {
  assert.equal(BLANK_DRAFT.fields.length > 0, true);
  assert.equal(BLANK_DRAFT.jsonMode, false);
});
