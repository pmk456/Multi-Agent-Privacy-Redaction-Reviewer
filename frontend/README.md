# Frontend

Plain HTML with Tailwind and Plotly from CDNs. No build step and no framework.

Start the backend and open **http://127.0.0.1:8000/ui/**. The API serves this folder, so
there is no CORS setup. **Demo mode** loads `mock/batch_result.json` (fictional data) and
works even while the pipeline is still a stub.

| File | |
|---|---|
| `index.html` | layout: upload, per-document and aggregate views |
| `app.js` | all behaviour. Check with `node --check frontend/app.js` |
| `mock/batch_result.json` | generated, don't edit: `cd backend && python scripts/make_frontend_mock.py` |
| `assets/` | Alliance University logo |

## Rules here

- The API never sends an original identifier, so there is nothing to accidentally render.
  Show categories, risks and strategies; refer to an entity by its `entity_id`.
- Render API data with `textContent` / `el(...)`, never `innerHTML`.
- Entity spans point into the **original** text, not the redacted text. Don't display them
  or use them to index `redacted_text`.
- Upload errors come back as `file_index` + `code`. The filename shown next to an error is
  taken from the browser's own file picker. The server never echoes it.

Owner: Pulagampalli Sai Mahima
