import { useEffect } from "react";

import { getJSON, sleep } from "../api";
import { useStore } from "../store";

const POLL_MS = 2000;
const GIVE_UP_MS = 5 * 60 * 1000;

/**
 * Poll the watched job until it settles.
 *
 * Mounted once, in App, so it keeps running while you are over on Browse. And
 * because `jobId` is one of the persisted keys, a refresh in the middle of a
 * scrape reattaches to the same job instead of losing it -- the effect just
 * starts again on the id that came back out of storage.
 */
export function useJobPoll() {
  const jobId = useStore((s) => s.jobId);

  useEffect(() => {
    if (!jobId) return; // nothing to watch

    let live = true;
    const { setJob } = useStore.getState(); // actions are stable, never a dep
    setJob(null);

    (async () => {
      const deadline = Date.now() + GIVE_UP_MS;
      while (live) {
        let next;
        try {
          next = await getJSON("/jobs/" + jobId);
        } catch (err) {
          if (live) setJob({ status: "failed", error: "lost contact with the API:\n" + err });
          return;
        }
        if (!live) return;

        setJob(next);
        if (next.status === "done" || next.status === "failed") return;

        if (Date.now() > deadline) {
          setJob({
            ...next,
            status: "failed",
            error:
              "stopped polling after 5 minutes. The job may still be running -- " +
              "check GET /jobs/" + jobId,
          });
          return;
        }
        await sleep(POLL_MS);
      }
    })();

    return () => {
      live = false; // unmounted, or the watched job changed
    };
  }, [jobId]);
}
