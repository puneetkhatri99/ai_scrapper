import { useEffect } from "react";

import { BrowseTable } from "../components/BrowseTable";
import { ErrorBox, StateBox } from "../components/primitives";
import { useStore } from "../store";
import { CARD_HEAD, GHOST, H1, MAIN } from "../ui";
import { TABS } from "./browseTabs";

// A tab is not a link: same border box either way, the selected one filled
// in the accent so the strip reads as one control.
const TAB =
  "cursor-pointer rounded-md border border-border bg-transparent px-4 py-2 " +
  "font-ui text-[13px] font-semibold text-dim transition duration-120 " +
  "aria-[selected=false]:hover:bg-surface-2 aria-[selected=false]:hover:text-text " +
  "aria-selected:border-accent aria-selected:bg-accent/14 aria-selected:text-text " +
  "focus-visible:outline-none focus-visible:border-accent focus-visible:ring-3 focus-visible:ring-accent/25";

/** The tab strip. Its own component so a table reload does not re-render it. */
function Tabs() {
  const browseTab = useStore((s) => s.browseTab);
  const setBrowseTab = useStore((s) => s.setBrowseTab);
  const rows = useStore((s) => s.rows);

  return (
    <div className="mb-6 flex flex-wrap gap-1" role="tablist" aria-label="Tables">
      {TABS.map((t) => (
        <button
          key={t.name}
          className={TAB}
          role="tab"
          id={"tab-" + t.name}
          aria-selected={String(t.name === browseTab)}
          aria-controls="panel"
          onClick={() => setBrowseTab(t.name)}
        >
          {t.label}{" "}
          <span className="font-mono font-normal text-mute">{rows[t.name]?.length ?? ""}</span>
        </button>
      ))}
    </div>
  );
}

/** Read-only: this page never POSTs and never deletes. */
export function Browse() {
  const browseTab = useStore((s) => s.browseTab);
  const rows = useStore((s) => s.rows[browseTab]);
  const browseError = useStore((s) => s.browseError);
  const loadTab = useStore((s) => s.loadTab);
  const refreshBrowse = useStore((s) => s.refreshBrowse);

  // loadTab is a no-op when the tab is already cached, so this fires on the
  // first visit and after Refresh drops the cache, and never in between.
  useEffect(() => {
    loadTab(browseTab);
  }, [browseTab, rows, loadTab]);

  const spec = TABS.find((t) => t.name === browseTab);

  return (
    <main className={MAIN}>
      <div className={CARD_HEAD}>
        <h1 className={H1}>Browse</h1>
        <button type="button" className={GHOST} onClick={refreshBrowse}>
          Refresh
        </button>
      </div>

      <Tabs />

      <div id="panel" role="tabpanel" aria-labelledby={"tab-" + browseTab}>
        {browseError && <ErrorBox text={browseError} />}
        {!browseError && !rows && <StateBox text="loading..." />}
        {rows?.length === 0 && <StateBox text={spec.empty} />}
        {rows?.length > 0 && (
          <BrowseTable
            rows={rows}
            tab={browseTab}
            columns={spec.columns}
            Detail={spec.Detail}
          />
        )}
      </div>
    </main>
  );
}
