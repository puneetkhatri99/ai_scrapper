import { useState } from "react";

import {
  BLANK,
  PRESETS,
  TYPES,
  fieldIssues,
  isStarterFields,
  schemaFromFields,
} from "../schema";
import { useStore } from "../store";
import { GHOST, HINT, INPUT, ISSUE, SELECT } from "../ui";

// The four columns, shared by the header and every row. Under 640px the header
// goes and the row falls to two columns, so a field is two lines, not four.
const GRID = "grid grid-cols-[1fr_150px_88px_34px] items-center gap-2 max-sm:grid-cols-2";

// The × at the end of a row: no chrome until you are over it.
const DROP =
  "h-8 cursor-pointer border border-transparent bg-transparent p-0 font-ui text-lg " +
  "leading-none text-mute transition duration-120 hover:text-failed " +
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

/**
 * The rows editor. Reads `draft.fields` straight from the store, so typing a
 * field name re-renders this component and nothing else on the page.
 *
 * Three things make it a builder rather than a list of inputs: it validates
 * while you type instead of at submit, it shows the JSON it is about to send,
 * and Enter inserts the next row where you are.
 */
export function SchemaBuilder() {
  const fields = useStore((s) => s.draft.fields);
  const patchDraft = useStore((s) => s.patchDraft);
  // Which row to focus after an insert. React honours autoFocus on mount only,
  // so this cannot steal focus back on an unrelated re-render.
  const [focusRow, setFocusRow] = useState(-1);

  const setFields = (next) => patchDraft({ fields: next });
  const patch = (i, p) => setFields(fields.map((f, j) => (j === i ? { ...f, ...p } : f)));

  const drop = (i) => {
    const next = fields.filter((_, j) => j !== i);
    setFields(next.length ? next : [BLANK]); // never an empty builder
  };

  const insertAfter = (i) => {
    setFields([...fields.slice(0, i + 1), BLANK, ...fields.slice(i + 1)]);
    setFocusRow(i + 1);
  };

  const issues = fieldIssues(fields);
  const named = fields.filter((f) => f.name.trim()).length;
  const required = fields.filter((f) => f.name.trim() && f.required).length;

  return (
    <div
      className="rounded-lg border border-border bg-surface p-3"
      role="group"
      aria-labelledby="fields-label"
    >
      {isStarterFields(fields) && (
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <span className={HINT}>Start from</span>
          {PRESETS.map((p) => (
            <button
              key={p.name}
              type="button"
              className={GHOST}
              onClick={() => setFields(p.fields)}
            >
              {p.name}
            </button>
          ))}
        </div>
      )}

      <div
        className={
          GRID +
          " px-1 pb-2 font-ui text-[11px] font-semibold tracking-[.06em] uppercase text-mute max-sm:hidden"
        }
      >
        <span>Field name</span>
        <span>Type</span>
        <span>Required</span>
        <span />
      </div>

      <div>
        {fields.map((f, i) => (
          <div
            // On a narrow screen the rows stack, so they need a rule between
            // them: two columns of inputs alone do not read as separate fields.
            className={i ? "mt-2 max-sm:mt-4 max-sm:border-t max-sm:border-border max-sm:pt-4" : ""}
            key={i}
          >
            <div className={GRID}>
              <input
                type="text"
                className={INPUT}
                aria-label="Field name"
                aria-invalid={issues[i] ? "true" : undefined}
                autoFocus={i === focusRow}
                placeholder="price"
                value={f.name}
                onChange={(e) => patch(i, { name: e.target.value })}
                onKeyDown={(e) => {
                  // Enter inside a form submits it. In a row editor the useful
                  // meaning is "next field", so take it over.
                  if (e.key !== "Enter") return;
                  e.preventDefault();
                  insertAfter(i);
                }}
              />
              <select
                className={SELECT}
                aria-label="Field type"
                value={f.type}
                onChange={(e) => patch(i, { type: e.target.value })}
              >
                {TYPES.map(([value, text]) => (
                  <option key={value} value={value}>
                    {text}
                  </option>
                ))}
              </select>
              <span className="flex h-full items-center justify-center">
                <input
                  type="checkbox"
                  className="size-4 cursor-pointer accent-accent"
                  aria-label="Required"
                  checked={f.required}
                  onChange={(e) => patch(i, { required: e.target.checked })}
                />
              </span>
              <button
                type="button"
                className={DROP}
                title="Remove this field"
                aria-label="Remove field"
                onClick={() => drop(i)}
              >
                ×
              </button>
            </div>
            {issues[i] && (
              <p className={ISSUE} role="alert">
                {issues[i]}
              </p>
            )}
          </div>
        ))}
      </div>

      <div className="mt-3 flex items-center justify-between gap-3">
        <button type="button" className={GHOST} onClick={() => insertAfter(fields.length - 1)}>
          Add field
        </button>
        <span className={HINT}>
          {named
            ? `${named} field${named === 1 ? "" : "s"}, ${required} required`
            : "Name at least one field"}
        </span>
      </div>

      {/* Native disclosure: the JSON that will be posted, without leaving the
          rows to see it. No state, no library. */}
      <details className="mt-3 border-t border-border pt-3">
        <summary className="cursor-pointer text-xs font-semibold text-dim hover:text-text focus-visible:rounded-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">
          Schema preview
        </summary>
        <pre className="mt-3 max-h-60 overflow-x-auto rounded-lg border border-border bg-surface-2 p-4 font-mono text-[13px] leading-[1.6] text-text">
          {JSON.stringify(schemaFromFields(fields), null, 2)}
        </pre>
      </details>
    </div>
  );
}
