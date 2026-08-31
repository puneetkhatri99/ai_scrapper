import { isValidElement, useMemo } from "react";

import { cellText } from "../api";
import { TABLE, TBODY, TD, TH } from "../ui";

/**
 * Columns for rows with no declared shape: the union of every row's keys in
 * first-seen order. Extracted rows are not guaranteed to be uniform, so the
 * first row alone is not enough.
 */
export function unionColumns(rows) {
  const seen = new Set(); // one hash lookup per key, not a scan of the list
  const keys = [];
  for (const row of rows) {
    for (const k of Object.keys(row)) {
      if (seen.has(k)) continue;
      seen.add(k);
      keys.push(k);
    }
  }
  return keys.map((k) => ({ key: k, label: k }));
}

/** One cell. `col.render` may return a string or an element; both are fine. */
export function Cell({ row, col }) {
  const cls = col.class ? TD + " " + col.class : TD;
  const value = col.render ? col.render(row) : row[col.key];
  if (isValidElement(value)) return <td className={cls}>{value}</td>;

  const text = cellText(value);
  if (text === null) return <td className={cls + " text-mute"}>-</td>;
  return <td className={cls}>{text}</td>;
}

/**
 * A plain data table. Used for extracted results and script output, where
 * nothing is clickable -- the expandable one on the Browse page is
 * BrowseTable, which needs the store and this one does not.
 *
 * columns: [{key, label, render?, class?}]. Omit it for the union above.
 */
export function DataTable({ rows, columns }) {
  const cols = useMemo(() => columns ?? unionColumns(rows), [rows, columns]);

  return (
    <table className={TABLE}>
      <thead>
        <tr>
          {cols.map((c) => (
            <th key={c.label} className={TH}>
              {c.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody className={TBODY}>
        {rows.map((row, i) => (
          <tr key={i} className="even:bg-surface-2">
            {cols.map((col) => (
              <Cell key={col.label} row={row} col={col} />
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
