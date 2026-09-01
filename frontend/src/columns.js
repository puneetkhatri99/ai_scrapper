// The project's column shape as TanStack column definitions. No DOM and no
// React in here, the same reason schema.js has none: this is the one bit of
// the table that is ours rather than the library's, and it is the bit that
// silently un-sorts a column if it drifts.
//
// A column is {key, label, class?, render?, hint?} and two optional keys the
// table added: `value` for a column that is derived rather than stored (the
// Companies page's "Last run" is one), and `sortable: false` for a column
// there is nothing to order by.

/**
 * The accessor hands back the raw value, never the rendered cell: a status
 * column has to sort by "done" and "failed" rather than by the pill drawn for
 * them, and a count column has to sort as a number, not as its digits.
 */
export function columnDefs(columns) {
  return columns.map((c) => ({
    id: c.key ?? c.label,
    accessorFn: c.value ?? ((row) => row[c.key]),
    header: c.label,
    // An unlabelled column has no header to click, so there is nothing to
    // hang a sort on even when the values would order fine.
    enableSorting: c.sortable !== false && !!c.label,
    meta: c,
  }));
}
