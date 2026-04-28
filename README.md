# Résumé Advisor API

Backend for the Odyssey Therapeia Résumé Advisor tool. Stateless FastAPI service that parses résumés/JDs, fetches JD URLs, and calls Claude to produce structured tailoring advice.

## Quick start

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/) (`pip install uv` if you don't have it).

```bash
# 1. install dependencies
uv sync

# 2. set up env
cp .env.example .env
# edit .env — set ANTHROPIC_API_KEY to a real key

# 3. run dev server (auto-reloads on file change)
uv run uvicorn app.main:app --reload --port 8000

# 4. verify
curl http://localhost:8000/api/health
# → {"status":"ok","service":"resume-advisor-api",...}

# 5. open auto-generated docs
open http://localhost:8000/docs
```

## Tests

```bash
uv run pytest -v
```

Tests don't need a real API key — they use a fake key and mock external calls.

## Project layout

```
app/
├── main.py              FastAPI app factory, CORS, lifespan
├── config.py            Pydantic settings, env loading
├── routes/              Thin HTTP handlers — validate input, call services
│   └── health.py
├── services/            Real logic — analyzer, parser, fetcher
└── prompts/             System prompts as .md files (editable by non-engineers)

tests/                   Pytest suite — mock external calls
```

## Endpoints (V1 plan)

| Method | Path             | Status     | Description                              |
|--------|------------------|------------|------------------------------------------|
| GET    | `/api/health`    | ✅ done    | Service identity, no external calls      |
| POST   | `/api/parse`     | planned    | Extract text from .pdf / .docx / .txt    |
| POST   | `/api/fetch-jd`  | planned    | Fetch + clean a JD URL                   |
| POST   | `/api/analyze`   | planned    | Run Claude analysis on resume + JD       |
| GET    | `/docs`          | ✅ free    | Auto-generated Swagger UI                |

## Deployment

Target: Fly.io. See `Dockerfile` (coming next session).
