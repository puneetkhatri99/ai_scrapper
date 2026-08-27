// Shared by index.html and browse.html: talking to the API, and the two
// widgets both pages render (a data table, a copy button).
//
// Everything here is scraped third-party text or an LLM-written script. It
// reaches the DOM through textContent, never innerHTML. That is the whole
// XSS story for this app and it must stay true on both pages.

// Served from the API itself in dev; otherwise talk to it cross-origin.
const API = location.port === "8000" ? "" : "http://127.0.0.1:8000";

const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function getJSON(path) {
  const r = await fetch(API + path);
  if (!r.ok) throw new Error("GET " + path + " returned " + r.status);
  return r.json();
}

/** First 8 chars of a uuid: enough to tell rows apart, short enough to scan. */
const short = (id) => String(id).slice(0, 8);

/** MySQL hands back "2026-08-27T14:03:11"; show it without the T. */
const when = (ts) => (ts ? String(ts).replace("T", " ").slice(0, 19) : "");

function cellText(v) {
  if (v === null || v === undefined || v === "") return null;
  return typeof v === "object" ? JSON.stringify(v) : String(v);
}

/**
 * Build a table element from rows.
 *
 * columns: [{key, label, render?, class?}]. Omit it and the columns are the
 * union of every row's keys in first-seen order, since extracted rows are not
 * guaranteed to be uniform.
 */
function buildTable(rows, columns) {
  if (!columns) {
    const keys = [];
    for (const row of rows)
      for (const k of Object.keys(row)) if (!keys.includes(k)) keys.push(k);
    columns = keys.map((k) => ({ key: k, label: k }));
  }

  const table = document.createElement("table");
  const head = table.createTHead().insertRow();
  for (const col of columns) {
    const th = document.createElement("th");
    th.textContent = col.label;
    head.append(th);
  }

  const body = table.createTBody();
  for (const row of rows) {
    const tr = body.insertRow();
    for (const col of columns) {
      const td = tr.insertCell();
      if (col.class) td.className = col.class;
      const node = col.render ? col.render(row) : null;
      if (node instanceof Node) {
        td.append(node);
        continue;
      }
      const text = cellText(node !== null ? node : row[col.key]);
      if (text === null) {
        td.textContent = "-";
        td.classList.add("nul");
      } else {
        td.textContent = text;              // never innerHTML
      }
    }
  }
  return table;
}

/** The dot-and-word status badge. Never color alone (design.md 7). */
function statusPill(status) {
  const span = document.createElement("span");
  span.className = "status";
  span.dataset.status = status;
  const dot = document.createElement("span");
  dot.className = "dot";
  const word = document.createElement("span");
  word.textContent = status;
  span.append(dot, word);
  return span;
}

/** A <pre> of code with a copy button over it. */
function codeBlock(code) {
  const wrap = document.createElement("div");
  wrap.className = "code-wrap";

  const pre = document.createElement("pre");
  const el = document.createElement("code");
  el.textContent = code;
  pre.append(el);

  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "ghost copy";
  btn.textContent = "copy";
  btn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(code);
      btn.textContent = "copied";
    } catch {
      btn.textContent = "copy failed";      // insecure context or denied
    }
    setTimeout(() => (btn.textContent = "copy"), 1500);
  });

  wrap.append(pre, btn);
  return wrap;
}

/** Labelled block: a section label plus whatever node follows it. */
function section(label, node) {
  const div = document.createElement("div");
  div.className = "section";
  const h = document.createElement("span");
  h.className = "label";
  h.textContent = label;
  div.append(h, node);
  return div;
}

function stateBox(text) {
  const p = document.createElement("p");
  p.className = "state";
  p.textContent = text;
  return p;
}
