// One zustand store, four slices: the shell, the new-job form, the job being
// watched, and the browse tables. Components subscribe to single fields, so
// typing in the prompt box does not re-render the results table.
//
// Zustand rather than Redux Toolkit: `persist` is the refresh requirement
// solved in eight lines, and RTK plus redux-persist is roughly three times the
// bundle and a reducer file per slice for a store this size.
import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

// Explicit extensions: Vite does not need them, but bare node does, and
// tests/store.test.mjs imports this file directly.
import { del, getJSON, patchJSON, postJSON, putJSON, sleep } from "./api.js";
import { EXAMPLE, fieldsFromSchema, schemaFromFields } from "./schema.js";

export const BLANK_DRAFT = {
  name: "",
  url: "",
  script: "",
  prompt: "",
  fields: EXAMPLE,
  jsonMode: false,
  jsonText: "",
};

// Kept here, not in the tab config: the store must not import a .jsx file.
const TAB_PATHS = {
  jobs: "/jobs?limit=200",
  attempts: "/attempts?limit=200",
  scripts: "/scripts?limit=200",
  officers: "/officers?limit=200",
};

export const useStore = create(
  persist(
    (set, get) => ({
      // --- shell ------------------------------------------------------------
      page: "new",
      setPage: (page) => set({ page }),

      // Light unless the user says otherwise. main.jsx is what puts this on
      // <html> -- this file is imported by tests on bare node, where there is
      // no document to write to.
      theme: "light",
      setTheme: (theme) => set({ theme }),

      // --- the new-job form -------------------------------------------------
      draft: BLANK_DRAFT,
      // Functional form everywhere: never reads a draft captured by an older
      // render, so callbacks stay stable and there are no lost keystrokes.
      patchDraft: (patch) => set((s) => ({ draft: { ...s.draft, ...patch } })),
      resetDraft: () => set({ draft: BLANK_DRAFT, formError: null }),

      formError: null,
      setFormError: (formError) => set({ formError }),

      /** Fields <-> raw JSON. Refuses to go back to fields if it would lose data. */
      toggleJsonMode: () =>
        set((s) => {
          const { jsonMode, fields, jsonText } = s.draft;
          if (!jsonMode) {
            return {
              formError: null,
              draft: {
                ...s.draft,
                jsonMode: true,
                jsonText: JSON.stringify(schemaFromFields(fields), null, 2),
              },
            };
          }
          let parsed;
          try {
            parsed = JSON.parse(jsonText);
          } catch (err) {
            return {
              formError:
                "That is not valid JSON, so the fields cannot be filled in:\n" + err.message,
            };
          }
          const next = fieldsFromSchema(parsed);
          if (!next) {
            return {
              formError:
                "This schema has nested or unsupported types, so it can only be edited as JSON.",
            };
          }
          return { formError: null, draft: { ...s.draft, jsonMode: false, fields: next } };
        }),

      // --- the job being watched --------------------------------------------
      jobId: null,
      job: null, // server state: never persisted, refetched on load
      posting: false,

      setJob: (job) => set({ job }),
      clearJob: () => set({ jobId: null, job: null }),

      async submitJob() {
        const { draft } = get();

        let json_schema;
        try {
          json_schema = draft.jsonMode
            ? JSON.parse(draft.jsonText)
            : schemaFromFields(draft.fields);
        } catch (err) {
          return set({ formError: "JSON schema is not valid JSON:\n" + err.message });
        }
        if (!Object.keys(json_schema.properties || {}).length) {
          return set({ formError: "Add at least one field to extract." });
        }

        set({ posting: true, formError: null });
        let res;
        try {
          res = await postJSON("/jobs", {
            name: draft.name,
            url: draft.url,
            json_schema,
            prompt: draft.prompt,
            // Present: the backend runs exactly this in the sandbox and never
            // calls the model. Blank: the normal recon -> generate loop.
            script: draft.script,
          });
        } catch (err) {
          return set({ posting: false, formError: "could not reach the API:\n" + err });
        }
        // 422 detail verbatim -- swallowing it is how you get "something went wrong".
        if (!res.ok) {
          return set({ posting: false, formError: JSON.stringify(res.body, null, 2) });
        }
        set({ posting: false, jobId: res.body.job_id, job: null });
      },

      /**
       * Run a job's exact inputs again.
       *
       * There is no re-run endpoint and there should not be: POSTing the same
       * url, schema and prompt is what the reuse check already keys on, so the
       * backend replays the saved script as attempt 0 with no recon and no LLM
       * call (CLAUDE.md 2). A stale script falls through into the repair loop
       * on its own.
       *
       * It loads the form first, then submits it, so the page shows exactly
       * what is running and the inputs are there to edit for the next run.
       */
      async runAgain(job) {
        get().loadJob(job);
        await get().submitJob();
      },

      /**
       * Put a job's inputs in the form without running anything.
       *
       * With `code`, the script box is filled too, which turns the next submit
       * into a plain sandboxed run of that code: no recon, no LLM call. That
       * is the whole "edit the script and run it" path -- fix a selector by
       * hand, run it, see the rows.
       */
      loadJob({ url, prompt, json_schema, name }, code = "") {
        const fields = fieldsFromSchema(json_schema);
        const label = name ?? "";
        set({
          page: "new",
          formError: null,
          draft: fields
            ? { name: label, url, prompt, script: code, fields, jsonMode: false, jsonText: "" }
            : {
                name: label,
                url,
                prompt,
                script: code,
                fields: EXAMPLE,
                jsonMode: true,
                jsonText: JSON.stringify(json_schema, null, 2),
              },
        });
      },

      /**
       * Rename a job. The only editable thing about one: url, prompt and schema
       * are the reuse key (CLAUDE.md 2), so editing one would be a new job --
       * which is what `runAgain` loading the form already gives you.
       *
       * Returns an error string, or null. The caller renders it: a rename can
       * come from the job card or from any row of the browse table, and neither
       * error slot is the right home for the other one's failure.
       */
      async renameJob(id, name) {
        let res;
        try {
          res = await patchJSON("/jobs/" + id, { name });
        } catch (err) {
          return "could not reach the API: " + err;
        }
        if (!res.ok) return JSON.stringify(res.body);

        const saved = res.body.name;
        set((s) => ({
          job: s.job && s.job.id === id ? { ...s.job, name: saved } : s.job,
          rows: s.rows.jobs
            ? { ...s.rows, jobs: s.rows.jobs.map((r) => (r.id === id ? { ...r, name: saved } : r)) }
            : s.rows,
        }));
        return null;
      },

      // --- companies: the broker list and the two batch buttons ------------
      // The scraped officers are deliberately not here: they are a Browse tab,
      // read-only, because the next run merges over them.
      companyRows: null, // server state, never persisted
      companiesError: null,

      async loadCompanies() {
        try {
          set({ companyRows: await getJSON("/companies"), companiesError: null });
        } catch (err) {
          set({ companiesError: "could not reach the API:\n" + err });
        }
      },

      /**
       * Every write goes through here: it returns the error string for the
       * caller to render, or null, and reloads on success. Same convention as
       * `renameJob` -- a failure belongs next to the row that caused it, and
       * this store has no idea which row that is.
       */
      async _write(send, path, body) {
        let res;
        try {
          res = await send(path, body);
        } catch (err) {
          return "could not reach the API: " + err;
        }
        if (!res.ok) return JSON.stringify(res.body);
        await get().loadCompanies();
        return null;
      },

      addCompany: (row) => get()._write(postJSON, "/companies", row),
      saveCompany: (row) => get()._write(putJSON, "/companies/" + row.id, row),

      /**
       * Delete several companies, and their officers with them.
       *
       * One request each: there is no bulk endpoint and a handful of DELETEs
       * does not need one. Sequential rather than Promise.all -- 60 concurrent
       * DELETEs is 60 MySQL connections to save a second nobody is watching.
       * One reload at the end, so the table redraws once instead of N times.
       *
       * Stops at the first failure: carrying on would leave the user guessing
       * which half of their selection actually went.
       */
      async deleteCompanies(ids) {
        let problem = null;
        for (const id of ids) {
          try {
            const res = await del("/companies/" + id);
            if (!res.ok) problem = JSON.stringify(res.body);
          } catch (err) {
            problem = "could not reach the API: " + err;
          }
          if (problem) break;
        }
        // Even a partial run changed the table, so reload either way.
        await get().loadCompanies();
        return problem;
      },

      // --- the batch --------------------------------------------------------
      runProgress: { running: false },
      runPolling: false,

      /** `kind` is "scripts" (may call the model) or "run" (never does). */
      async startBatch(kind, ids = null) {
        let res;
        try {
          res = await postJSON("/companies/" + kind, { ids });
        } catch (err) {
          return "could not reach the API: " + err;
        }
        if (!res.ok) return res.body?.detail ?? JSON.stringify(res.body);
        get().pollRun();
        return null;
      },

      /**
       * Follow a batch to the end, refreshing the table as it walks.
       *
       * Also the reattach: the Companies page calls this on mount, so a run
       * started before a refresh -- or in another tab -- is picked back up.
       * The guard is what keeps a second mount from starting a second loop.
       */
      async pollRun() {
        if (get().runPolling) return;
        set({ runPolling: true });
        try {
          let wasRunning = false;
          for (;;) {
            let progress;
            try {
              progress = await getJSON("/companies/run");
            } catch (err) {
              return set({ companiesError: "could not reach the API:\n" + err });
            }
            set({ runProgress: progress });
            // Once while it runs, and once more after it stops, so the final
            // row of results is on screen without the user pressing anything.
            if (progress.running || wasRunning) await get().loadCompanies();
            if (!progress.running) return;
            wasRunning = true;
            await sleep(2000);
          }
        } finally {
          set({ runPolling: false });
        }
      },

      // --- browse -----------------------------------------------------------
      browseTab: "jobs",
      setBrowseTab: (browseTab) => set({ browseTab }),

      rows: {}, // per tab; server state, never persisted
      browseError: null,

      openRows: {},
      toggleRow: (key) =>
        set((s) => {
          const openRows = { ...s.openRows };
          if (openRows[key]) delete openRows[key];
          else openRows[key] = true;
          return { openRows };
        }),

      async loadTab(name) {
        if (get().rows[name]) return; // cached: switching tabs is not a refetch
        set({ browseError: null });
        try {
          const data = await getJSON(TAB_PATHS[name]);
          set((s) => ({ rows: { ...s.rows, [name]: data } }));
        } catch (err) {
          set({ browseError: "could not reach the API:\n" + err });
        }
      },

      refreshBrowse: () => set({ rows: {}, browseError: null }),
    }),
    {
      name: "scarper",
      // Bump this whenever BLANK_DRAFT gains a field. A draft persisted by an
      // older build has no key for it, and `undefined.trim()` is a blank page
      // on the first render -- localStorage outlives the deploy that wrote it.
      version: 2,
      migrate: (state) => ({ ...state, draft: { ...BLANK_DRAFT, ...state.draft } }),
      storage: createJSONStorage(() => localStorage),
      // Only what the user made survives a refresh. Fetched rows deliberately
      // do not -- a cache that outlives the page shows yesterday's jobs.
      // `job` is left out for the same reason: `jobId` comes back and the
      // poller refetches it, which is also how a running job is reattached.
      partialize: (s) => ({
        page: s.page,
        theme: s.theme,
        draft: s.draft,
        jobId: s.jobId,
        browseTab: s.browseTab,
        openRows: s.openRows,
      }),
    },
  ),
);

// --- derived selectors -------------------------------------------------------
// Computed at subscribe time, never stored. Both return primitives, so a
// component using them re-renders only when the answer actually changes.

/** True while a job is in flight: the submit button and dismiss both key on it. */
export const selectBusy = (s) =>
  s.posting ||
  (!!s.jobId && (!s.job || s.job.status === "pending" || s.job.status === "running"));

/**
 * Attempt 0 is a script that was not written for this job: the saved one being
 * replayed, or one supplied with the submit. Either way no model was called,
 * and it does not spend one of the three generation attempts. Say which of the
 * two actually happened.
 */
export const selectAttemptLine = (s) => {
  const job = s.job;
  if (!job || !job.attempts) return null;
  const generated = job.attempts - (job.replayed ? 1 : 0);
  if (!job.replayed) return `attempt ${job.attempts} / 3`;
  return generated
    ? `that script failed, attempt ${generated} / 3`
    : "ran an existing script, no generation";
};
