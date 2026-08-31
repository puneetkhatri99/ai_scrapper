import { BLANK, TYPES } from "../schema";
import { useStore } from "../store";

/**
 * The rows editor. Reads `draft.fields` straight from the store, so typing a
 * field name re-renders this component and nothing else on the page.
 */
export function SchemaBuilder() {
  const fields = useStore((s) => s.draft.fields);
  const patchDraft = useStore((s) => s.patchDraft);

  const setFields = (next) => patchDraft({ fields: next });
  const patch = (i, p) => setFields(fields.map((f, j) => (j === i ? { ...f, ...p } : f)));
  const drop = (i) => {
    const next = fields.filter((_, j) => j !== i);
    setFields(next.length ? next : [BLANK]); // never an empty builder
  };

  return (
    <div className="builder" role="group" aria-labelledby="fields-label">
      <div className="row-head">
        <span>Field name</span>
        <span>Type</span>
        <span>Required</span>
        <span />
      </div>

      <div>
        {fields.map((f, i) => (
          <div className="row" key={i}>
            <input
              type="text"
              aria-label="Field name"
              placeholder="price"
              value={f.name}
              onChange={(e) => patch(i, { name: e.target.value })}
            />
            <select
              aria-label="Field type"
              value={f.type}
              onChange={(e) => patch(i, { type: e.target.value })}
            >
              {TYPES.map(([value, text]) => (
                <option key={value} value={value}>
                  {text}
                </option>
              ))}
            </select>
            <span className="req">
              <input
                type="checkbox"
                aria-label="Required"
                checked={f.required}
                onChange={(e) => patch(i, { required: e.target.checked })}
              />
            </span>
            <button
              type="button"
              className="ghost drop"
              title="Remove this field"
              aria-label="Remove field"
              onClick={() => drop(i)}
            >
              ×
            </button>
          </div>
        ))}
      </div>

      <button type="button" className="ghost" onClick={() => setFields([...fields, BLANK])}>
        Add field
      </button>
    </div>
  );
}
