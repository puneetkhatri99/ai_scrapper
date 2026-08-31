# design.md

Visual system for the frontend. One page, one job: type three things, watch a
job run, read the result. The UI is a **tool**, not a landing page — no hero,
no marketing copy, no illustrations.

Reference feel: Linear / Vercel dashboard / a good CI log viewer. Dense,
monospaced where it matters, calm while waiting, loud when it fails.

---

## 1. Theme

Light by default, dark on request. The switch sits in the topbar, writes
`data-theme` on `<html>`, and the choice is persisted -- so it is a decision
made once, not a preference re-guessed on every load.

No `prefers-color-scheme` branch. The switch is already the answer to "give me
the other one", and an OS-driven default would silently fight a user who had
picked the theme the OS disagrees with.

In light, cards are white and the page behind them is not -- that greyish
ground is what gives a card an edge without a drop shadow. In dark the same
relationship holds, inverted.

## 2. Tokens

Define once, in `@theme` in `style.css`. Nothing else names a colour: the
`--color-*` prefix is what makes Tailwind mint a utility per token, so
`--color-surface` *is* `bg-surface` / `text-surface` / `border-surface`, and a
component that wants the card colour asks for it by name, not by hex.

```css
@theme {
  /* surface */
  --color-bg:        #f6f7f9;   /* page */
  --color-surface:   #ffffff;   /* cards, the builder panel */
  --color-surface-2: #f4f6f9;   /* inputs, code blocks, zebra rows */
  --color-border:    #e2e6ec;
  --color-border-hi: #c8cfd8;

  /* text — every one clears 4.5:1 on both surface and surface-2 */
  --color-text: #101418;
  --color-dim:  #4b5563;
  --color-mute: #656e7d;

  /* state — status is the whole UI, so these carry real weight. Darker than a
     dark theme's set: green-500 on white is 1.9:1, below even the 3:1 floor
     for a non-text indicator. */
  --color-pending: #6b7280;   /* grey   */
  --color-running: #2563eb;   /* blue   */
  --color-done:    #15803d;   /* green  */
  --color-failed:  #b91c1c;   /* red    */
  --color-accent:    #4f46e5; /* indigo — buttons, focus rings */
  --color-accent-hi: #4338ca; /* hover: darker on light, never lighter */

  /* type */
  --font-ui:   ui-sans-serif, -apple-system, "Inter", system-ui, sans-serif;
  --font-mono: ui-monospace, "JetBrains Mono", "SF Mono", Menlo, monospace;

  /* Tailwind's own 4px scale is the spacing scale: p-1 p-2 p-3 p-4 p-6 p-8
     p-12 are the 4/8/12/16/24/32/48 this used to spell out. */

  /* one radius system: rounded-md (6px) for controls, rounded-lg for
     containers. Nothing else -- lg is retuned from Tailwind's 8px. */
  --radius-lg: 0.625rem;
}
```

Dark overrides only what actually differs. It is a plain rule, not `@theme`,
and not Tailwind's `dark:` variant: the values swap underneath the utilities,
so no component carries two class names for two themes.

```css
:root[data-theme="dark"] {
  --color-bg:        #0b0d10;
  --color-surface:   #14171c;
  --color-surface-2: #1c2027;
  --color-border:    #262b33;
  --color-border-hi: #343b45;

  --color-text: #e6e9ee;
  --color-dim:  #9aa3af;
  --color-mute: #838c9b;  /* the old #626b78 is 3.6:1 on the page, under 7's floor */

  --color-pending: #9aa3af;
  --color-running: #3b82f6;
  --color-done:    #22c55e;
  --color-failed:  #f87171;  /* red-500 is 4.3:1 on surface-2, red-400 is 5.9 */

  color-scheme: dark;
}
```

The accent is deliberately not in that list: `#4f46e5` carries white text at
4.84:1 and reads on both grounds, so one indigo is one fewer thing to keep in
sync. A state colour is not reused across themes without checking it -- the
green that passes on `#0b0d10` is 1.9:1 on white.

A repeated control -- a text field, a ghost button, a `th` -- names its
utilities once in `src/ui.js` and every call site imports that string. That
file is what the element selectors in the old stylesheet turned into; it is
plain text, so the Tailwind scanner still sees every class in it.

## 3. Typography

| Role | Font | Size | Weight |
|---|---|---|---|
| Page title | ui | 20px | 600 |
| Section label | ui | 12px, `letter-spacing: .06em`, uppercase | 600, `--color-mute` |
| Body / labels | ui | 14px | 400 |
| Input text | **mono** | 13px | 400 |
| JSON schema / prompt / generated script | **mono** | 13px, `line-height: 1.6` | 400 |
| Status badge | ui | 12px | 600 |

Rule: **anything the user types that is code or data is monospaced.** The URL
field, the JSON schema textarea, the extracted results, and the generated
script are all mono. Only chrome and labels are sans.

## 4. Layout

Single column, `max-w-[860px]`, centered, `pt-8 px-4 pb-12`.
Two stacked cards:

```
┌─ new job ──────────────────────────────┐
│ URL          [ https://…            ]  │
│ JSON schema  [ mono textarea, 10 rows]  │
│ Prompt       [ mono textarea, 4 rows ]  │
│                        [ Run scrape ]  │
└────────────────────────────────────────┘

┌─ job a1b2c3 ─────────────── ● running ─┐
│ attempt 2 / 3                          │
│ ─ result ──────────────────────────    │
│ [ table of extracted rows ]            │
│ ─ script ──────────────────────────    │
│ [ mono code block, copy button ]       │
└────────────────────────────────────────┘
```

The job card does not exist until a job is submitted. No empty state
placeholder, no skeleton illustration.

## 5. Status is the primary signal

A single dot + word, top-right of the job card. This is the one thing the user
stares at.

| Status | Dot | Label | Extra |
|---|---|---|---|
| `pending` | `--color-pending`, static | pending | — |
| `running` | `--color-running`, 1.6s pulse | running | `attempt N / 3` beneath |
| `done` | `--color-done`, static | done | result table appears |
| `failed` | `--color-failed`, static | failed | error block, mono, `--color-failed` left border |

```css
@keyframes pulse { 0%,100% { opacity: 1 } 50% { opacity: .35 } }
```

That pulse is the only animation in the app. Everything else is a
`transition: 120ms ease` on hover/focus. No page transitions, no scroll
effects, no toast stack.

## 6. Components

**Input / textarea** — `--color-surface-2` fill, `border border-border`,
`rounded-md`. Focus: `focus:border-accent focus:ring-3 focus:ring-accent/25`.
Never remove the focus ring.

**Button** — `--color-accent` fill, white text, `rounded-md`, `padding: 10px 18px`.
Disabled while a job runs (`opacity: .5; cursor: not-allowed`) — one job at a
time is a real constraint (`CLAUDE.md` §9), so the UI states it honestly.

**Code block** — `--color-surface-2`, `rounded-lg`, `border border-border`,
`overflow-x-auto`, `p-4`. Copy button top-right, ghost style,
becomes "copied" for 1.5s. No syntax highlighting library in v1.

**Schema builder** — the fields editor is the one dense control here, so it
carries more than a row of inputs: a `Fields | JSON` segmented pair (both modes
named, rather than one button that hides what the other side is), starter
presets offered only while nothing has been typed, a duplicate-name message
under the row that caused it, a running `N fields, M required` count, and a
native `<details>` "Schema preview" holding the JSON that will actually be
posted. Enter inside a field name inserts the next row rather than submitting
the form. Panel is `--color-surface`, inputs stay `--color-surface-2`, so a row reads as a
row.

**Theme switch** — the same segmented pair as the schema editor, top right of
the topbar: `Light | Dark`, both named, the current one `aria-pressed`. A
single button labelled with one theme never says whether it is describing the
state or the action. `main.jsx` owns the `<html>` attribute and applies it
before the first paint, so a reload into dark does not flash light.

**Run again** — a ghost button wherever a job's three inputs are on screen: the
job card, and both Browse detail panels. It posts the same url, schema and
prompt, which is exactly what the reuse check keys on, so the saved script
replays as attempt 0. Disabled while a job is in flight, like the submit
button.

**Result table** — full width, `border-collapse: collapse`, header row
`--color-mute` uppercase 12px, cells mono 13px, `border border-border` row
separators, zebra via `--color-surface-2` on even rows. Wrap in
`overflow-x-auto` — extracted data is arbitrary width.

**Error block** — mono 13px, `--color-failed` 3px left border, `--color-surface-2` fill.
Show the traceback **verbatim**. This is a developer tool; the raw error is the
most useful thing on the page. Never replace it with "Something went wrong".

## 7. Non-negotiables

- Focus rings stay visible on every interactive element.
- Contrast ≥ 4.5:1 for text against its surface, **in both themes**.
  `--color-mute` on `--color-surface-2` is the floor — check that one, it is tighter
  than `--color-bg`.
- Status is never conveyed by color alone: dot **and** word, always.
- Labels are real `<label for>`, textareas are resizable.
- The page works with JS for polling only. No framework required; if React is
  used, it is one component file, no router, no state library.

## 8. Explicitly not doing

Gradients, glassmorphism, drop shadows beyond a hairline border, icon library,
a third theme, animated logos, empty-state
illustrations, toast notifications, syntax highlighting. Every one of these is
weight added to a form and a status line.
