import { isValidElement, useMemo } from "react";

import { cellText } from "../api";
import { TD } from "../ui";
import { TableShell, useDataTable } from "./Table";

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

/** One cell. `col.render` may return a string or an element; both are fine.
 *  `data-label` is what the cell prints in front of itself once the table has
 *  folded into cards on a narrow screen -- see CARDS in ui.js. */
export function Cell({ row, col }) {
  const cls = col.class ? TD + " " + col.class : TD;
  const value = col.render ? col.render(row) : row[col.key];
  if (isValidElement(value))
    return (
      <td className={cls} data-label={col.label}>
        {value}
      </td>
    );

  const text = cellText(value);
  return (
    <td className={text === null ? cls + " text-mute" : cls} data-label={col.label}>
      {text === null ? "-" : text}
    </td>
  );
}

/**
 * A plain data table: sortable, searchable, paged, and read-only. Used for
 * extracted results and script output, where nothing is clickable -- the
 * expandable one on the Browse page is BrowseTable, which needs the store and
 * this one does not.
 *
 * columns: [{key, label, render?, class?}]. Omit it for the union above.
 *
 * Auto layout, not fixed: these column sets say "truncate to whatever is
 * left" without declaring a width, and the union columns declare nothing at
 * all. A search box over eight rows of output is noise, so it appears only
 * once there is enough here to lose something in.
 */
export function DataTable({ rows, columns }) {
  const cols = useMemo(() => columns ?? unionColumns(rows), [rows, columns]);
  const table = useDataTable(rows, cols);

  return (
    <TableShell table={table} fixed={false} search={rows.length > 10} placeholder="Search rows">
      {table.getRowModel().rows.map((r, i) => (
        <tr key={r.id} className={i % 2 ? "bg-surface-2" : undefined}>
          {cols.map((col) => (
            <Cell key={col.label} row={r.original} col={col} />
          ))}
        </tr>
      ))}
    </TableShell>
  );
}
