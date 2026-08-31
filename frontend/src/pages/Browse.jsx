import { useEffect } from "react";

import { BrowseTable } from "../components/BrowseTable";
import { ErrorBox, Scroll, StateBox } from "../components/primitives";
import { useStore } from "../store";
import { TABS } from "./browseTabs";

/** The tab strip. Its own component so a table reload does not re-render it. */
function Tabs() {
  const browseTab = useStore((s) => s.browseTab);
  const setBrowseTab = useStore((s) => s.setBrowseTab);
  const rows = useStore((s) => s.rows);

  return (
    <div className="tabs" role="tablist" aria-label="Tables">
      {TABS.map((t) => (
        <button
          key={t.name}
          role="tab"
          id={"tab-" + t.name}
          aria-selected={String(t.name === browseTab)}
          aria-controls="panel"
          onClick={() => setBrowseTab(t.name)}
        >
          {t.label} <span className="count">{rows[t.name]?.length ?? ""}</span>
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
    <main>
      <div className="card-head">
        <h1 style={{ margin: 0 }}>Browse</h1>
        <button type="button" className="ghost" onClick={refreshBrowse}>
          Refresh
        </button>
      </div>

      <Tabs />

      <div id="panel" role="tabpanel" aria-labelledby={"tab-" + browseTab}>
        {browseError && <ErrorBox text={browseError} />}
        {!browseError && !rows && <StateBox text="loading..." />}
        {rows?.length === 0 && <StateBox text={spec.empty} />}
        {rows?.length > 0 && (
          <Scroll>
            <BrowseTable
              rows={rows}
              tab={browseTab}
              columns={spec.columns}
              Detail={spec.Detail}
            />
          </Scroll>
        )}
      </div>
    </main>
  );
}
