import { useEffect, useState } from "react";

import { getJSON, when } from "../api";
import { CodeBlock } from "../components/CodeBlock";
import { DataTable } from "../components/DataTable";
import { ErrorBox, Pre, Section, StateBox, StatusPill } from "../components/primitives";
import { useStore } from "../store";
import { CARD_HEAD, GHOST, H1, HINT, LABEL, MAIN, NUM, W } from "../ui";

// The three tables on this page. Module-level so they keep one identity, the
// same reason browseTabs.jsx declares its columns there.
const RUN_COLUMNS = [
  { key: "created_at", label: "When", class: W.when, render: (r) => when(r.created_at) },
  { key: "status", label: "Status", class: W.status,
    render: (r) => <StatusPill status={r.status} /> },
  { key: "attempts", label: "Attempts", class: W.num + " " + NUM },
  // Auto-layout tables ignore `truncate` with nothing to truncate to, and the
  // whole error is in the box at the top of the page anyway.
  { key: "error", label: "Error", class: "max-w-[520px] truncate" },
];

const ATTEMPT_COLUMNS = [
  // 0 is not a real attempt: it is the saved script being replayed.
  { key: "attempt_number", label: "Attempt", class: W.tag,
    render: (r) => (r.attempt_number === 0 ? "replay" : String(r.attempt_number)) },
  { key: "success", label: "Result", class: W.tag,
    render: (r) => (r.success ? "ok" : "failed") },
  { key: "rows", label: "Rows", class: W.num + " " + NUM },
  { key: "error_message", label: "Error", class: "max-w-[520px] truncate" },
];

const OFFICER_COLUMNS = [
  { key: "name", label: "Name", class: W.co },
  { key: "nmls_id", label: "NMLS #", class: W.tag },
  { key: "position", label: "Position", class: "truncate" },
  { key: "email", label: "Email", class: "truncate" },
  { key: "phone", label: "Phone", class: "w-[140px] whitespace-nowrap" },
  { key: "updated_at", label: "Updated", class: W.when, render: (r) => when(r.updated_at) },
];

// The company's own columns, in the order the table on the previous page has
// them. Read-only here: the table is where a company is edited, and two places
// to change one field is one place too many.
const FACTS = [
  ["NMLS #", "nmls_id"],
  ["Officers on the sheet", "lo_count"],
  ["Directory URL", "directory_url"],
  ["Company URL", "company_url"],
  ["Hint for the AI", "note"],
];

function Facts({ company }) {
  return (
    <dl className="mb-2 grid gap-x-8 gap-y-3 sm:grid-cols-[max-content_1fr]">
      {FACTS.map(([label, key]) => (
        <div key={key} className="contents">
          <dt className={LABEL + " self-center"}>{label}</dt>
          <dd className="m-0 font-mono text-[13px] break-all">
            {company[key] ?? <span className="text-mute">-</span>}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * Everything about one company, on its own page.
 *
 * One fetch: GET /companies/{id}/detail gathers the row, its runs, the last
 * run's attempts, the saved script and the officers together. It carries the
 * company row too, so this page works from an id alone -- which is what makes
 * it survive a refresh, since `companyId` is persisted beside `page`.
 */
export function Company() {
  const companyId = useStore((s) => s.companyId);
  const setPage = useStore((s) => s.setPage);
  const [extra, setExtra] = useState(null);

  useEffect(() => {
    if (!companyId) return;
    let live = true;
    setExtra(null);
    getJSON("/companies/" + companyId + "/detail").then(
      (data) => live && setExtra({ data }),
      (err) => live && setExtra({ error: String(err) }),
    );
    return () => {
      live = false;
    };
  }, [companyId]);

  const back = (
    <button type="button" className={GHOST} onClick={() => setPage("companies")}>
      &larr; All companies
    </button>
  );

  const { company, url, jobs, attempts, script, officers } = extra?.data ?? {};

  return (
    <main className={MAIN}>
      <div className={CARD_HEAD}>
        <h1 className={H1}>{company?.name ?? "Company"}</h1>
        {back}
      </div>

      {!companyId && <StateBox text="no company chosen -- pick one from the list" />}
      {companyId && !extra && <StateBox text="loading..." />}
      {extra?.error && <ErrorBox text={extra.error} />}

      {company && (
        <>
          <Section label="the row">
            <Facts company={company} />
            <p className={HINT}>Edit these on the Companies table.</p>
          </Section>

          {company.last_error && (
            <Section label="why the last pass produced nothing">
              <ErrorBox text={company.last_error} />
            </Section>
          )}

          {/* Which of the two url columns actually won: the directory url when
              there is one, the company home page otherwise. */}
          <Section label="where it looks">
            <Pre text={url || "no url -- fill in a directory or company url"} />
          </Section>

          <Section label={`runs (${jobs.length})`}>
            {jobs.length ? (
              <DataTable rows={jobs} columns={RUN_COLUMNS} />
            ) : (
              <StateBox text="no run yet" />
            )}
          </Section>

          <Section label={`attempts in the last run (${attempts.length})`}>
            {attempts.length ? (
              <DataTable rows={attempts} columns={ATTEMPT_COLUMNS} />
            ) : (
              <StateBox text="nothing was tried" />
            )}
          </Section>

          <Section label="saved script">
            {script ? (
              <CodeBlock code={script} />
            ) : (
              <StateBox text="no script yet -- press Generate scripts" />
            )}
          </Section>

          <Section label={`officers (${officers.length})`}>
            {officers.length ? (
              <DataTable rows={officers} columns={OFFICER_COLUMNS} />
            ) : (
              <StateBox text="none scraped yet" />
            )}
          </Section>

          <div className="mt-8">{back}</div>
        </>
      )}
    </main>
  );
}
