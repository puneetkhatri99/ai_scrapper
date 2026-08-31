import { JobCard } from "../components/JobCard";
import { SchemaBuilder } from "../components/SchemaBuilder";
import { ErrorBox } from "../components/primitives";
import { selectBusy, useStore } from "../store";
import {
  BTN,
  CARD,
  FIELD,
  FIELD_LABEL,
  H1,
  HINT,
  INPUT,
  ISSUE,
  MAIN_NARROW,
  SEG,
  SEG_BTN,
  TEXTAREA,
} from "../ui";

// Each field subscribes to its own slice of the draft. That is the whole
// reason for a store here: typing in the prompt box re-renders the prompt box,
// not the schema builder and not the results table below it.

function NameField() {
  const name = useStore((s) => s.draft.name);
  const patchDraft = useStore((s) => s.patchDraft);
  return (
    <div className={FIELD}>
      <label className={FIELD_LABEL} htmlFor="name">
        Name <span className={HINT}>optional</span>
      </label>
      <input
        className={INPUT}
        id="name"
        maxLength={120}
        autoComplete="off"
        placeholder="Competitor prices"
        value={name}
        onChange={(e) => patchDraft({ name: e.target.value })}
      />
    </div>
  );
}

function UrlField() {
  const url = useStore((s) => s.draft.url);
  const patchDraft = useStore((s) => s.patchDraft);
  return (
    <div className={FIELD}>
      <label className={FIELD_LABEL} htmlFor="url">
        Page to scrape
      </label>
      <input
        className={INPUT}
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

  // Parsed on every keystroke: a syntax error is worth knowing about while you
  // are still looking at the line, not after a submit round trip.
  let jsonError = null;
  if (jsonMode) {
    try {
      JSON.parse(jsonText);
    } catch (err) {
      jsonError = err.message;
    }
  }

  return (
    <div className={FIELD}>
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <label className="text-dim" id="fields-label">
          Fields to extract
        </label>
        {/* Two modes, both visible. A single toggle button never says what the
            other side is until you have already pressed it. */}
        <div className={SEG} role="group" aria-label="Schema editor">
          <button
            type="button"
            className={SEG_BTN}
            aria-pressed={!jsonMode}
            onClick={() => jsonMode && toggleJsonMode()}
          >
            Fields
          </button>
          <button
            type="button"
            className={SEG_BTN}
            aria-pressed={jsonMode}
            onClick={() => !jsonMode && toggleJsonMode()}
          >
            JSON
          </button>
        </div>
      </div>
      <p className={HINT}>
        {jsonMode
          ? "Raw JSON Schema. Switch back to fields if it stays flat."
          : "One row per piece of data you want back from each item on the page."}
      </p>

      {jsonMode ? (
        <>
          <textarea
            className={TEXTAREA}
            rows="10"
            spellCheck="false"
            aria-label="JSON schema"
            aria-invalid={jsonError ? "true" : undefined}
            value={jsonText}
            onChange={(e) => patchDraft({ jsonText: e.target.value })}
          />
          {jsonError && (
            <p className={ISSUE} role="alert">
              {jsonError}
            </p>
          )}
        </>
      ) : (
        <SchemaBuilder />
      )}
    </div>
  );
}

/**
 * Bring your own script. Collapsed until there is one, because the normal path
 * is to let the model write it -- this is the escape hatch for when you would
 * rather fix a selector by hand than pay for another generation.
 */
function ScriptField() {
  const script = useStore((s) => s.draft.script);
  const patchDraft = useStore((s) => s.patchDraft);

  return (
    <details className={FIELD} open={!!script}>
      <summary className="mb-2 cursor-pointer text-dim hover:text-text focus-visible:rounded-md focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent">
        Run a script instead
      </summary>
      <p className={HINT}>
        A <code className="font-mono text-dim">def run(page)</code>. It runs exactly as written, in the same
        sandbox the generated ones use -- separate process, no imports, 120s cap
        -- and nothing is sent to the model. Leave this empty to have one written
        for you.
      </p>
      <textarea
        className={TEXTAREA}
        rows="12"
        spellCheck="false"
        aria-label="Script"
        placeholder="def run(page):&#10;    ..."
        value={script}
        onChange={(e) => patchDraft({ script: e.target.value })}
      />
    </details>
  );
}

function PromptField() {
  const prompt = useStore((s) => s.draft.prompt);
  const patchDraft = useStore((s) => s.patchDraft);
  return (
    <div className={FIELD}>
      <label className={FIELD_LABEL} htmlFor="prompt">
        What should it do?
      </label>
      <p className={HINT} id="prompt-hint">
        Plain English. Include any searching, clicking or paging it needs to do.
      </p>
      <textarea
        className={TEXTAREA}
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
  // Say which of the two this is about to do. A script in the box is a
  // sandboxed run of that code; an empty box is recon plus a generation.
  const sandbox = useStore((s) => !!s.draft.script.trim());

  return (
    <>
      {formError && <ErrorBox text={formError} />}
      <div className="flex justify-end">
        <button type="submit" className={BTN} disabled={busy}>
          {busy ? "Running..." : sandbox ? "Run script in sandbox" : "Run scrape"}
        </button>
      </div>
    </>
  );
}

export function NewJob() {
  const submitJob = useStore((s) => s.submitJob);

  return (
    <main className={MAIN_NARROW}>
      <h1 className={H1 + " mb-6"}>New job</h1>

      <section className={CARD}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            submitJob();
          }}
        >
          <NameField />
          <UrlField />
          <SchemaField />
          <PromptField />
          <ScriptField />
          <SubmitBar />
        </form>
      </section>

      <JobCard />
    </main>
  );
}
