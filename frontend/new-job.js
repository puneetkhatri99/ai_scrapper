// The new-job page: build a schema without writing JSON, submit, poll, render.
// Depends on api.js for $, getJSON, buildTable, codeBlock and the API base.

const POLL_MS = 2000;
const GIVE_UP_MS = 5 * 60 * 1000;

// Plain English on the left, JSON Schema on the right. Flat types only --
// build_validator in backend/models.py validates flat properties, so the
// builder cannot express something the backend would silently ignore.
const TYPES = [
  ["string", "Text"],
  ["integer", "Whole number"],
  ["number", "Decimal"],
  ["boolean", "Yes / no"],
  ["array", "List"],
];

const EXAMPLE = [
  { name: "title", type: "string", required: true },
  { name: "price", type: "string", required: false },
];

const form = $("job-form");
const runBtn = $("run");
const formError = $("form-error");
const rowsEl = $("rows");
const jsonEl = $("schema-json");

let jsonMode = false;

// --- schema builder --------------------------------------------------------

function addRow(field = { name: "", type: "string", required: false }) {
  const i = rowsEl.children.length;
  const row = document.createElement("div");
  row.className = "row";

  const name = document.createElement("input");
  name.type = "text";
  name.id = "field-name-" + i;
  name.placeholder = "price";
  name.value = field.name;
  name.setAttribute("aria-label", "Field name");

  const type = document.createElement("select");
  type.setAttribute("aria-label", "Field type");
  for (const [value, text] of TYPES) {
    const opt = document.createElement("option");
    opt.value = value;
    opt.textContent = text;
    type.append(opt);
  }
  type.value = field.type;

  const reqWrap = document.createElement("span");
  reqWrap.className = "req";
  const req = document.createElement("input");
  req.type = "checkbox";
  req.checked = field.required;
  req.setAttribute("aria-label", "Required");
  reqWrap.append(req);

  const drop = document.createElement("button");
  drop.type = "button";
  drop.className = "ghost drop";
  drop.textContent = "×";
  drop.title = "Remove this field";
  drop.setAttribute("aria-label", "Remove field");
  drop.addEventListener("click", () => {
    row.remove();
    if (!rowsEl.children.length) addRow();     // never an empty builder
  });

  row.append(name, type, reqWrap, drop);
  rowsEl.append(row);
  return name;
}

/** Read the rows into a JSON Schema. */
function schemaFromRows() {
  const properties = {};
  const required = [];
  for (const row of rowsEl.children) {
    const [name, type, reqWrap] = row.children;
    const key = name.value.trim();
    if (!key) continue;
    properties[key] = { type: type.value };
    if (reqWrap.firstChild.checked) required.push(key);
  }
  const schema = { type: "object", properties };
  if (required.length) schema.required = required;
  return schema;
}

/** Put a JSON Schema back into rows. Returns false if it is not flat. */
function rowsFromSchema(schema) {
  let s = schema;
  if (s && s.type === "array" && s.items && typeof s.items === "object") s = s.items;
  if (!s || typeof s !== "object" || !s.properties) return false;

  const required = new Set(s.required || []);
  const fields = [];
  for (const [name, spec] of Object.entries(s.properties)) {
    const type = spec && spec.type;
    if (!TYPES.some(([v]) => v === type)) return false;     // nested or unknown
    fields.push({ name, type, required: required.has(name) });
  }

  rowsEl.replaceChildren();
  (fields.length ? fields : EXAMPLE).forEach(addRow);
  return true;
}

/** Whichever editor is showing is the one that counts. */
function currentSchema() {
  if (!jsonMode) return schemaFromRows();
  return JSON.parse(jsonEl.value);            // throws; the caller reports it
}

$("add").addEventListener("click", () => addRow().focus());

$("mode").addEventListener("click", () => {
  formError.hidden = true;
  if (!jsonMode) {
    jsonEl.value = JSON.stringify(schemaFromRows(), null, 2);
  } else {
    let parsed;
    try {
      parsed = JSON.parse(jsonEl.value);
    } catch (err) {
      return show(formError, "That is not valid JSON, so the fields cannot be "
        + "filled in:\n" + err.message);
    }
    if (!rowsFromSchema(parsed)) {
      return show(formError, "This schema has nested or unsupported types, so "
        + "it can only be edited as JSON.");
    }
  }
  jsonMode = !jsonMode;
  $("builder").hidden = jsonMode;
  jsonEl.hidden = !jsonMode;
  $("fields-hint").textContent = jsonMode
    ? "Raw JSON Schema. Switch back to fields if it stays flat."
    : "One row per piece of data you want back from each item on the page.";
  $("mode").textContent = jsonMode ? "Edit as fields" : "Edit as JSON";
});

EXAMPLE.forEach(addRow);

// --- submit and poll -------------------------------------------------------

function show(el, text) {
  el.textContent = text;
  el.hidden = false;
}

function setBusy(busy) {
  runBtn.disabled = busy;
  runBtn.textContent = busy ? "Running..." : "Run scrape";
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  formError.hidden = true;

  let schema;
  try {
    schema = currentSchema();
  } catch (err) {
    return show(formError, "JSON schema is not valid JSON:\n" + err.message);
  }
  if (!Object.keys(schema.properties || {}).length) {
    return show(formError, "Add at least one field to extract.");
  }

  setBusy(true);
  let res, body;
  try {
    res = await fetch(API + "/jobs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        url: $("url").value,
        json_schema: schema,
        prompt: $("prompt").value,
      }),
    });
    body = await res.json();
  } catch (err) {
    setBusy(false);
    return show(formError, "could not reach the API:\n" + err);
  }

  if (!res.ok) {
    setBusy(false);
    // 422 detail verbatim -- swallowing it is how you get "something went wrong".
    return show(formError, JSON.stringify(body, null, 2));
  }

  poll(body.job_id);
});

async function poll(id) {
  $("job-card").hidden = false;
  $("job-id").textContent = short(id);
  $("attempts-link").href = "browse.html#attempts";
  for (const s of ["result", "script", "error"]) $(s + "-section").hidden = true;
  setStatus("pending");

  const deadline = Date.now() + GIVE_UP_MS;
  while (true) {
    let job;
    try {
      job = await getJSON("/jobs/" + id);
    } catch (err) {
      setStatus("failed");
      show($("job-error"), "lost contact with the API:\n" + err);
      $("error-section").hidden = false;
      break;
    }

    render(job);
    if (job.status === "done" || job.status === "failed") break;

    if (Date.now() > deadline) {
      setStatus("failed");
      show($("job-error"), "stopped polling after 5 minutes. The job may still "
        + "be running -- check GET /jobs/" + id);
      $("error-section").hidden = false;
      break;
    }
    await sleep(POLL_MS);
  }
  setBusy(false);          // one job at a time, stated honestly (design.md 6)
}

function setStatus(status) {
  $("status").dataset.status = status;
  $("status-word").textContent = status;
}

function render(job) {
  setStatus(job.status);

  const attempt = $("attempt");
  attempt.hidden = !job.attempts;
  if (job.attempts) {
    // A replay is attempt 0: counted, but it does not spend one of the three
    // generation attempts. Say which of the two actually happened.
    const generated = job.attempts - (job.replayed ? 1 : 0);
    if (!job.replayed) attempt.textContent = `attempt ${job.attempts} / 3`;
    else if (!generated) attempt.textContent = "replayed a saved script";
    else attempt.textContent = `saved script was stale, attempt ${generated} / 3`;
  }

  if (Array.isArray(job.result) && job.result.length) {
    $("result").replaceChildren(buildTable(job.result));
    $("result-section").hidden = false;
  }

  if (job.script) {
    $("script").replaceChildren(codeBlock(job.script));
    $("script-section").hidden = false;
  }

  if (job.status === "failed" && job.error) {
    show($("job-error"), job.error);          // verbatim traceback (rules.md G28)
    $("error-section").hidden = false;
  }
}
