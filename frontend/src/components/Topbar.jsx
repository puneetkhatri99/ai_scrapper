import { useStore } from "../store";
import { SEG, SEG_BTN } from "../ui";

const PAGES = [
  ["new", "New job"],
  ["companies", "Companies"],
  ["browse", "Browse"],
];

// A page that is not in the nav but belongs to one that is: reading a company
// must not leave every tab unlit.
const OWNER = { company: "companies" };

const THEMES = ["light", "dark"];

// The current page is underlined in the accent, not just recoloured.
const NAV =
  "border-b-2 border-transparent py-1 text-[13px] text-dim no-underline " +
  "transition duration-120 hover:text-text " +
  "aria-[current=page]:border-accent aria-[current=page]:text-text " +
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent";

/**
 * Both options named and one pressed, rather than a button labelled with the
 * theme you are not in -- which never says whether it is describing the state
 * or the action. Same segmented control the schema editor uses.
 */
function ThemeSwitch() {
  const theme = useStore((s) => s.theme);
  const setTheme = useStore((s) => s.setTheme);

  return (
    <div className={SEG} role="group" aria-label="Theme">
      {THEMES.map((name) => (
        <button
          key={name}
          type="button"
          className={SEG_BTN}
          aria-pressed={theme === name}
          onClick={() => setTheme(name)}
        >
          {name === "light" ? "Light" : "Dark"}
        </button>
      ))}
    </div>
  );
}

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
    <header className="flex min-h-14 flex-wrap items-center gap-x-4 gap-y-2 border-b border-border bg-surface px-4 py-2 sm:gap-x-6">
      <a
        className="font-mono text-sm font-semibold tracking-[-.02em] text-text no-underline"
        href="#"
        onClick={go("new")}
      >
        scarper
      </a>
      <nav className="flex flex-wrap gap-4">
        {PAGES.map(([name, label]) => (
          <a
            key={name}
            className={NAV}
            href="#"
            onClick={go(name)}
            aria-current={(OWNER[page] ?? page) === name ? "page" : undefined}
          >
            {label}
          </a>
        ))}
      </nav>
      <div className="ml-auto">
        <ThemeSwitch />
      </div>
    </header>
  );
}
