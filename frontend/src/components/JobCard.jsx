import { short } from "../api";
import { selectAttemptLine, selectBusy, useStore } from "../store";
import { CodeBlock } from "./CodeBlock";
import { DataTable } from "./DataTable";
import { ErrorBox, Scroll, Section, StatusPill } from "./primitives";
import { JobName } from "./JobName";
import { RunAgain, RunScript } from "./RunAgain";
import { CARD, CARD_HEAD, GHOST, HEAD_ACTIONS, LABEL } from "../ui";

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
    <section className={CARD}>
      <div className={CARD_HEAD}>
        <span className="inline-flex min-w-0 items-center gap-3">
          <span className={LABEL}>
            job{" "}
            <span className="font-mono normal-case tracking-normal text-dim">
              {short(jobId)}
            </span>
          </span>
          {/* The id is the identity and stays; the name is the label. */}
          <JobName job={job ?? {}} id={jobId} className="w-[180px]" />
        </span>
        <span className={HEAD_ACTIONS}>
          <StatusPill status={status} />
          {/* GET /jobs/{id} echoes the three inputs back, so this works even
              after a refresh, when the form no longer holds them. */}
          {!busy && job?.script && <RunScript job={job} code={job.script} />}
          {!busy && job && <RunAgain job={job} />}
          {/* Persisted state needs an off switch, or the card never leaves. */}
          {!busy && (
            <button type="button" className={GHOST} onClick={clearJob}>
              dismiss
            </button>
          )}
        </span>
      </div>

      {attempt && <p className="font-mono text-xs text-mute">{attempt}</p>}

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
          <button type="button" className={GHOST + " mt-3"} onClick={seeAttempts}>
            view every attempt →
          </button>
        </Section>
      )}
    </section>
  );
}
