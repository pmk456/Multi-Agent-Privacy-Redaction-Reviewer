# Frontend

Plain HTML, CSS and JavaScript, with Plotly from a CDN for charts. No build step and no
framework.

Start the backend and open **http://127.0.0.1:8000/ui/**. The API serves this folder, so
there is no CORS setup. The **sample batch** loads `mock/batch_result.json` (fictional data)
and works even when the backend is offline.

| File | |
|---|---|
| `index.html` | page structure: app bar, Review page, Documents and Insights containers |
| `styles.css` | the design system: tokens, type scale, buttons, inputs, tables, status, toasts |
| `app.js` | all behaviour. Check with `node --check frontend/app.js` |
| `mock/batch_result.json` | generated, don't edit: `cd backend && python scripts/make_frontend_mock.py` |
| `assets/` | Alliance University logo |

## Design system (`styles.css`)

- **Light, warm-neutral surfaces with one accent.** Navy is used for actions and focus.
- **Colour only carries meaning:** teal = released, maroon = blocked or critical, amber =
  warning. Charts use one sequential scale, where darker means more information removed.
- **Hierarchy from type and whitespace.** Each page has one boxed surface at most; sections
  are separated by headings and hairlines, not cards.
- **Radius by importance:** 4 px for badges and tokens, 6 px for controls, 8 px for the
  primary surface.
- **Motion is short (≤ 200 ms)** and only confirms a state change. It's disabled under
  `prefers-reduced-motion`.
- **All text colour pairs meet WCAG AA contrast.** Focus is always visible, and tabs support
  the arrow keys.

Tailwind's Play CDN was dropped: Tailwind documents it as a development tool, not for
production, and a small set of tokens is easier to keep consistent.

## Rules here

- The API never sends an original identifier, so there is nothing to accidentally render.
  Show categories, risks and strategies; refer to an entity by its `entity_id`.
- Render API data with `textContent` / `el(...)`, never `innerHTML`. The only exception is
  the static SVG paths in `ICONS`.
- Entity spans point into the **original** text, not the redacted text. Don't display them
  or use them to index `redacted_text`.
- Upload errors come back as `file_index` + `code` and are shown on the matching file row.
  The filename next to an error comes from the browser's own file picker; the server never
  echoes it.

Owner: Pulagampalli Sai Mahima
