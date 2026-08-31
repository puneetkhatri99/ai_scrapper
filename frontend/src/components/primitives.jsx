// The small shared pieces every page uses. All presentational: no store, no
// fetching. The class strings are the ones ui.js defines from design.md.

import { ERROR, LABEL, PRE, SCROLL, SECTION, STATE } from "../ui";

// A status is a colour and a word, never a colour alone (design.md 7). The
// running dot is the one animation in the app: it says work is happening.
const DOT = {
  pending: "bg-pending",
  running: "bg-running animate-blip",
  done: "bg-done",
  failed: "bg-failed",
};

export function StatusPill({ status }) {
  return (
    <span className="inline-flex items-center gap-2 text-xs font-semibold">
      <span className={`size-2 shrink-0 rounded-full ${DOT[status] ?? DOT.pending}`} />
      <span>{status}</span>
    </span>
  );
}

export function Section({ label, children }) {
  return (
    <div className={SECTION}>
      <span className={LABEL + " mb-3 block"}>{label}</span>
      {children}
    </div>
  );
}

export const StateBox = ({ text }) => <p className={STATE}>{text}</p>;

/** Verbatim, always -- never "something went wrong" (rules.md G28). */
export const ErrorBox = ({ text }) => <p className={ERROR}>{text}</p>;

export const Pre = ({ text }) => <pre className={PRE}>{text}</pre>;

export const Scroll = ({ children }) => <div className={SCROLL}>{children}</div>;
