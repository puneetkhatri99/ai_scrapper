import { useEffect, useRef, useState } from "react";

import { GHOST, PRE } from "../ui";

/** A <pre> of code with a copy button over it. */
export function CodeBlock({ code }) {
  const [label, setLabel] = useState("copy");
  const timer = useRef(null);

  // Clearing on unmount keeps a "copied" timer from firing into a component
  // that is no longer on the page -- easy to hit here, since a row can be
  // collapsed a second after its copy button is pressed.
  useEffect(() => () => clearTimeout(timer.current), []);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setLabel("copied");
    } catch {
      setLabel("copy failed"); // insecure context, or the user said no
    }
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setLabel("copy"), 1500);
  };

  return (
    <div className="relative">
      <pre className={PRE}>
        <code>{code}</code>
      </pre>
      <button type="button" className={GHOST + " absolute top-2 right-2"} onClick={copy}>
        {label}
      </button>
    </div>
  );
}
