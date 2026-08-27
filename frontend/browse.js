// Every row of both tables, plus the saved scripts view over them.
// Read-only: this page never POSTs, never deletes. Depends on api.js.

const panel = $("panel");
const tabs = [...document.querySelectorAll('[role="tab"]')];

// Each tab is a path, a column set, and what its expanded row shows.
const TABS = {
  jobs: {
    path: "/jobs?limit=200",
    empty: "No jobs yet. Run one from the New job page.",
    columns: [
      { key: "id", label: "Job", render: (r) => short(r.id) },
      { key: "url", label: "URL", class: "clip" },
      { key: "status", label: "Status", render: (r) => statusPill(r.status) },
      { key: "prompt", label: "Prompt", class: "clip" },
      { key: "attempts", label: "Attempts", class: "num" },
      { key: "created_at", label: "Created", render: (r) => when(r.created_at) },
    ],
    detail: jobDetail,
  },
  attempts: {
    path: "/attempts?limit=200",
    empty: "No attempts yet.",
    columns: [
      { key: "job_id", label: "Job", render: (r) => short(r.job_id) },
      { key: "url", label: "URL", class: "clip" },
      {
        key: "attempt_number",
        label: "Attempt",
        // 0 is not a real attempt: it is the saved script being replayed.
        render: (r) => (r.attempt_number === 0 ? "replay" : String(r.attempt_number)),
      },
      { key: "success", label: "Result", render: (r) => (r.success ? "ok" : "failed") },
      { key: "error_message", label: "Error", class: "clip" },
      { key: "created_at", label: "Created", render: (r) => when(r.created_at) },
    ],
    detail: attemptDetail,
  },
  scripts: {
    path: "/scripts?limit=200",
    empty: "No saved scripts yet. A script is saved the first time a job succeeds, "
      + "and reused when the same URL, prompt and fields are submitted again.",
    columns: [
      { key: "url", label: "URL", class: "clip" },
      { key: "prompt", label: "Prompt", class: "clip" },
      { key: "reuse_count", label: "Times reused", class: "num" },
      { key: "created_at", label: "Saved", render: (r) => when(r.created_at) },
    ],
    detail: scriptDetail,
  },
};

// --- expanded row bodies ---------------------------------------------------

function jobDetail(row, job) {
  const box = document.createElement("div");
  box.append(section("schema", pre(JSON.stringify(row.json_schema, null, 2))));
  box.append(section("prompt", pre(row.prompt)));

  if (job) {
    if (job.result && job.result.length) {
      const scroll = document.createElement("div");
      scroll.className = "scroll";
      scroll.append(buildTable(job.result));
      box.append(section(`result (${job.result.length} rows)`, scroll));
    }
    if (job.script) box.append(section("script", codeBlock(job.script)));
  }

  if (row.error) box.append(section("error", errorBox(row.error)));
  return box;
}

function attemptDetail(row) {
  const box = document.createElement("div");
  box.append(section("script", codeBlock(row.script_code)));
  if (row.error_message) box.append(section("error", errorBox(row.error_message)));
  if (row.output_json && row.output_json.length) {
    const scroll = document.createElement("div");
    scroll.className = "scroll";
    scroll.append(buildTable(row.output_json));
    box.append(section(`output (${row.output_json.length} rows)`, scroll));
  }
  return box;
}

function scriptDetail(row) {
  const box = document.createElement("div");
  box.append(section("prompt", pre(row.prompt)));
  box.append(section("schema", pre(JSON.stringify(row.json_schema, null, 2))));
  box.append(section("script", codeBlock(row.script_code)));
  return box;
}

function pre(text) {
  const el = document.createElement("pre");
  el.textContent = text;                  // arbitrary user text, never innerHTML
  return el;
}

function errorBox(text) {
  const p = document.createElement("p");
  p.className = "error";
  p.textContent = text;                   // verbatim (rules.md G28)
  return p;
}

// --- rendering -------------------------------------------------------------

/** Toggle one detail row open beneath its table row. */
function bindRows(table, rows, tab) {
  table.classList.add("picks");
  const bodyRows = [...table.tBodies[0].rows];
  bodyRows.forEach((tr, i) => {
    const row = rows[i];
    tr.className = i % 2 ? "pick zebra" : "pick";
    tr.tabIndex = 0;
    tr.setAttribute("aria-expanded", "false");

    const toggle = async () => {
      const open = tr.nextElementSibling;
      if (open && open.classList.contains("detail")) {
        open.remove();
        tr.setAttribute("aria-expanded", "false");
        return;
      }
      const detail = table.tBodies[0].insertRow(tr.sectionRowIndex + 1);
      detail.className = "detail";
      const cell = detail.insertCell();
      cell.colSpan = tab.columns.length;
      cell.append(stateBox("loading..."));
      tr.setAttribute("aria-expanded", "true");

      // Only the jobs tab needs a second request: the result and the winning
      // script live behind GET /jobs/{id}, not in the list row.
      let extra = null;
      if (tab === TABS.jobs) {
        try {
          extra = await getJSON("/jobs/" + row.id);
        } catch (err) {
          cell.replaceChildren(errorBox(String(err)));
          return;
        }
      }
      cell.replaceChildren(tab.detail(row, extra));
    };

    tr.addEventListener("click", toggle);
    tr.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        toggle();
      }
    });
  });
}

async function load(name) {
  const tab = TABS[name];
  panel.replaceChildren(stateBox("loading..."));

  let rows;
  try {
    rows = await getJSON(tab.path);
  } catch (err) {
    panel.replaceChildren(errorBox("could not reach the API:\n" + err));
    return;
  }

  document.querySelector(`#tab-${name} .count`).textContent = rows.length;

  if (!rows.length) {
    panel.replaceChildren(stateBox(tab.empty));
    return;
  }

  const table = buildTable(rows, tab.columns);
  bindRows(table, rows, tab);

  const scroll = document.createElement("div");
  scroll.className = "scroll";
  scroll.append(table);
  panel.replaceChildren(scroll);
}

function select(name) {
  for (const t of tabs) t.setAttribute("aria-selected", String(t.dataset.tab === name));
  panel.setAttribute("aria-labelledby", "tab-" + name);
  location.hash = name;
  load(name);
}

const current = () => tabs.find((t) => t.getAttribute("aria-selected") === "true").dataset.tab;

for (const t of tabs) t.addEventListener("click", () => select(t.dataset.tab));
$("refresh").addEventListener("click", () => select(current()));

select(TABS[location.hash.slice(1)] ? location.hash.slice(1) : "jobs");
