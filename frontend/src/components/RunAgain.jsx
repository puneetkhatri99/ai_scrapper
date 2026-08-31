import { selectBusy, useStore } from "../store";
import { GHOST } from "../ui";

/**
 * Run these inputs again. Takes anything carrying the three job inputs: the
 * polled job, a Jobs row, a saved-script row.
 *
 * Disabled while a job is in flight, for the same reason the submit button is:
 * one job at a time is a real constraint, so the UI states it honestly.
 */
export function RunAgain({ job, label = "Run again" }) {
  const busy = useStore(selectBusy);
  const runAgain = useStore((s) => s.runAgain);

  return (
    <button
      type="button"
      className={GHOST}
      disabled={busy}
      title="Runs the saved script again. No LLM call unless the script has gone stale."
      onClick={() => runAgain(job)}
    >
      {label}
    </button>
  );
}

/**
 * Put this script in the form's script box, without running it. Submitting
 * then executes exactly that code in the sandbox -- no recon, no LLM call --
 * so a selector can be fixed by hand and tried out.
 *
 * Not disabled while a job runs: this only fills the form in.
 */
export function RunScript({ job, code, label = "Edit & run" }) {
  const loadJob = useStore((s) => s.loadJob);

  return (
    <button
      type="button"
      className={GHOST}
      title="Opens this script in the form. Running it executes exactly this code in the sandbox."
      onClick={() => loadJob(job, code)}
    >
      {label}
    </button>
  );
}
