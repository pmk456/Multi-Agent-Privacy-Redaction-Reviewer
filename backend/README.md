# Backend

FastAPI service plus the agent workflow. Run from the repository root:

```bash
uvicorn app.main:app --reload --app-dir backend
pytest backend/tests
```

`app/schemas/` is shared by every slice - read CONTRIBUTING.md before changing it.
