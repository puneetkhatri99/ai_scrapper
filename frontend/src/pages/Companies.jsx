import { useEffect, useRef, useState } from "react";

import { cellText } from "../api";
import { ErrorBox, StateBox, StatusPill } from "../components/primitives";
import { TableShell, useDataTable } from "../components/Table";
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
  STATE,
  W,
} from "../ui";

// The editable row, in order. `key` is both the API field and the column, so
// adding one is a line here and a line in backend/companies/schemas.py.
const COLUMNS = [
  { key: "name", label: "Company", class: W.co, required: true },
  { key: "nmls_id", label: "NMLS #", class: W.tag },
  { key: "lo_count", label: "LOs", class: W.num, numeric: true,
    hint: "the sheet's own headcount, to compare against what we scraped" },
  { key: "directory_url", label: "Directory URL", hint: "where the officers are listed" },
  { key: "company_url", label: "Company URL" },
  { key: "note", label: "Hint", hint: "told to the AI, e.g. \"Search Button\"" },
];

const BLANK = Object.fromEntries(COLUMNS.map((c) => [c.key, ""]));

// Every cell here is its own input, so the padding lives on the input and the
// cell gives it the whole width -- otherwise the box floats inside a padded td
// and the row reads as two grids.
const CELL = "border-b border-border p-0 align-middle";
// The cells that hold something other than an input. `py-0` and centred, so a
// status pill lines up with the text in the boxes either side of it: the
// editable cells' input carries its own padding and a negative margin to
// cancel it, which leaves it sitting ~10px higher than a padded cell's
// content. The row is then as tall as the input, which is the tallest thing
// in it.
const FLAT = "border-b border-border px-3 py-2 align-middle";
const CHECK = "size-4 cursor-pointer accent-accent align-middle";
// The way off this page. A link, not a button: in a table of 67 rows a
// bordered control per row is 67 borders, and this one leaves the page rather
// than doing something to it.
const DETAILS = "w-[84px]";
const DETAILS_LINK =
  "cursor-pointer rounded-md bg-transparent px-2 py-1 font-ui text-xs font-semibold " +
  "text-accent underline-offset-2 transition duration-120 hover:underline " +
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

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
    <td className={CELL + " " + col.class} data-label={col.label}>
      <input
        // min-w-0: in card mode the cell is a flex row (its label, then this),
        // and a flex item will not shrink past its content without it.
        className={NAME_INPUT + " w-full min-w-0 rounded-none!"}
        aria-label={col.label}
        aria-invalid={error ? "true" : undefined}
        autoComplete="off"
        inputMode={col.numeric ? "numeric" : undefined}
        placeholder={col.required ? "required" : "-"}
        // Fixed columns clip a long url mid-word; this is where you read it.
        title={text || undefined}
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

/**
 * What the last pass over this company amounts to, as one of six states.
 *
 * Six, not four, because `last_error` covers two different things: a run that
 * failed, and a company the batch passed over (no saved script yet, no url).
 * `job_id` is what tells them apart -- it is set only once a job actually ran.
 * Painting a skip red would make a fresh database of 67 companies look broken
 * when nothing had gone wrong at all.
 */
function outcomeOf(row) {
  if (row.last_error) return row.job_id ? "failed" : "skipped";
  return row.job_status || "not run";
}

// Each state, and what it means. The order is the order of the legend.
const OUTCOMES = {
  done: "scraped, officers merged in",
  running: "being scraped now",
  pending: "queued",
  failed: "the run produced nothing usable",
  skipped: "passed over: no saved script yet, or no url",
  "not run": "never attempted",
};

/** What the colours mean. A table of 67 rows is read by colour first, so the
 *  key for it belongs above the table, not in a tooltip. */
function Legend() {
  return (
    <div className="mb-4 flex flex-wrap items-center gap-x-6 gap-y-2">
      {Object.entries(OUTCOMES).map(([state, meaning]) => (
        <span key={state} className="inline-flex items-center gap-2">
          <StatusPill status={state} />
          <span className="text-xs text-mute">{meaning}</span>
        </span>
      ))}
    </div>
  );
}

/**
 * The Last run cell: the state, then as much of the reason as fits on the line.
 *
 * One line on purpose. This column used to print the whole error, which made
 * every row in the table a different height -- and the reason is nearly always
 * the same sentence, so it cost a lot of space to say very little. The full
 * text is on hover, and in the panel the row opens.
 */
function Outcome({ row }) {
  return (
    <div className="flex items-center gap-2 overflow-hidden" title={row.last_error || undefined}>
      <StatusPill status={outcomeOf(row)} />
      {/* {row.last_error && (
        <span className="truncate text-xs text-mute">{row.last_error}</span>
      )} */}
    </div>
  );
}

// The whole header row, editable columns plus the three the row only shows.
// Module-level and frozen in shape, the same reason browseTabs.jsx declares
// its columns there: the table reloads every two seconds while a batch runs,
// and a fresh columns array each time would rebuild the table with it.
const READ_ONLY = [
  { key: "officers", label: "Officers", class: W.num,
    hint: "how many we have actually scraped" },
  // Derived, not stored -- `value` is what the sort and the search see.
  { key: "outcome", label: "Last run", class: W.outcome, value: outcomeOf },
  { key: "details", label: "", class: DETAILS, sortable: false },
];
const TABLE_COLUMNS = [...COLUMNS, ...READ_ONLY];
const SELECT_COLUMNS = [
  { key: "select", label: "", class: W.drop, sortable: false },
  ...TABLE_COLUMNS,
];
const NO_ROWS = []; // one identity, so the table is not rebuilt before the fetch lands

function CompanyRow({ row, selectMode, checked, onCheck }) {
  const saveCompany = useStore((s) => s.saveCompany);
  const openCompany = useStore((s) => s.openCompany);

  return (
    <tr>
      {selectMode && (
        <td className={FLAT + " " + W.drop} data-label="Select">
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
      <td className={FLAT + " " + W.num} data-label="Officers">
        {row.officers || <span className="text-mute">-</span>}
      </td>
      <td className={FLAT + " " + W.outcome} data-label="Last run">
        <Outcome row={row} />
      </td>
      <td className={FLAT + " " + DETAILS}>
        <button
          type="button"
          className={DETAILS_LINK}
          aria-label={"Everything about " + row.name}
          title="Its runs, attempts, saved script and officers"
          onClick={() => openCompany(row.id)}
        >
          Details
        </button>
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

  const table = useDataTable(rows ?? NO_ROWS, selectMode ? SELECT_COLUMNS : TABLE_COLUMNS);

  // Derived, never stored: the table reloads every two seconds while a batch
  // runs, so a row can vanish under the selection. Intersecting here means a
  // deleted row leaves the count without anything having to prune the set.
  const selected = (rows ?? []).filter((r) => picked.has(r.id));
  const count = selected.length;
  // Against what the search left on screen, not against all 67: ticking
  // "select all" under a filter means the rows the filter found.
  const visible = table.getFilteredRowModel().rows.map((r) => r.original);
  const allPicked = visible.length > 0 && visible.every((r) => picked.has(r.id));

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

  const checkAll = (on) => setPicked(on ? new Set(visible.map((r) => r.id)) : new Set());

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

      {rows && <Legend />}
      {rows && (
        <TableShell
          table={table}
          placeholder="Search companies"
          // Select-all sits beside the search box rather than in the header
          // row, because on a phone the header row is not on screen at all --
          // and because under a filter it means "the ones you can see".
          actions={
            selectMode && (
              <label className="inline-flex cursor-pointer items-center gap-2 font-ui text-xs font-semibold text-dim">
                <input
                  type="checkbox"
                  className={CHECK}
                  checked={allPicked}
                  ref={(el) => {
                    if (el) el.indeterminate = count > 0 && !allPicked;
                  }}
                  onChange={(e) => checkAll(e.target.checked)}
                />
                Select all
              </label>
            )
          }
        >
          {table.getRowModel().rows.map((r) => (
            <CompanyRow
              key={r.original.id}
              row={r.original}
              selectMode={selectMode}
              checked={picked.has(r.original.id)}
              onCheck={check}
            />
          ))}
        </TableShell>
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
