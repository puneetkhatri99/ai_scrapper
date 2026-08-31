// The builder <-> JSON Schema translation, kept out of app.js because it is
// the only frontend logic worth a test and the only piece that touches
// neither React nor the DOM. tests/schema.test.mjs imports this file directly.

// Plain English on the left, JSON Schema on the right. Flat types only --
// build_validator in backend/models.py validates flat properties, so the
// builder cannot express something the backend would silently ignore.
export const TYPES = [
  ["string", "Text"],
  ["integer", "Whole number"],
  ["number", "Decimal"],
  ["boolean", "Yes / no"],
  ["array", "List"],
];

const TYPE_NAMES = new Set(TYPES.map(([value]) => value));

export const BLANK = { name: "", type: "string", required: false };

export const EXAMPLE = [
  { name: "title", type: "string", required: true },
  { name: "price", type: "string", required: false },
];

// Starting points, not templates to fill in: clicking one replaces the rows.
// Offered only while nothing has been typed (isStarterFields), so a click can
// never throw away work.
export const PRESETS = [
  {
    name: "Products",
    fields: [
      { name: "name", type: "string", required: true },
      { name: "price", type: "number", required: false },
      { name: "url", type: "string", required: false },
      { name: "in_stock", type: "boolean", required: false },
    ],
  },
  {
    name: "Articles",
    fields: [
      { name: "title", type: "string", required: true },
      { name: "author", type: "string", required: false },
      { name: "published", type: "string", required: false },
      { name: "url", type: "string", required: false },
    ],
  },
  {
    name: "Listings",
    fields: [
      { name: "name", type: "string", required: true },
      { name: "address", type: "string", required: false },
      { name: "phone", type: "string", required: false },
      { name: "rating", type: "number", required: false },
    ],
  },
];

/** True while the rows are still the default or entirely unnamed. */
export function isStarterFields(fields) {
  return (
    fields.every((f) => !f.name.trim()) ||
    JSON.stringify(fields) === JSON.stringify(EXAMPLE)
  );
}

/**
 * Per-row problems, index-aligned with `fields`, null where a row is fine.
 *
 * Duplicates only. A second row with the same name silently overwrites the
 * first in schemaFromFields, which is the one mistake here that loses data
 * without saying so. Everything else the backend genuinely accepts: pydantic
 * takes "product name" and "price-usd" as field names, so rejecting them in
 * the UI would be inventing a rule the API does not have.
 */
export function fieldIssues(fields) {
  const firstSeen = new Map();
  return fields.map((f, i) => {
    const name = f.name.trim();
    if (!name) return null; // blank rows are dropped, not wrong
    if (firstSeen.has(name)) return `"${name}" is already row ${firstSeen.get(name) + 1}.`;
    firstSeen.set(name, i);
    return null;
  });
}

/** Builder rows -> JSON Schema. Unnamed rows are skipped, not exported blank. */
export function schemaFromFields(fields) {
  const properties = {};
  const required = [];
  for (const f of fields) {
    const key = f.name.trim();
    if (!key) continue;
    properties[key] = { type: f.type };
    if (f.required) required.push(key);
  }
  const schema = { type: "object", properties };
  if (required.length) schema.required = required;
  return schema;
}

/**
 * JSON Schema -> builder rows, or null if it is not flat enough to show.
 * Null is the signal to stay in JSON mode: rendering a nested schema as rows
 * would silently drop the parts the rows cannot express.
 */
export function fieldsFromSchema(schema) {
  let s = schema;
  if (s && s.type === "array" && s.items && typeof s.items === "object") s = s.items;
  if (!s || typeof s !== "object" || !s.properties) return null;

  const required = new Set(s.required || []);
  const fields = [];
  for (const [name, spec] of Object.entries(s.properties)) {
    const type = spec && spec.type;
    if (!TYPE_NAMES.has(type)) return null;         // nested or unknown
    fields.push({ name, type, required: required.has(name) });
  }
  return fields.length ? fields : EXAMPLE;
}
