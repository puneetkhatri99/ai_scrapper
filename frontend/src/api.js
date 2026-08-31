// Talking to the backend. No DOM and no React in here.

// `npm run dev` puts the page on :5173 and the API on :8000, which is why
// both are in main.py's CORS allow-list. A `npm run build` bundle is served by
// main.py itself, so the base is empty and same-origin. VITE_API_BASE wins
// over both when the API lives somewhere else.
// `?.` so this module also imports outside Vite -- tests/store.test.mjs runs
// it on bare node, where import.meta.env does not exist.
const API =
  import.meta.env?.VITE_API_BASE ?? (location.port === "8000" ? "" : "http://127.0.0.1:8000");

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function getJSON(path) {
  const r = await fetch(API + path);
  if (!r.ok) throw new Error("GET " + path + " returned " + r.status);
  return r.json();
}

/** Both halves come back: a 422 body is the error message (rules.md G28). */
async function sendJSON(method, path, body) {
  const r = await fetch(API + path, {
    method,
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  return { ok: r.ok, body: await r.json() };
}

export const postJSON = (path, body) => sendJSON("POST", path, body);
export const patchJSON = (path, body) => sendJSON("PATCH", path, body);
export const putJSON = (path, body) => sendJSON("PUT", path, body);

/** DELETE answers 204 with no body, so there is nothing to parse. */
export async function del(path) {
  const r = await fetch(API + path, { method: "DELETE" });
  return { ok: r.ok, body: r.ok ? null : await r.json() };
}

/** First 8 chars of a uuid: enough to tell rows apart, short enough to scan. */
export const short = (id) => String(id).slice(0, 8);

/** MySQL hands back "2026-08-27T14:03:11"; show it without the T. */
export const when = (ts) => (ts ? String(ts).replace("T", " ").slice(0, 19) : "");

/** Table cell text, or null for "nothing here" so the cell can render a dash. */
export function cellText(v) {
  if (v === null || v === undefined || v === "") return null;
  return typeof v === "object" ? JSON.stringify(v) : String(v);
}
