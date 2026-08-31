import { memo } from "react";

import { useStore } from "../store";
import { Cell } from "./DataTable";

/** Stable across renders and across refreshes, which is what makes an open row persist. */
export const rowKey = (tab, row, i) => `${tab}:${row.id || row.job_id || i}`;

/**
 * One row plus its detail row.
 *
 * memo, and the row subscribes to its own open flag rather than being handed
 * it: opening row 5 of 200 re-renders row 5. Passing `openRows` down instead
 * would re-render all 200 on every click, since the object identity changes.
 */
const Row = memo(function Row({ row, index, tab, columns, Detail }) {
  const key = rowKey(tab, row, index);
  const isOpen = useStore((s) => !!s.openRows[key]); // a boolean, so no churn
  const toggleRow = useStore((s) => s.toggleRow); // actions never change identity

  const toggle = () => toggleRow(key);

  return (
    <>
      <tr
        className={index % 2 ? "pick zebra" : "pick"}
        tabIndex={0}
        aria-expanded={String(isOpen)}
        onClick={toggle}
        onKeyDown={(e) => {
          if (e.key !== "Enter" && e.key !== " ") return;
          e.preventDefault();
          toggle();
        }}
      >
        {columns.map((col) => (
          <Cell key={col.label} row={row} col={col} />
        ))}
      </tr>
      {isOpen && (
        <tr className="detail">
          <td colSpan={columns.length}>
            <Detail row={row} />
          </td>
        </tr>
      )}
    </>
  );
});

/** The Browse page's table: every row expands to show what the LLM produced. */
export function BrowseTable({ rows, tab, columns, Detail }) {
  return (
    <table className="picks">
      <thead>
        <tr>
          {columns.map((c) => (
            <th key={c.label}>{c.label}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, i) => (
          <Row
            key={rowKey(tab, row, i)}
            row={row}
            index={i}
            tab={tab}
            columns={columns}
            Detail={Detail}
          />
        ))}
      </tbody>
    </table>
  );
}
