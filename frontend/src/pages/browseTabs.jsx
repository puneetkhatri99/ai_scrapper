import { short, when } from "../api";
import { AttemptDetail, JobDetail, OfficerDetail, ScriptDetail } from "../components/details";
import { JobName } from "../components/JobName";
import { StatusPill } from "../components/primitives";
import { NUM, W } from "../ui";

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
      { key: "id", label: "Job", class: W.id, render: (r) => short(r.id) },
      // Editable in place -- the cell is the rename control.
      { key: "name", label: "Name", class: W.name, render: (r) => <JobName job={r} /> },
      { key: "url", label: "URL", class: "truncate" },
      { key: "status", label: "Status", class: W.status,
        render: (r) => <StatusPill status={r.status} /> },
      { key: "prompt", label: "Prompt", class: "truncate" },
      { key: "attempts", label: "Attempts", class: W.num + " " + NUM },
      { key: "created_at", label: "Created", class: W.when, render: (r) => when(r.created_at) },
    ],
    Detail: JobDetail,
  },
  {
    name: "attempts",
    label: "Attempts",
    empty: "No attempts yet.",
    columns: [
      { key: "job_id", label: "Job", class: W.id, render: (r) => short(r.job_id) },
      { key: "url", label: "URL", class: "truncate" },
      {
        key: "attempt_number",
        label: "Attempt",
        class: W.tag,
        // 0 is not a real attempt: it is the saved script being replayed.
        render: (r) => (r.attempt_number === 0 ? "replay" : String(r.attempt_number)),
      },
      { key: "success", label: "Result", class: W.tag,
        render: (r) => (r.success ? "ok" : "failed") },
      { key: "error_message", label: "Error", class: "truncate" },
      { key: "created_at", label: "Created", class: W.when, render: (r) => when(r.created_at) },
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
      { key: "url", label: "URL", class: "truncate" },
      { key: "prompt", label: "Prompt", class: "truncate" },
      { key: "reuse_count", label: "Times reused", class: W.num + " " + NUM },
      { key: "created_at", label: "Saved", class: W.when, render: (r) => when(r.created_at) },
    ],
    Detail: ScriptDetail,
  },
  {
    name: "officers",
    label: "Loan officers",
    empty:
      "No loan officers yet. Add companies on the Companies page, generate a script " +
      "for each, then Run all.",
    columns: [
      { key: "company", label: "Company", class: W.name },
      { key: "name", label: "Name", class: W.name },
      { key: "nmls_id", label: "NMLS #", class: W.tag },
      { key: "email", label: "Email", class: "truncate" },
      { key: "phone", label: "Phone", class: W.tag },
      { key: "position", label: "Position", class: "truncate" },
      { key: "address", label: "Address", class: "truncate" },
      // The pair the sheet used to track by hand: first sighting, and the last
      // time this person's details actually changed.
      { key: "fetched_at", label: "Fetched", class: W.when, render: (r) => when(r.fetched_at) },
      { key: "updated_at", label: "Updated", class: W.when, render: (r) => when(r.updated_at) },
    ],
    Detail: OfficerDetail,
  },
];
