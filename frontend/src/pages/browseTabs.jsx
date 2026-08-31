import { short, when } from "../api";
import { AttemptDetail, JobDetail, ScriptDetail } from "../components/details";
import { StatusPill } from "../components/primitives";

// Each tab is a column set and what its expanded row shows. Module-level and
// frozen in shape, so `columns` keeps one identity for the life of the page --
// which is what lets the memoised rows in BrowseTable actually skip work.
// The paths themselves live in store.js, which fetches them.
export const TABS = [
  {
    name: "jobs",
    label: "Jobs",
    empty: "No jobs yet. Run one from the New job page.",
    columns: [
      { key: "id", label: "Job", render: (r) => short(r.id) },
      { key: "url", label: "URL", class: "clip" },
      { key: "status", label: "Status", render: (r) => <StatusPill status={r.status} /> },
      { key: "prompt", label: "Prompt", class: "clip" },
      { key: "attempts", label: "Attempts", class: "num" },
      { key: "created_at", label: "Created", render: (r) => when(r.created_at) },
    ],
    Detail: JobDetail,
  },
  {
    name: "attempts",
    label: "Attempts",
    empty: "No attempts yet.",
    columns: [
      { key: "job_id", label: "Job", render: (r) => short(r.job_id) },
      { key: "url", label: "URL", class: "clip" },
      {
        key: "attempt_number",
        label: "Attempt",
        // 0 is not a real attempt: it is the saved script being replayed.
        render: (r) => (r.attempt_number === 0 ? "replay" : String(r.attempt_number)),
      },
      { key: "success", label: "Result", render: (r) => (r.success ? "ok" : "failed") },
      { key: "error_message", label: "Error", class: "clip" },
      { key: "created_at", label: "Created", render: (r) => when(r.created_at) },
    ],
    Detail: AttemptDetail,
  },
  {
    name: "scripts",
    label: "Saved scripts",
    empty:
      "No saved scripts yet. A script is saved the first time a job succeeds, and reused " +
      "when the same URL, prompt and fields are submitted again.",
    columns: [
      { key: "url", label: "URL", class: "clip" },
      { key: "prompt", label: "Prompt", class: "clip" },
      { key: "reuse_count", label: "Times reused", class: "num" },
      { key: "created_at", label: "Saved", render: (r) => when(r.created_at) },
    ],
    Detail: ScriptDetail,
  },
];
