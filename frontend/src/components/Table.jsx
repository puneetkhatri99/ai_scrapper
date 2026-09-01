// The one table engine: TanStack Table, headless. It owns sorting, the search
// box and paging; the markup stays here so a table is still a <table> and the
// rows stay with the page that knows how to draw them -- an expandable row on
// Browse, a row of inputs on Companies.
//
// Columns keep the shape the project already had, {key, label, class, render},
// so browseTabs.jsx and Company.jsx did not have to change. Two optional keys
// are new: `value` for a column that is derived rather than stored, and
// `sortable: false` for one there is nothing to sort by.

import { useMemo, useRef, useState } from "react";
import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getPaginationRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";

import { columnDefs } from "../columns";
import { GHOST, HINT, INPUT, PICKS, TABLE, TBODY, TH } from "../ui";
import { Scroll, StateBox } from "./primitives";

/** Big enough that the common table is one page, small enough that the
 *  officers list does not render four thousand rows into the DOM. */
const PAGE_SIZE = 50;

const TOOLBAR = "mb-3 flex flex-wrap items-center gap-3";
const SEARCH = INPUT + " w-auto max-w-full grow-0 basis-[280px] py-2 text-xs";
/** Narrow enough to still be a column, wide enough to grab. */
const MIN_W = 64;
/** The drag target: the column's right edge, straddling it. Invisible until
 *  you are on it, the way a spreadsheet's is. */
const GRIP =
  "absolute top-0 right-0 z-10 h-full w-2 cursor-col-resize touch-none " +
  "hover:bg-accent/40 max-md:hidden";
const SORT =
  "inline-flex cursor-pointer items-center gap-1 bg-transparent p-0 font-ui text-xs " +
  "font-semibold tracking-[.06em] text-mute uppercase hover:text-text " +
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

/** Wire a set of rows to a table instance. columns.js does the mapping. */
export function useDataTable(rows, columns, pageSize = PAGE_SIZE) {
  const [sorting, setSorting] = useState([]);
  const [globalFilter, setGlobalFilter] = useState("");
  const defs = useMemo(() => columnDefs(columns), [columns]);

  return useReactTable({
    data: rows,
    columns: defs,
    state: { sorting, globalFilter },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize } },
    // Keyed on the row, not its place in the array: the Companies table
    // reloads under the reader, and an index key would hand row 4's half-typed
    // input to whatever lands in slot 4 next.
    getRowId: (row, i) => String(row.id ?? i),
    // The Companies table reloads every two seconds while a batch runs. Left
    // on, that would throw the reader back to page 1 mid-scroll.
    autoResetPageIndex: false,
  });
}

/** A header cell. A button, not a th with onClick: sorting has to be reachable
 *  from the keyboard, and aria-sort is what says which way it went.
 *
 *  The right edge drags to resize, and double-clicks back to the default.
 *  Ours rather than TanStack's handler for one reason: it starts from the
 *  width the column is actually rendering. Nearly every column here sizes
 *  itself from a class or from the space left over, and the library's handler
 *  starts from a number it made up, so the first pixel of drag snaps. */
function HeadCell({ header, table }) {
  const col = header.column;
  const meta = col.columnDef.meta ?? {};
  const dir = col.getIsSorted();
  const label = flexRender(col.columnDef.header, header.getContext());
  const ref = useRef(null);

  const drag = (e) => {
    e.preventDefault(); // no text selection, and no sort from the mousedown
    const from = (e.touches?.[0] ?? e).clientX;
    const start = ref.current.offsetWidth;
    const move = (ev) => {
      const x = (ev.touches?.[0] ?? ev).clientX;
      table.setColumnSizing((s) => ({ ...s, [col.id]: Math.max(MIN_W, start + x - from) }));
    };
    const stop = () => {
      document.removeEventListener("mousemove", move);
      document.removeEventListener("mouseup", stop);
      document.removeEventListener("touchmove", move);
      document.removeEventListener("touchend", stop);
      document.body.style.userSelect = "";
    };
    document.body.style.userSelect = "none";
    document.addEventListener("mousemove", move);
    document.addEventListener("mouseup", stop);
    document.addEventListener("touchmove", move, { passive: false });
    document.addEventListener("touchend", stop);
  };

  return (
    <th
      ref={ref}
      className={(meta.class ? TH + " " + meta.class : TH) + " relative"}
      // Set only once dragged: unset, the column keeps whatever its class or
      // the leftover space gives it, which is the layout every table has now.
      style={{ width: table.getState().columnSizing[col.id] }}
      title={meta.hint}
      aria-sort={dir ? (dir === "asc" ? "ascending" : "descending") : undefined}
    >
      {col.getCanSort() ? (
        <button type="button" className={SORT} onClick={col.getToggleSortingHandler()}>
          {label}
          <span aria-hidden="true" className={dir ? "text-accent" : "text-border-hi"}>
            {dir === "desc" ? "\u2193" : "\u2191"}
          </span>
        </button>
      ) : (
        label
      )}
      <span
        role="separator"
        aria-orientation="vertical"
        aria-label={"Resize " + (meta.label || col.id) + " column"}
        title="Drag to resize, double-click to reset"
        className={GRIP}
        onMouseDown={drag}
        onTouchStart={drag}
        onDoubleClick={() => col.resetSize()}
      />
    </th>
  );
}

/** Only shown when there is more than one page -- most tables here have one. */
function Pager({ table }) {
  const { pageIndex, pageSize } = table.getState().pagination;
  const total = table.getFilteredRowModel().rows.length;
  if (total <= pageSize) return null;

  const first = pageIndex * pageSize + 1;
  return (
    <div className="mt-3 flex flex-wrap items-center justify-end gap-3">
      <span className={HINT}>
        {first}-{Math.min(total, first + pageSize - 1)} of {total}
      </span>
      <button
        type="button"
        className={GHOST}
        disabled={!table.getCanPreviousPage()}
        onClick={() => table.previousPage()}
      >
        Previous
      </button>
      <button
        type="button"
        className={GHOST}
        disabled={!table.getCanNextPage()}
        onClick={() => table.nextPage()}
      >
        Next
      </button>
    </div>
  );
}

/**
 * The search box, the header row, the scroll box and the pager. `children` is
 * the tbody -- every page draws its own rows, because they are all different.
 *
 * `actions` is anything that belongs beside the search box; the Companies page
 * puts its select-all there rather than in the header row, because on a phone
 * the header row is not on screen at all.
 */
export function TableShell({
  table,
  search = true,
  placeholder = "Search",
  actions,
  // Fixed layout needs every wide column to declare a width; the tables whose
  // columns only say "truncate to whatever is left" want auto.
  fixed = true,
  children,
}) {
  const filter = table.getState().globalFilter ?? "";
  const total = table.getFilteredRowModel().rows.length;

  return (
    <>
      {(search || actions) && (
        <div className={TOOLBAR}>
          {search && (
            <input
              className={SEARCH}
              type="search"
              autoComplete="off"
              aria-label={placeholder}
              placeholder={placeholder}
              value={filter}
              onChange={(e) => {
                table.setGlobalFilter(e.target.value);
                table.setPageIndex(0); // page 4 of the old result set means nothing
              }}
            />
          )}
          {actions}
          <span className={HINT + " ml-auto"}>
            {total} {total === 1 ? "row" : "rows"}
          </span>
        </div>
      )}

      {total === 0 ? (
        <StateBox text={filter ? `nothing matches "${filter}"` : "nothing here"} />
      ) : (
        <>
          <Scroll>
            <table className={fixed ? PICKS : TABLE}>
              <thead>
                {table.getHeaderGroups().map((group) => (
                  <tr key={group.id}>
                    {group.headers.map((header) => (
                      <HeadCell key={header.id} header={header} table={table} />
                    ))}
                  </tr>
                ))}
              </thead>
              <tbody className={TBODY}>{children}</tbody>
            </table>
          </Scroll>
          <Pager table={table} />
        </>
      )}
    </>
  );
}
