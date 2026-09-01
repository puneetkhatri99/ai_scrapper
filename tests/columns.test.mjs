// What a column set turns into before TanStack sees it. Wrong here and a
// column simply stops sorting, or sorts by the wrong thing, without anything
// on screen looking broken. `npm test` in frontend/ runs it.
import assert from "node:assert/strict";
import { test } from "node:test";

import { columnDefs } from "../frontend/src/columns.js";

const row = { name: "Fairway", lo_count: 1988, last_error: "no script", job_id: null };

test("a plain column reads its key", () => {
  const [def] = columnDefs([{ key: "lo_count", label: "LOs" }]);
  assert.equal(def.id, "lo_count");
  assert.equal(def.header, "LOs");
  // The raw value, not a string: 1988 has to sort above 300, not below it.
  assert.equal(def.accessorFn(row), 1988);
  assert.equal(def.enableSorting, true);
});

test("`value` is what a derived column sorts and searches by", () => {
  const outcome = (r) => (r.last_error ? (r.job_id ? "failed" : "skipped") : "done");
  const [def] = columnDefs([{ key: "outcome", label: "Last run", value: outcome }]);
  // There is no `outcome` on the row -- without `value` this would be undefined
  // and every row in the column would tie.
  assert.equal(def.accessorFn(row), "skipped");
});

test("a column with nothing to order by does not offer a sort", () => {
  const defs = columnDefs([
    { key: "details", label: "", sortable: false },
    { key: "drop", label: "" }, // no header to click, so nothing to hang it on
    { key: "note", label: "Hint" },
  ]);
  assert.deepEqual(
    defs.map((d) => d.enableSorting),
    [false, false, true],
  );
});

test("the column itself rides along, so the cell keeps its width and hint", () => {
  const col = { key: "name", label: "Company", class: "w-[200px]", hint: "why" };
  const [def] = columnDefs([col]);
  assert.equal(def.meta, col);
});
