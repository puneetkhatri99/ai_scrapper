import { useEffect, useRef, useState } from "react";

import { cellText } from "../api";
import { ErrorBox, Scroll, StateBox, StatusPill } from "../components/primitives";
import { useStore } from "../store";
import {
  BTN,
  CARD_HEAD,
  FIELD_LABEL,
  GHOST,
  H1,
  HEAD_ACTIONS,
  HINT,
  INPUT,
  ISSUE,
  MAIN,
  NAME_INPUT,
  NUM,
  PICKS,
  STATE,
  TBODY,
  TD,
  TH,
  W,
} from "../ui";

// The editable row, in order. `key` is both the API field and the column, so
// adding one is a line here and a line in backend/companies/schemas.py.
const COLUMNS = [
  { key: "name", label: "Company", width: W.co, required: true },
  { key: "nmls_id", label: "NMLS #", width: W.tag },
  { key: "lo_count", label: "LOs", width: W.num, numeric: true },
  { key: "directory_url", label: "Directory URL", hint: "where the officers are listed" },
  { key: "company_url", label: "Company URL" },
  { key: "note", label: "Hint", hint: "told to the AI, e.g. \"Search Button\"" },
];

const BLANK = Object.fromEntries(COLUMNS.map((c) => [c.key, ""]));

// Every cell here is its own input, so the padding lives on the input and the
// cell gives it the whole width -- otherwise the box floats inside a padded td
// and the row reads as two grids.
const CELL = "border-b border-border p-0 align-top";
const CHECK = "size-4 cursor-pointer accent-accent align-middle";

const plural = (n) => (n === 1 ? "company" : "companies");

/**
 * One cell, edited in place -- the same interaction JobName already uses on
 * the Browse page: no edit mode and no save button, blur or Enter saves and
 * Escape puts back what was there.
 *
 * `saved` is watched rather than copied once, because the table reloads every
 * two seconds while a batch runs. Re-syncing only when the stored value
 * actually changed is what stops that landing mid-keystroke.
 */
function EditableCell({ row, col, onSave }) {
  const saved = cellText(row[col.key]) ?? "";
  const [text, setText] = useState(saved);
  const [error, setError] = useState(null);

  useEffect(() => setText(saved), [saved]);

  const save = async () => {
    if (text.trim() === saved) return;
    const value = col.numeric ? Number(text) || null : text;
    const problem = await onSave({ ...row, [col.key]: value });
    setError(problem);
    if (problem) setText(saved); // the row on screen must match the row stored
  };

  return (
    <td className={CELL + " " + col.width}>
      <input
        className={NAME_INPUT + " w-full rounded-none!"}
        aria-label={col.label}
        aria-invalid={error ? "true" : undefined}
        autoComplete="off"
        inputMode={col.numeric ? "numeric" : undefined}
        placeholder={col.required ? "required" : "-"}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={save}
        onKeyDown={(e) => {
          if (e.key === "Enter") e.currentTarget.blur();
          if (e.key === "Escape") setText(saved);
        }}
      />
      {error && (
        <span className={ISSUE} role="alert">
          {error}
        </span>
      )}
    </td>
  );
}

/** What the last pass over this company did. Nothing yet is not a failure. */
function Outcome({ row }) {
  if (row.last_error) {
    return (
      <span className={ISSUE} title={row.last_error}>
        {row.last_error}
      </span>
    );
  }
  if (row.job_status) return <StatusPill status={row.job_status} />;
  return <span className="text-mute">not run yet</span>;
}

function CompanyRow({ row, selectMode, checked, onCheck }) {
  const saveCompany = useStore((s) => s.saveCompany);

  return (
    <tr>
      {selectMode && (
        <td className={TD + " " + W.drop}>
          <input
            type="checkbox"
            className={CHECK}
            aria-label={"Select " + row.name}
            checked={checked}
            onChange={(e) => onCheck(row.id, e.target.checked)}
          />
        </td>
      )}
      {COLUMNS.map((col) => (
        <EditableCell key={col.key} row={row} col={col} onSave={saveCompany} />
      ))}
      <td className={TD + " " + W.num + " " + NUM}>{row.officers || <span className="text-mute">-</span>}</td>
      <td className={TD + " " + W.outcome}>
        <Outcome row={row} />
      </td>
    </tr>
  );
}

/**
 * The three bulk actions.
 *
 * The copy is what each one actually does, not a generic "are you sure?" --
 * and specifically not a generic warning about cost, because in this app the
 * two buttons differ on exactly that point: Generate is the only thing that
 * can reach the model, Run replays what it already wrote (CLAUDE.md 8). A
 * modal that warned about credits on both would teach the user to ignore it.
 *
 * `go` returns an error string or null -- the store's convention everywhere.
 */
const BULK = {
  run: {
    label: "Run selected",
    title: (n) => `Run ${n} selected ${plural(n)}?`,
    body:
      "Replays the script already saved for each one and merges in the loan " +
      "officers it finds. This never calls the AI, so it costs nothing -- a " +
      "company with no saved script is skipped rather than generated for.",
    confirm: "Run",
    go: (s, ids) => s.startBatch("run", ids),
    done: (n) => `Running ${n} ${plural(n)}.`,
  },
  scripts: {
    label: "Generate scripts",
    title: (n) => `Write scripts for ${n} selected ${plural(n)}?`,
    body:
      "Writes a scraping script for each selected company that has not got a " +
      "working one, and rewrites the ones whose last run failed. This is the " +
      "step that calls the AI, so it costs money.",
    confirm: "Generate",
    go: (s, ids) => s.startBatch("scripts", ids),
    done: (n) => `Writing scripts for up to ${n} ${plural(n)}.`,
  },
  delete: {
    label: "Delete",
    danger: true,
    title: (n) => `Delete ${n} selected ${plural(n)}?`,
    body:
      "Their scraped loan officers are deleted with them. This cannot be " +
      "undone -- re-adding a company does not bring its officers back.",
    confirm: "Delete",
    go: (s, ids) => s.deleteCompanies(ids),
    done: (n) => `Deleted ${n} ${plural(n)}.`,
  },
};

/**
 * Every dialog on this page, as a native <dialog>.
 *
 * showModal() is the whole reason: the backdrop, the focus trap, the inert
 * page behind it and Escape-to-close are the browser's, so this is markup and
 * one effect rather than a modal library and a keydown listener.
 */
function Modal({ busy, onClose, children }) {
  const ref = useRef(null);
  useEffect(() => {
    const dialog = ref.current;
    dialog?.showModal();
    return () => dialog?.close(); // closed before React removes it, so no orphan backdrop
  }, []);

  return (
    <dialog
      ref={ref}
      // Preflight zeroes every margin, so a modal dialog lands top-left
      // without this; the browser centres it once it has one.
      className={
        "m-auto max-h-[85vh] w-[min(30rem,92vw)] overflow-y-auto rounded-lg border " +
        "border-border bg-surface p-6 text-text backdrop:bg-black/50"
      }
      // Escape fires this. Blocked mid-action, so the dialog cannot vanish
      // out from under a request that is still going.
      onCancel={(e) => (busy ? e.preventDefault() : onClose())}
    >
      {children}
    </dialog>
  );
}

function Confirm({ action, count, busy, onConfirm, onCancel }) {
  return (
    <Modal busy={busy} onClose={onCancel}>
      <h2 className="mb-3 font-ui text-base font-semibold">{action.title(count)}</h2>
      <p className="mb-6 text-sm leading-[1.6] text-dim">{action.body}</p>
      <div className="flex justify-end gap-3">
        <button type="button" className={GHOST} disabled={busy} onClick={onCancel}>
          Cancel
        </button>
        <button
          type="button"
          // text-bg, not text-white: --color-failed is a light red in the dark
          // theme, where white on it is under 3:1.
          className={
            action.danger
              ? BTN + " bg-failed! text-bg! enabled:hover:bg-failed! enabled:hover:brightness-110"
              : BTN
          }
          disabled={busy}
          autoFocus
          onClick={onConfirm}
        >
          {busy ? "Working..." : action.confirm}
        </button>
      </div>
    </Modal>
  );
}

/**
 * Adding a company: the same six columns the table edits, as a form.
 *
 * `required` on the name is the browser's -- it blocks the submit and says so
 * itself, so there is no hand-written "a company needs a name" to keep in step
 * with the backend rail that also checks it.
 */
function AddCompany({ onClose }) {
  const addCompany = useStore((s) => s.addCompany);
  const [draft, setDraft] = useState(BLANK);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    // A plain form inside a dialog still navigates the page. We want the POST.
    e.preventDefault();
    setBusy(true);
    const problem = await addCompany({ ...draft, lo_count: Number(draft.lo_count) || null });
    setBusy(false);
    setError(problem);
    if (!problem) onClose();
  };

  return (
    <Modal busy={busy} onClose={onClose}>
      <form onSubmit={submit}>
        <h2 className="mb-6 font-ui text-base font-semibold">Add a company</h2>

        <div className="mb-6 grid gap-4">
          {COLUMNS.map((col) => (
            <div key={col.key}>
              <label className={FIELD_LABEL} htmlFor={"new-" + col.key}>
                {col.label} {col.hint && <span className={HINT}>{col.hint}</span>}
              </label>
              <input
                className={INPUT}
                id={"new-" + col.key}
                required={col.required}
                autoFocus={col.required}
                autoComplete="off"
                inputMode={col.numeric ? "numeric" : undefined}
                value={draft[col.key]}
                onChange={(e) => setDraft({ ...draft, [col.key]: e.target.value })}
              />
            </div>
          ))}
        </div>

        {error && (
          <div className="mb-6">
            <ErrorBox text={error} />
          </div>
        )}

        <div className="flex justify-end gap-3">
          <button type="button" className={GHOST} disabled={busy} onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className={BTN} disabled={busy}>
            {busy ? "Adding..." : "Add company"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

/** What just happened, briefly. Clears itself; also clickable to dismiss. */
function Toast({ toast, onDismiss }) {
  // `toast` alone: onDismiss is a fresh closure every render, and the table
  // reloads every two seconds while a batch runs -- keyed on that, the timer
  // would restart for ever and the toast would never leave.
  useEffect(() => {
    const t = setTimeout(onDismiss, 5000);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [toast]);

  return (
    <div
      role="status"
      aria-live="polite"
      className="pointer-events-none fixed inset-x-0 bottom-8 z-10 flex justify-center px-4"
    >
      <button
        type="button"
        onClick={onDismiss}
        className={
          "pointer-events-auto max-w-full cursor-pointer rounded-md border px-4 py-2.5 text-left " +
          "font-ui text-sm shadow-lg " +
          (toast.bad
            ? "border-failed bg-surface text-failed"
            : "border-border bg-surface text-text")
        }
      >
        {toast.text}
      </button>
    </div>
  );
}

/**
 * The head: either the two whole-list buttons or, once rows are ticked, the
 * three bulk ones. Select stays put beside them so the toggle never moves.
 */
function BatchBar({ selectMode, onToggleSelect, count, onAsk, onAdd }) {
  const running = useStore((s) => s.runProgress.running);
  const startBatch = useStore((s) => s.startBatch);
  const [error, setError] = useState(null);

  // One batch at a time is the backend's rule, not the button's: /companies/run
  // and /companies/scripts share a lock and answer 409 while one is held. So
  // the disable here is honesty about that, and the title says which.
  const why = running ? "a batch is already running" : undefined;

  const startAll = (kind, confirmText) => async () => {
    if (confirmText && !confirm(confirmText)) return;
    setError(await startBatch(kind));
  };

  return (
    <div className={HEAD_ACTIONS}>
      {error && <span className={ISSUE}>{error}</span>}

      {count > 0 ? (
        <>
          <span className="font-ui text-xs font-semibold text-mute">{count} selected</span>
          <button
            type="button"
            className={GHOST}
            disabled={running}
            title={why}
            onClick={() => onAsk("scripts")}
          >
            {BULK.scripts.label}
          </button>
          <button
            type="button"
            className={BTN}
            disabled={running}
            title={why}
            onClick={() => onAsk("run")}
          >
            {BULK.run.label}
          </button>
          <button
            type="button"
            className={GHOST + " border-failed! text-failed!"}
            disabled={running}
            title={why}
            onClick={() => onAsk("delete")}
          >
            {BULK.delete.label}
          </button>
        </>
      ) : (
        <>
          <button type="button" className={GHOST} onClick={onAdd}>
            Add company
          </button>
          <button
            type="button"
            className={GHOST}
            disabled={running}
            title={why}
            onClick={startAll(
              "scripts",
              "Write a script for every company that has not got a working one? " +
                "This is the step that calls the AI, so it costs money.",
            )}
          >
            Generate scripts
          </button>
          <button
            type="button"
            className={BTN}
            disabled={running}
            title={why}
            onClick={startAll("run")}
          >
            Run all
          </button>
        </>
      )}

      <button type="button" className={GHOST} aria-pressed={selectMode} onClick={onToggleSelect}>
        {selectMode ? "Cancel" : "Select"}
      </button>
    </div>
  );
}

/**
 * The broker list: add, edit and delete, plus the batch buttons.
 *
 * Generate scripts is the only thing here that can reach the model. Run all
 * replays what it wrote, which is why the two are separate buttons and not one
 * -- a manual run has a predictable cost of nothing. Ticking rows narrows both
 * to a selection; the endpoints already take a list of ids, so "selected" and
 * "all" are the same two calls with an argument.
 */
export function Companies() {
  const rows = useStore((s) => s.companyRows);
  const error = useStore((s) => s.companiesError);
  const progress = useStore((s) => s.runProgress);
  const loadCompanies = useStore((s) => s.loadCompanies);
  const pollRun = useStore((s) => s.pollRun);

  const [selectMode, setSelectMode] = useState(false);
  const [picked, setPicked] = useState(() => new Set());
  const [adding, setAdding] = useState(false);
  const [asking, setAsking] = useState(null); // which BULK action, awaiting confirm
  const [busy, setBusy] = useState(false);
  const [toast, setToast] = useState(null);

  useEffect(() => {
    loadCompanies();
    pollRun(); // reattaches to a batch that was already going
  }, [loadCompanies, pollRun]);

  // Derived, never stored: the table reloads every two seconds while a batch
  // runs, so a row can vanish under the selection. Intersecting here means a
  // deleted row leaves the count without anything having to prune the set.
  const selected = (rows ?? []).filter((r) => picked.has(r.id));
  const count = selected.length;
  const allPicked = count > 0 && count === rows?.length;

  const clear = () => setPicked(new Set());

  // Leaving select mode drops the selection, and does not ask: throwing away
  // ticks is not destructive, and a confirm on it would be noise.
  const toggleSelect = () => {
    setSelectMode((on) => !on);
    clear();
  };

  const check = (id, on) =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });

  const checkAll = (on) => setPicked(on ? new Set(rows.map((r) => r.id)) : new Set());

  const runAction = async () => {
    const action = BULK[asking];
    const ids = selected.map((r) => r.id);
    setBusy(true);
    const problem = await action.go(useStore.getState(), ids);
    setBusy(false);
    setAsking(null);
    setToast(problem ? { text: problem, bad: true } : { text: action.done(ids.length) });
    // Run and Generate keep the selection -- the rows are about to change
    // status and that is what the user is watching. Delete cannot: the rows
    // are gone.
    if (!problem && asking === "delete") clear();
  };

  return (
    <main className={MAIN}>
      <div className={CARD_HEAD}>
        <h1 className={H1}>Companies</h1>
        <BatchBar
          selectMode={selectMode}
          onToggleSelect={toggleSelect}
          count={count}
          onAsk={setAsking}
          onAdd={() => setAdding(true)}
        />
      </div>

      {progress.running && (
        <p className={STATE + " mb-6"} aria-live="polite">
          {progress.phase === "generate" ? "Writing scripts" : "Running"} {progress.done} /{" "}
          {progress.total}
          {progress.current ? " - " + progress.current : ""}
        </p>
      )}

      {error && <ErrorBox text={error} />}
      {!error && !rows && <StateBox text="loading..." />}

      {rows && (
        <Scroll>
          <table className={PICKS}>
            <thead>
              <tr>
                {selectMode && (
                  <th className={TH + " " + W.drop}>
                    <input
                      type="checkbox"
                      className={CHECK}
                      aria-label="Select every company"
                      checked={allPicked}
                      ref={(el) => {
                        if (el) el.indeterminate = count > 0 && !allPicked;
                      }}
                      onChange={(e) => checkAll(e.target.checked)}
                    />
                  </th>
                )}
                {COLUMNS.map((c) => (
                  <th key={c.key} className={TH + " " + (c.width ?? "")} title={c.hint}>
                    {c.label}
                  </th>
                ))}
                <th className={TH + " " + W.num + " " + NUM}>Officers</th>
                <th className={TH + " " + W.outcome}>Last run</th>
              </tr>
            </thead>
            <tbody className={TBODY}>
              {rows.map((row) => (
                <CompanyRow
                  key={row.id}
                  row={row}
                  selectMode={selectMode}
                  checked={picked.has(row.id)}
                  onCheck={check}
                />
              ))}
            </tbody>
          </table>
        </Scroll>
      )}

      {adding && <AddCompany onClose={() => setAdding(false)} />}
      {asking && (
        <Confirm
          action={BULK[asking]}
          count={count}
          busy={busy}
          onConfirm={runAction}
          onCancel={() => setAsking(null)}
        />
      )}
      {toast && <Toast toast={toast} onDismiss={() => setToast(null)} />}
    </main>
  );
}
