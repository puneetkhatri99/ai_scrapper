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

// --- surviving a deploy ------------------------------------------------------

test("a draft persisted before a field existed still renders", async () => {
  // Exactly what a browser that used the previous build has in localStorage.
  saved.set(
    "scarper",
    JSON.stringify({
      version: 1,
      state: { page: "new", draft: { url: "u", prompt: "p", fields: [], jsonMode: false } },
    }),
  );
  await useStore.persist.rehydrate();

  const { draft } = useStore.getState();
  assert.equal(draft.url, "u");                 // what was stored is kept
  assert.equal(draft.script, "");               // what is new is filled in
  assert.equal(draft.name, "");
  assert.equal(typeof draft.script.trim(), "string");
});

// --- running a script in the sandbox -----------------------------------------

test("Edit & run fills the form with the script and posts nothing", async () => {
  let called = false;
  globalThis.fetch = async () => {
    called = true;
    return { ok: true, json: async () => ({}) };
  };

  useStore.getState().loadJob(
    {
      url: "https://shop.test",
      prompt: "get the shoes",
      json_schema: { type: "object", properties: { title: { type: "string" } } },
      name: "Shoes",
    },
    "def run(page):\n    return []",
  );

  assert.equal(called, false);
  const { draft, page } = useStore.getState();
  assert.equal(page, "new");
  assert.equal(draft.name, "Shoes");
  assert.equal(draft.script, "def run(page):\n    return []");
  assert.deepEqual(draft.fields, [{ name: "title", type: "string", required: false }]);
});

test("a script in the box is posted with the job", async () => {
  let sent = null;
  globalThis.fetch = async (url, init) => {
    sent = JSON.parse(init.body);
    return { ok: true, json: async () => ({ job_id: "job-1" }) };
  };

  const s = useStore.getState();
  s.patchDraft({ url: "https://shop.test", prompt: "x", script: "def run(page): return []" });
  await s.submitJob();

  assert.equal(sent.script, "def run(page): return []");
});

// --- renaming ----------------------------------------------------------------

test("a rename patches the job, the watched job and the browse row", async () => {
  let sent = null;
  globalThis.fetch = async (url, init) => {
    sent = { url, method: init.method, body: JSON.parse(init.body) };
    return { ok: true, json: async () => ({ name: "Shoe prices" }) };
  };

  useStore.setState({
    job: { id: "job-1", status: "done" },
    rows: { jobs: [{ id: "job-0" }, { id: "job-1" }] },
  });
  const error = await useStore.getState().renameJob("job-1", "  Shoe prices  ");

  assert.equal(error, null);
  assert.equal(sent.method, "PATCH");
  assert.match(sent.url, /\/jobs\/job-1$/);
  assert.equal(sent.body.name, "  Shoe prices  ");

  // The server's normalised name is what lands, in both places that show it.
  const { job, rows } = useStore.getState();
  assert.equal(job.name, "Shoe prices");
  assert.deepEqual(rows.jobs, [{ id: "job-0" }, { id: "job-1", name: "Shoe prices" }]);
});

test("a failed rename is returned, not swallowed, and changes nothing", async () => {
  globalThis.fetch = async () => ({
    ok: false,
    json: async () => ({ detail: "too long" }),
  });

  useStore.setState({ job: { id: "job-1", name: "old" } });
  const error = await useStore.getState().renameJob("job-1", "x".repeat(200));

  assert.match(error, /too long/);
  assert.equal(useStore.getState().job.name, "old");
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

test("the theme starts light, switches, and outlives a refresh", () => {
  assert.equal(useStore.getState().theme, "light");

  useStore.getState().setTheme("dark");

  assert.equal(useStore.getState().theme, "dark");
  // main.jsx is what puts it on <html>; the store only has to remember it.
  assert.equal(JSON.parse(saved.get("scarper")).state.theme, "dark");
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
  // Attempt 0 is a script nobody generated for this job -- the saved one
  // replayed, or one supplied with the submit. Neither spent a generation.
  assert.equal(
    selectAttemptLine({ job: { attempts: 1, replayed: true } }),
    "ran an existing script, no generation",
  );
  // It failed and one generation followed it.
  assert.equal(
    selectAttemptLine({ job: { attempts: 2, replayed: true } }),
    "that script failed, attempt 1 / 3",
  );
});

test("a fresh draft is the example, not an empty form", () => {
  assert.equal(BLANK_DRAFT.fields.length > 0, true);
  assert.equal(BLANK_DRAFT.jsonMode, false);
});

// --- re-running a job --------------------------------------------------------

test("re-running loads the inputs into the form and posts them", async () => {
  let sent = null;
  globalThis.fetch = async (url, init) => {
    sent = JSON.parse(init.body);
    return { ok: true, json: async () => ({ job_id: "job-9" }) };
  };

  await useStore.getState().runAgain({
    url: "https://shop.test/deals",
    prompt: "get the deals",
    json_schema: {
      type: "object",
      properties: { sku: { type: "string" } },
      required: ["sku"],
    },
  });

  const { draft, jobId, page } = useStore.getState();
  assert.deepEqual(sent.json_schema.properties, { sku: { type: "string" } });
  assert.equal(sent.url, "https://shop.test/deals");
  assert.equal(jobId, "job-9");
  // The form shows what is running, so the next run can be an edit of it.
  assert.equal(draft.url, "https://shop.test/deals");
  assert.deepEqual(draft.fields, [{ name: "sku", type: "string", required: true }]);
  assert.equal(draft.jsonMode, false);
  assert.equal(page, "new");
});

test("re-running a schema the rows cannot show falls back to JSON mode", async () => {
  const nested = {
    type: "object",
    properties: { seller: { type: "object", properties: { name: { type: "string" } } } },
  };
  globalThis.fetch = async () => ({ ok: true, json: async () => ({ job_id: "job-10" }) });

  await useStore.getState().runAgain({ url: "https://x.test", prompt: "p", json_schema: nested });

  const { draft } = useStore.getState();
  assert.equal(draft.jsonMode, true);
  assert.deepEqual(JSON.parse(draft.jsonText), nested);
});

// --- companies: the broker list and the two batch buttons --------------------

/** Answers every request; records what was asked for. */
function stubApi(routes) {
  const seen = [];
  globalThis.fetch = async (url, init = {}) => {
    const method = init.method ?? "GET";
    seen.push({ method, url, body: init.body ? JSON.parse(init.body) : null });
    // The API base is "" on port 8000, so `url` is a bare path here.
    const path = String(url).split("?")[0];
    const hit = routes[method + " " + path] ?? routes[method] ?? { ok: true };
    return { ok: hit.ok !== false, status: hit.status ?? 200, json: async () => hit.body ?? {} };
  };
  return seen;
}

test("editing a company PUTs it and reloads the table", async () => {
  const seen = stubApi({
    "GET /companies": { body: [{ id: "co-1", name: "Renamed" }] },
    "PUT /companies/co-1": { body: { id: "co-1" } },
  });

  const problem = await useStore.getState().saveCompany({ id: "co-1", name: "Renamed" });

  assert.equal(problem, null);
  assert.equal(seen[0].method, "PUT");
  assert.equal(seen[0].body.name, "Renamed");
  // The reload is what makes the officer count and last run catch up.
  assert.equal(seen[1].method, "GET");
  assert.deepEqual(useStore.getState().companyRows, [{ id: "co-1", name: "Renamed" }]);
});

test("a rejected company comes back verbatim and the table is not reloaded", async () => {
  const seen = stubApi({
    "POST /companies": { ok: false, status: 422, body: { detail: "url scheme must be http" } },
  });

  const problem = await useStore.getState().addCompany({ name: "x", company_url: "ftp://x" });

  assert.match(problem, /url scheme must be http/); // rules.md G28: the real error
  assert.equal(seen.length, 1, "nothing to reload, the write did not happen");
  assert.equal(useStore.getState().companyRows, null);
});

test("starting a run follows it to the end and refreshes the rows", async () => {
  const progress = [
    { running: true, phase: "run", done: 1, total: 2, current: "Cross Country" },
    { running: false, phase: null, done: 2, total: 2, current: null },
  ];
  const seen = stubApi({
    "POST /companies/run": { body: { started: "run_all" } },
    "GET /companies/run": { get body() { return progress.shift(); } },
    "GET /companies": { body: [{ id: "co-1", officers: 12 }] },
  });

  await useStore.getState().startBatch("run");
  // pollRun is fire-and-forget from startBatch; let its two ticks land.
  while (useStore.getState().runPolling) await new Promise((r) => setTimeout(r, 5));

  assert.deepEqual(useStore.getState().runProgress, { running: false, phase: null, done: 2, total: 2, current: null });
  assert.deepEqual(useStore.getState().companyRows, [{ id: "co-1", officers: 12 }]);
  assert.equal(seen.filter((s) => s.url.endsWith("/companies")).length, 2,
    "refreshed while running, and once more after it stopped");
});

test("a second run while one is going shows the 409 rather than starting one", async () => {
  stubApi({ "POST /companies/run": { ok: false, status: 409, body: { detail: "a run is already in progress" } } });

  assert.equal(await useStore.getState().startBatch("run"), "a run is already in progress");
  assert.equal(useStore.getState().runPolling, false);
});

test("company rows are not persisted", async () => {
  stubApi({ "GET /companies": { body: [{ id: "co-1" }] } });
  await useStore.getState().loadCompanies();

  // Same rule as browse rows: a cache that outlived the page shows a stale
  // officer count and a last run that has since finished.
  assert.equal("companyRows" in JSON.parse(saved.get("scarper")).state, false);
});

// --- bulk selection ----------------------------------------------------------

test("a bulk action sends the picked ids, not the whole list", async () => {
  const seen = stubApi({
    "POST /companies/run": { body: { started: "run_all" } },
    "GET /companies/run": { body: { running: false } },
    "GET /companies": { body: [] },
  });

  await useStore.getState().startBatch("run", ["co-1", "co-3"]);
  while (useStore.getState().runPolling) await new Promise((r) => setTimeout(r, 5));

  // The endpoints already took a list, so "selected" and "all" are the same
  // call with an argument -- there is no second route to keep in step.
  assert.deepEqual(seen[0].body, { ids: ["co-1", "co-3"] });
});

test("deleting several sends one DELETE each and reloads once", async () => {
  const seen = stubApi({ "GET /companies": { body: [] } });

  assert.equal(await useStore.getState().deleteCompanies(["co-1", "co-2"]), null);

  assert.deepEqual(
    seen.map((s) => s.method + " " + s.url),
    ["DELETE /companies/co-1", "DELETE /companies/co-2", "GET /companies"],
  );
});

test("a failed bulk delete stops there, reports it, and still reloads", async () => {
  const seen = stubApi({
    "DELETE /companies/co-2": { ok: false, status: 404, body: { detail: "company not found" } },
    "GET /companies": { body: [] },
  });

  const problem = await useStore.getState().deleteCompanies(["co-1", "co-2", "co-3"]);

  assert.match(problem, /company not found/);       // rules.md G28: the real error
  assert.equal(seen.some((s) => s.url.endsWith("co-3")), false, "stopped at the failure");
  // co-1 is gone whatever happened to co-2, so the table on screen is stale
  // until this reload -- half a bulk delete must not look like none of it.
  assert.equal(seen.at(-1).method, "GET");
});
