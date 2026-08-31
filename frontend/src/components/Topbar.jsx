import { useStore } from "../store";

const PAGES = [
  ["new", "New job"],
  ["browse", "Browse"],
];

/**
 * Two views, switched through the store rather than a router. `page` is one of
 * the persisted keys, so a refresh puts you back where you were. Swap in
 * react-router the day these views need shareable URLs -- nothing else here
 * depends on how the switch is made.
 */
export function Topbar() {
  const page = useStore((s) => s.page);
  const setPage = useStore((s) => s.setPage);

  const go = (name) => (e) => {
    e.preventDefault();
    setPage(name);
  };

  return (
    <header className="topbar">
      <a className="brand" href="#" onClick={go("new")}>
        scarper
      </a>
      <nav>
        {PAGES.map(([name, label]) => (
          <a
            key={name}
            href="#"
            onClick={go(name)}
            aria-current={page === name ? "page" : undefined}
          >
            {label}
          </a>
        ))}
      </nav>
    </header>
  );
}
