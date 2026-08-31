import { useEffect, useState } from "react";

import { useStore } from "../store";
import { ISSUE, NAME_INPUT } from "../ui";

/**
 * A job's name, edited in place. There is no edit mode and no save button --
 * the field is the display. Blur or Enter saves, Escape puts back what was
 * there. The id is not the placeholder: it is already the column to the left,
 * and in the card head it is already the line this sits on.
 *
 * Takes any row carrying `id` and `name`: the polled job, or a Jobs row.
 * `className` is where it sits: a table cell wants the column's width, the
 * card head a fixed one, so the width is not baked into NAME_INPUT.
 */
export function JobName({ job, id = job.id, className = "w-full min-w-[140px] max-w-[200px]" }) {
  const renameJob = useStore((s) => s.renameJob);
  const saved = job.name ?? "";
  const [text, setText] = useState(saved);
  const [error, setError] = useState(null);

  // The poller hands back a new `job` object every two seconds. Re-sync only
  // when the stored name actually changed, so it never lands mid-keystroke.
  useEffect(() => setText(saved), [saved]);

  const save = async () => {
    if (text.trim() === saved) return; // nothing typed, or Escape put it back
    setError(await renameJob(id, text));
  };

  return (
    <>
      <input
        className={NAME_INPUT + " " + className}
        aria-label="Job name"
        aria-invalid={error ? "true" : undefined}
        maxLength={120}
        autoComplete="off"
        placeholder="unnamed"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={save}
        // A browse row toggles on click and on Enter/Space. Typing a name is
        // not a request to expand the row it sits in.
        onClick={(e) => e.stopPropagation()}
        onKeyDown={(e) => {
          e.stopPropagation();
          if (e.key === "Enter") e.currentTarget.blur();
          // Reverting the text is the whole of cancel: the blur that follows
          // finds nothing changed and never calls the API.
          if (e.key === "Escape") setText(saved);
        }}
      />
      {error && (
        <span className={ISSUE} role="alert">
          {error}
        </span>
      )}
    </>
  );
}
