// The one piece of frontend logic that can be wrong without being visible:
// the builder rows <-> JSON Schema translation. `npm test` in frontend/ runs it.
// node:test and node:assert are built in, so this adds no dependency.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  EXAMPLE,
  fieldsFromSchema,
  schemaFromFields,
} from "../frontend/src/schema.js";

test("rows become a flat schema, and unnamed rows are dropped", () => {
  assert.deepEqual(
    schemaFromFields([
      { name: "title", type: "string", required: true },
      { name: " price ", type: "number", required: false },
      { name: "  ", type: "string", required: true },      // never filled in
    ]),
    {
      type: "object",
      properties: { title: { type: "string" }, price: { type: "number" } },
      required: ["title"],
    },
  );
});

test("no required field means no `required` key at all", () => {
  const schema = schemaFromFields([{ name: "title", type: "string", required: false }]);
  assert.equal("required" in schema, false);
});

test("a schema this builder wrote survives a round trip", () => {
  assert.deepEqual(fieldsFromSchema(schemaFromFields(EXAMPLE)), EXAMPLE);
});

test("a list-of-objects schema is unwrapped to its item fields", () => {
  assert.deepEqual(
    fieldsFromSchema({ type: "array", items: schemaFromFields(EXAMPLE) }),
    EXAMPLE,
  );
});

test("anything the rows cannot express returns null, not a lossy guess", () => {
  // Null keeps the editor in JSON mode. Rendering these as rows would quietly
  // drop the parts the rows have no way to show.
  for (const schema of [
    { type: "object", properties: { seller: { type: "object" } } },   // nested
    { type: "object", properties: { price: { type: "money" } } },     // unknown
    { type: "object" },                                               // no props
    null,
    "not a schema",
  ]) {
    assert.equal(fieldsFromSchema(schema), null, JSON.stringify(schema));
  }
});
