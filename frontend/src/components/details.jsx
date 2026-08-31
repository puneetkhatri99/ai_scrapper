import { useEffect, useState } from "react";

import { getJSON } from "../api";
import { CodeBlock } from "./CodeBlock";
import { DataTable } from "./DataTable";
import { ErrorBox, Pre, Scroll, Section, StateBox } from "./primitives";
import { RunAgain, RunScript } from "./RunAgain";
import { ACTIONS } from "../ui";

/** What opens under a row on the Jobs tab. */
export function JobDetail({ row }) {
  const [extra, setExtra] = useState(null);

  // The result and the winning script live behind GET /jobs/{id}, not in the
  // list row -- this is the only detail view that needs a second request.
  useEffect(() => {
    let live = true;
    getJSON("/jobs/" + row.id).then(
      (data) => live && setExtra({ data }),
      (err) => live && setExtra({ error: String(err) }),
    );
    return () => {
      live = false;
    };
  }, [row.id]);

  const job = extra?.data;
  return (
    <div>
      <div className={ACTIONS}>
        {job?.script && <RunScript job={row} code={job.script} />}
        <RunAgain job={row} />
      </div>
      <Section label="schema">
        <Pre text={JSON.stringify(row.json_schema, null, 2)} />
      </Section>
      <Section label="prompt">
        <Pre text={row.prompt} />
      </Section>

      {!extra && <StateBox text="loading..." />}
      {extra?.error && <ErrorBox text={extra.error} />}

      {job?.result?.length > 0 && (
        <Section label={`result (${job.result.length} rows)`}>
          <Scroll>
            <DataTable rows={job.result} />
          </Scroll>
        </Section>
      )}
      {job?.script && (
        <Section label="script">
          <CodeBlock code={job.script} />
        </Section>
      )}
      {row.error && (
        <Section label="error">
          <ErrorBox text={row.error} />
        </Section>
      )}
    </div>
  );
}

/** What opens under a row on the Attempts tab. Everything is already there. */
export function AttemptDetail({ row }) {
  return (
    <div>
      <Section label="script">
        <CodeBlock code={row.script_code} />
      </Section>
      {row.error_message && (
        <Section label="error">
          <ErrorBox text={row.error_message} />
        </Section>
      )}
      {row.output_json?.length > 0 && (
        <Section label={`output (${row.output_json.length} rows)`}>
          <Scroll>
            <DataTable rows={row.output_json} />
          </Scroll>
        </Section>
      )}
    </div>
  );
}

/** What opens under a row on the Saved scripts tab. */
export function ScriptDetail({ row }) {
  return (
    <div>
      <div className={ACTIONS}>
        <RunScript job={row} code={row.script_code} />
        <RunAgain job={row} label="Run this script again" />
      </div>
      <Section label="prompt">
        <Pre text={row.prompt} />
      </Section>
      <Section label="schema">
        <Pre text={JSON.stringify(row.json_schema, null, 2)} />
      </Section>
      <Section label="script">
        <CodeBlock code={row.script_code} />
      </Section>
    </div>
  );
}

/**
 * What opens under a row on the Loan officers tab.
 *
 * No actions: these rows are scraped, and the next run merges over them, so
 * there is nothing here a user could edit that would survive. The one thing
 * worth showing is where the row came from and when.
 */
export function OfficerDetail({ row }) {
  return (
    <div>
      <Section label="address">
        <Pre text={row.address || "-"} />
      </Section>
      <Section label="scraped from">
        <Pre text={row.source_url || "-"} />
      </Section>
    </div>
  );
}
