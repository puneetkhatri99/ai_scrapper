// The one thing on the page that is not the app: a way out to the manual.
// A plain <a>, not a store page -- the docs are a static file the backend
// serves beside the bundle, so there is nothing here for React to render.

/**
 * `/docs.html` is `frontend/public/docs.html`, copied verbatim into the bundle
 * by Vite. That means it works in `npm run dev` and in the built bundle
 * main.py mounts, with no route on either side.
 *
 * The `.html` is not untidiness: FastAPI already owns `/docs`, which is its
 * Swagger UI. Shortening this link would quietly point it at the API explorer.
 *
 * A new tab, because the manual is something you read *while* working: a job
 * mid-run keeps polling in the tab you left, and the form keeps whatever you
 * had typed.
 *
 * Baseline-aligned rather than boxed: it is a sign-off, not a section, and a
 * card would give it more weight than a link deserves.
 */
export function Footer() {
  return (
    <footer className="mx-auto mt-12 flex max-w-[1180px] flex-wrap items-baseline gap-4 border-t border-border px-6 pt-6 pb-8 text-[13px]">
      <span className="font-mono text-dim">scarper</span>
      {/* mr-auto pushes the link to the far edge, and collapses to a line
          break on narrow screens instead of squeezing it off the end. */}
      <span className="mr-auto text-mute">
        describe the data you want, get a working scraper
      </span>
      <a
        className="group inline-flex items-center gap-2 border-b border-border-hi pb-0.5 text-dim no-underline transition duration-120 hover:border-accent hover:text-text"
        href="/docs.html"
        target="_blank"
        rel="noreferrer"
      >
        Read the docs
        <svg
          className="opacity-70 group-hover:opacity-100"
          width="11"
          height="11"
          viewBox="0 0 12 12"
          aria-hidden="true"
          focusable="false"
        >
          <path
            d="M4.5 1.5h6v6M10.5 1.5L5 7M9 7.5v3h-7.5V3h3"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.3"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </a>
    </footer>
  );
}
