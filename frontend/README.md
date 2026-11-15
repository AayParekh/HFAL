# CSS Tracker (demo prototype)

Hospital Financial Assistance Compliance Tracker for the Community Service Society of New York (CSSNY).
Interactive frontend on **mock data only**. No backend. See `HANDOFF.md` for the backend boundary.

## Run it

```bash
npm install
npm run dev          # http://localhost:5173
npm test             # grading unit tests (Vitest)
npm run typecheck && npm run lint
npm run generate:mock  # regenerate src/api/mock/data/generated.json (seeded, deterministic)
```

`VITE_USE_MOCKS=true` (default, see `.env`) uses the in-browser mock API.

### Demo switches (URL query string)
- `/?mock=error` shows the table error state, `/?mock=empty` the empty state
- `/?pfi=unknown` opens the panel on a hospital that does not exist (404 error state)
- `/?pfi=739` deep-links to a hospital's panel

## Note on `src/components/ui`
The shadcn CLI could not be run when this project was scaffolded (no network), so the primitives
(button, badge, card, input, skeleton, alert, table, sheet) were written by hand in the shadcn style.
To replace them with the canonical versions:

```bash
npx shadcn@latest add button badge card input skeleton alert table sheet --overwrite
```
