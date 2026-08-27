# design.md

Visual system for the frontend. One page, one job: type three things, watch a
job run, read the result. The UI is a **tool**, not a landing page — no hero,
no marketing copy, no illustrations.

Reference feel: Linear / Vercel dashboard / a good CI log viewer. Dense,
monospaced where it matters, calm while waiting, loud when it fails.

---

## 1. Theme

Dark-first. This is a developer tool that sits open next to a terminal.

## 2. Tokens

Define once at `:root`. Nothing else in the CSS hardcodes a color.

```css
:root {
  /* surface */
  --bg:        #0b0d10;   /* page */
  --surface:   #14171c;   /* cards, form */
  --surface-2: #1c2027;   /* inputs, code blocks */
  --border:    #262b33;
  --border-hi: #343b45;

  /* text */
  --text:      #e6e9ee;
  --text-dim:  #9aa3af;
  --text-mute: #626b78;

  /* state — status is the whole UI, so these carry real weight */
  --pending:   #9aa3af;   /* grey  */
  --running:   #3b82f6;   /* blue  */
  --done:      #22c55e;   /* green */
  --failed:    #ef4444;   /* red   */
  --accent:    #6366f1;   /* indigo — buttons, focus rings */

  /* type */
  --font-ui:   ui-sans-serif, -apple-system, "Inter", system-ui, sans-serif;
  --font-mono: ui-monospace, "JetBrains Mono", "SF Mono", Menlo, monospace;

  /* scale — 4px base, no arbitrary values */
  --s1: 4px; --s2: 8px; --s3: 12px; --s4: 16px;
  --s5: 24px; --s6: 32px; --s7: 48px;

  --radius: 6px;
  --radius-lg: 10px;
}
```

Light mode: flip `--bg`/`--surface`/`--text` under
`@media (prefers-color-scheme: light)`. Keep the four state colors — they read
fine on both.

## 3. Typography

| Role | Font | Size | Weight |
|---|---|---|---|
| Page title | ui | 20px | 600 |
| Section label | ui | 12px, `letter-spacing: .06em`, uppercase | 600, `--text-mute` |
| Body / labels | ui | 14px | 400 |
| Input text | **mono** | 13px | 400 |
| JSON schema / prompt / generated script | **mono** | 13px, `line-height: 1.6` | 400 |
| Status badge | ui | 12px | 600 |

Rule: **anything the user types that is code or data is monospaced.** The URL
field, the JSON schema textarea, the extracted results, and the generated
script are all mono. Only chrome and labels are sans.

## 4. Layout

Single column, `max-width: 860px`, centered, `padding: var(--s6) var(--s4)`.
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
| `pending` | `--pending`, static | pending | — |
| `running` | `--running`, 1.6s pulse | running | `attempt N / 3` beneath |
| `done` | `--done`, static | done | result table appears |
| `failed` | `--failed`, static | failed | error block, mono, `--failed` left border |

```css
@keyframes pulse { 0%,100% { opacity: 1 } 50% { opacity: .35 } }
```

That pulse is the only animation in the app. Everything else is a
`transition: 120ms ease` on hover/focus. No page transitions, no scroll
effects, no toast stack.

## 6. Components

**Input / textarea** — `--surface-2` fill, `1px solid var(--border)`,
`--radius`. Focus: `border-color: var(--accent)` plus
`box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 25%, transparent)`.
Never remove the focus ring.

**Button** — `--accent` fill, white text, `--radius`, `padding: 10px 18px`.
Disabled while a job runs (`opacity: .5; cursor: not-allowed`) — one job at a
time is a real constraint (`CLAUDE.md` §9), so the UI states it honestly.

**Code block** — `--surface-2`, `--radius-lg`, `1px solid var(--border)`,
`overflow-x: auto`, `padding: var(--s4)`. Copy button top-right, ghost style,
becomes "copied" for 1.5s. No syntax highlighting library in v1.

**Result table** — full width, `border-collapse: collapse`, header row
`--text-mute` uppercase 12px, cells mono 13px, `1px solid var(--border)` row
separators, zebra via `--surface-2` on even rows. Wrap in
`overflow-x: auto` — extracted data is arbitrary width.

**Error block** — mono 13px, `--failed` 3px left border, `--surface-2` fill.
Show the traceback **verbatim**. This is a developer tool; the raw error is the
most useful thing on the page. Never replace it with "Something went wrong".

## 7. Non-negotiables

- Focus rings stay visible on every interactive element.
- Contrast ≥ 4.5:1 for text against its surface. `--text-mute` on `--bg` is the
  floor — do not go dimmer.
- Status is never conveyed by color alone: dot **and** word, always.
- Labels are real `<label for>`, textareas are resizable.
- The page works with JS for polling only. No framework required; if React is
  used, it is one component file, no router, no state library.

## 8. Explicitly not doing

Gradients, glassmorphism, drop shadows beyond a hairline border, icon library,
dark/light toggle widget (respect the OS), animated logos, empty-state
illustrations, toast notifications, syntax highlighting. Every one of these is
weight added to a form and a status line.
