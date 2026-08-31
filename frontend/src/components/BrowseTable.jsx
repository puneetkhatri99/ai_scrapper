import { memo } from "react";

import { useStore } from "../store";
import { PICKS, TBODY, TH } from "../ui";
import { Cell } from "./DataTable";

/** Stable across renders and across refreshes, which is what makes an open row persist. */
export const rowKey = (tab, row, i) => `${tab}:${row.id || row.job_id || i}`;

// A clickable row. The hover and open states paint the cells rather than the
// <tr>, because a td's own background sits on top of its row's. Open also
// gets an accent edge down the left, so an expanded row is not just shaded.
const PICK =
  "cursor-pointer hover:[&>td]:bg-surface-2 " +
  "aria-expanded:[&>td]:bg-surface-2 " +
  "aria-expanded:[&>td]:shadow-[inset_2px_0_0_var(--color-accent)] " +
  "focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent";

// Zebra by class, not :nth-child: an inserted detail row would otherwise flip
// the parity of every row below it.
const ZEBRA = " bg-surface-2";

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
        className={index % 2 ? PICK + ZEBRA : PICK}
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
        <tr>
          {/* The detail sits on the page colour, a step back from the row it
              opened under. Its first section needs no top margin. */}
          <td
            className="border-b border-border bg-bg px-6 py-4 [&>div>*:first-child]:mt-0"
            colSpan={columns.length}
          >
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
    <table className={PICKS}>
      <thead>
        <tr>
          {columns.map((c) => (
            // Same class as the cells: the width lives on the column, and a
            // numeric column wants its header right-aligned with its digits.
            <th key={c.label} className={c.class ? TH + " " + c.class : TH}>
              {c.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody className={TBODY}>
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
