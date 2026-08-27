# Plan 07 — Frontend

**Goal:** one page: submit a job, watch it, read the result. Follow `design.md`
exactly — tokens at `:root`, mono for code-shaped content, real errors shown.

**Owner:** `script-writer` implements; `backend-engineer` reviews against
`design.md`.

## Files

```
frontend/index.html      # markup + <style> using the design.md tokens
frontend/app.js          # submit + poll + render
```

No build step, no framework, no dependencies (`rules.md` §G29).

## Steps

1. **Markup** — the two cards from `design.md` §4. Real `<label for>` on every
   field. Textareas are `resize: vertical`. The schema and prompt textareas use
   `--font-mono`.
2. **Prefill the schema textarea** with a small working example so the first
   run is one click away:
   ```json
   {"type":"object","properties":{"title":{"type":"string"},"price":{"type":"string"}},"required":["title"]}
   ```
3. **Submit** — `POST /jobs`, disable the button, render the job card.
   On a 422, show the validation detail in the error block. Do not swallow it.
4. **Poll** — `GET /jobs/{id}` every 2s. Stop on `done` or `failed`. Stop after
   5 minutes with a timeout message. Re-enable the button when polling stops
   (one job at a time is honest, per `design.md` §6).
5. **Render status** — dot + word + `attempt N / 3`. The pulse animation on
   `running` is the only animation in the app (`design.md` §5).
6. **Render result** — build the table from the union of keys across rows, in
   first-seen order. Wrap in `overflow-x: auto`. `null` renders as a dimmed
   `—`, not the string "null".
7. **Render script** — mono code block, copy button that flips to "copied" for
   1.5s.
8. **Render failure** — the traceback verbatim in the error block
   (`rules.md` §G28). Link to `/jobs/{id}/attempts` for the full history.
9. **Escape everything.** Extracted data is arbitrary third-party text. Use
   `textContent` / `createElement`, never `innerHTML`, when rendering results.
   This is XSS-by-scraped-content and it is a real path.

## Check (`test-engineer`)

No test framework for a two-file page. Manual checklist, run and recorded:

- [ ] Submit → card appears → dot pulses → result table renders
- [ ] A failing job shows the real traceback, not a generic message
- [ ] A result row containing `<img src=x onerror=alert(1)>` renders as **text**
- [ ] Keyboard: tab through every field, focus ring visible on each
- [ ] 360px viewport: no horizontal page scroll; the result table scrolls itself
- [ ] Light mode (OS setting) is legible
- [ ] Button is disabled while a job runs, re-enabled after

## Out of scope

Job history list, saved schemas, syntax highlighting, re-run button, auth.
