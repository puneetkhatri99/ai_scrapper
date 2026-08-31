import { short } from "../api";
import { selectAttemptLine, selectBusy, useStore } from "../store";
import { CodeBlock } from "./CodeBlock";
import { DataTable } from "./DataTable";
import { ErrorBox, Scroll, Section, StatusPill } from "./primitives";

/** The watched job: status, which attempt, and whatever it has produced so far. */
export function JobCard() {
  const jobId = useStore((s) => s.jobId);
  const job = useStore((s) => s.job);
  const busy = useStore(selectBusy);
  const attempt = useStore(selectAttemptLine);
  const clearJob = useStore((s) => s.clearJob);
  const setPage = useStore((s) => s.setPage);
  const setBrowseTab = useStore((s) => s.setBrowseTab);

  if (!jobId) return null;

  const status = job?.status ?? "pending";
  const rows = job?.result?.length ? job.result : null;

  const seeAttempts = () => {
    setBrowseTab("attempts");
    setPage("browse");
  };

  return (
    <section className="card">
      <div className="card-head">
        <span className="label">
          job <span className="job-ref">{short(jobId)}</span>
        </span>
        <span>
          <StatusPill status={status} />
          {/* Persisted state needs an off switch, or the card never leaves. */}
          {!busy && (
            <button type="button" className="ghost" onClick={clearJob}>
              dismiss
            </button>
          )}
        </span>
      </div>

      {attempt && <p className="attempt">{attempt}</p>}

      {rows && (
        <Section label="result">
          <Scroll>
            <DataTable rows={rows} />
          </Scroll>
        </Section>
      )}

      {job?.script && (
        <Section label="script">
          <CodeBlock code={job.script} />
        </Section>
      )}

      {status === "failed" && job?.error && (
        <Section label="error">
          <ErrorBox text={job.error} />
          <button type="button" className="ghost attempts-link" onClick={seeAttempts}>
            view every attempt →
          </button>
        </Section>
      )}
    </section>
  );
}
