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
import { getJSON, postJSON } from "./api.js";
import { EXAMPLE, fieldsFromSchema, schemaFromFields } from "./schema.js";

export const BLANK_DRAFT = {
  url: "",
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
};

export const useStore = create(
  persist(
    (set, get) => ({
      // --- shell ------------------------------------------------------------
      page: "new",
      setPage: (page) => set({ page }),

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
            url: draft.url,
            json_schema,
            prompt: draft.prompt,
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
      version: 1,
      storage: createJSONStorage(() => localStorage),
      // Only what the user made survives a refresh. Fetched rows deliberately
      // do not -- a cache that outlives the page shows yesterday's jobs.
      // `job` is left out for the same reason: `jobId` comes back and the
      // poller refetches it, which is also how a running job is reattached.
      partialize: (s) => ({
        page: s.page,
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
 * A replay is attempt 0: counted, but it does not spend one of the three
 * generation attempts. Say which of the two actually happened.
 */
export const selectAttemptLine = (s) => {
  const job = s.job;
  if (!job || !job.attempts) return null;
  const generated = job.attempts - (job.replayed ? 1 : 0);
  if (!job.replayed) return `attempt ${job.attempts} / 3`;
  return generated ? `saved script was stale, attempt ${generated} / 3` : "replayed a saved script";
};
