// The one piece of frontend logic that can be wrong without being visible:
// the builder rows <-> JSON Schema translation. `npm test` in frontend/ runs it.
// node:test and node:assert are built in, so this adds no dependency.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  EXAMPLE,
  PRESETS,
  fieldIssues,
  fieldsFromSchema,
  isStarterFields,
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

// --- what the builder says while you type ------------------------------------

test("a duplicate name is flagged on the second row, not the first", () => {
  const issues = fieldIssues([
    { name: "price", type: "number", required: false },
    { name: "title", type: "string", required: false },
    { name: "price", type: "string", required: false },
  ]);
  assert.equal(issues[0], null);
  assert.equal(issues[1], null);
  assert.match(issues[2], /already row 1/);
});

test("blank rows and names the API accepts are not flagged", () => {
  // pydantic takes both of these as field names, so the UI must not invent a
  // rule the backend does not have.
  const issues = fieldIssues([
    { name: "", type: "string", required: false },
    { name: "product name", type: "string", required: false },
    { name: "price-usd", type: "string", required: false },
  ]);
  assert.deepEqual(issues, [null, null, null]);
});

test("presets are only offered while there is nothing to lose", () => {
  assert.equal(isStarterFields(EXAMPLE), true);
  assert.equal(isStarterFields([{ name: "", type: "string", required: false }]), true);
  assert.equal(isStarterFields([{ name: "sku", type: "string", required: false }]), false);
});

test("every preset builds a schema the backend would accept", () => {
  for (const preset of PRESETS) {
    const schema = schemaFromFields(preset.fields);
    assert.equal(schema.type, "object", preset.name);
    assert.ok(Object.keys(schema.properties).length >= 3, preset.name);
    assert.deepEqual(fieldsFromSchema(schema), preset.fields, preset.name);
  }
});
