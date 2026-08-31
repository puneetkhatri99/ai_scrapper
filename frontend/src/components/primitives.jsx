// The small shared pieces every page uses. All presentational: no store, no
// fetching. Class names are the ones design.md already defines in style.css.

/** Never colour alone (design.md 7): a dot and the word. */
export function StatusPill({ status }) {
  return (
    <span className="status" data-status={status}>
      <span className="dot" />
      <span>{status}</span>
    </span>
  );
}

export function Section({ label, children }) {
  return (
    <div className="section">
      <span className="label">{label}</span>
      {children}
    </div>
  );
}

export const StateBox = ({ text }) => <p className="state">{text}</p>;

/** Verbatim, always -- never "something went wrong" (rules.md G28). */
export const ErrorBox = ({ text }) => <p className="error">{text}</p>;

export const Pre = ({ text }) => <pre>{text}</pre>;

export const Scroll = ({ children }) => <div className="scroll">{children}</div>;
