import { JobCard } from "../components/JobCard";
import { SchemaBuilder } from "../components/SchemaBuilder";
import { ErrorBox } from "../components/primitives";
import { selectBusy, useStore } from "../store";

// Each field subscribes to its own slice of the draft. That is the whole
// reason for a store here: typing in the prompt box re-renders the prompt box,
// not the schema builder and not the results table below it.

function UrlField() {
  const url = useStore((s) => s.draft.url);
  const patchDraft = useStore((s) => s.patchDraft);
  return (
    <div className="field">
      <label htmlFor="url">Page to scrape</label>
      <input
        id="url"
        type="url"
        required
        autoComplete="off"
        placeholder="https://example.com/products"
        value={url}
        onChange={(e) => patchDraft({ url: e.target.value })}
      />
    </div>
  );
}

function SchemaField() {
  const jsonMode = useStore((s) => s.draft.jsonMode);
  const jsonText = useStore((s) => s.draft.jsonText);
  const patchDraft = useStore((s) => s.patchDraft);
  const toggleJsonMode = useStore((s) => s.toggleJsonMode);

  return (
    <div className="field">
      <div className="field-head">
        <label id="fields-label">Fields to extract</label>
        <button type="button" className="ghost" onClick={toggleJsonMode}>
          {jsonMode ? "Edit as fields" : "Edit as JSON"}
        </button>
      </div>
      <p className="hint">
        {jsonMode
          ? "Raw JSON Schema. Switch back to fields if it stays flat."
          : "One row per piece of data you want back from each item on the page."}
      </p>

      {jsonMode ? (
        <textarea
          rows="10"
          spellCheck="false"
          aria-label="JSON schema"
          value={jsonText}
          onChange={(e) => patchDraft({ jsonText: e.target.value })}
        />
      ) : (
        <SchemaBuilder />
      )}
    </div>
  );
}

function PromptField() {
  const prompt = useStore((s) => s.draft.prompt);
  const patchDraft = useStore((s) => s.patchDraft);
  return (
    <div className="field">
      <label htmlFor="prompt">What should it do?</label>
      <p className="hint" id="prompt-hint">
        Plain English. Include any searching, clicking or paging it needs to do.
      </p>
      <textarea
        id="prompt"
        rows="4"
        spellCheck="false"
        required
        aria-describedby="prompt-hint"
        placeholder='search for "running shoes" and get the first 20 results across all pages'
        value={prompt}
        onChange={(e) => patchDraft({ prompt: e.target.value })}
      />
    </div>
  );
}

function SubmitBar() {
  const busy = useStore(selectBusy);
  const formError = useStore((s) => s.formError);
  return (
    <>
      {formError && <ErrorBox text={formError} />}
      <div className="actions">
        <button type="submit" disabled={busy}>
          {busy ? "Running..." : "Run scrape"}
        </button>
      </div>
    </>
  );
}

export function NewJob() {
  const submitJob = useStore((s) => s.submitJob);

  return (
    <main className="narrow">
      <h1>New job</h1>

      <section className="card">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submitJob();
          }}
        >
          <UrlField />
          <SchemaField />
          <PromptField />
          <SubmitBar />
        </form>
      </section>

      <JobCard />
    </main>
  );
}
