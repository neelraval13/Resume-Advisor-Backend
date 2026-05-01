# Résumé Advisor API

Backend for the Odyssey Therapeia Résumé Advisor — a tool that analyzes a candidate's résumé against a specific job description and returns honest, structured tailoring advice. **No fabrication, real growth recommendations, LaTeX-friendly line edits.**

Built with FastAPI, Pydantic, Anthropic Claude, and a strong commitment to advisor-over-ghostwriter design.

---

## Live deployment

**Production URL:** `https://resume-advisor-api.onrender.com`

Hosted on Render (Singapore region, free tier). Auto-deploys on `git push` to `main`. Idle service sleeps after 15 minutes; first request after sleep takes 30-50s to wake.

**Authenticated requests require the `X-API-Key` header.** The production key lives in the team password manager.

```bash
# Health check (no auth required)
curl https://resume-advisor-api.onrender.com/api/health

# Authenticated request
curl -H "X-API-Key: <key>" https://resume-advisor-api.onrender.com/api/...
```

---

## What this service does

Four endpoints that compose into one pipeline:

| Method | Path             | Auth | Description                                            |
|--------|------------------|------|--------------------------------------------------------|
| GET    | `/api/health`    | open | Service identity — used by uptime monitors             |
| POST   | `/api/parse`     | ✓    | Extract text from a PDF, DOCX, TXT, MD, or TEX upload  |
| POST   | `/api/fetch-jd`  | ✓    | Fetch and clean a job description from a URL           |
| POST   | `/api/analyze`   | ✓    | Stream tailoring advice from Claude as SSE events      |
| GET    | `/docs`          | open | Auto-generated Swagger UI                              |

The typical flow: parse a résumé file → fetch a JD by URL → analyze the two together. Each endpoint is independently useful; the pipeline is just composition.

### What `/api/analyze` returns

A structured `AnalyzeResponse` with:

- `fit_assessment` — honest 0-100 score with narrative
- `strengths_to_emphasize` — items already in the résumé to foreground for this JD
- `line_edits` — verbatim before/after edits (LaTeX-friendly, copy-pasteable)
- `structural_suggestions` — section reordering, hierarchy changes
- `skill_gap_recommendations` — projects to build, courses to take, certs to earn, with `concrete_starter` for "this week" actions
- `red_flags` — honesty concerns the candidate should know about

The endpoint streams over Server-Sent Events: `start → many text events → result → done`. The frontend gets live progress feedback during Claude's ~10s generation, then a fully validated structured payload at the end.

---

## Quick start (local dev)

Requires **Python 3.11+** and [**uv**](https://docs.astral.sh/uv/) (`pip install uv` if you don't have it).

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

# 5. open auto-generated docs
open http://localhost:8000/docs
```

In dev, auth is disabled by default (no `API_KEY` set in `.env`), so you don't need to send the header.

---

## Tests

```bash
uv run pytest -v
```

37 tests, sub-second runtime. All external calls (Anthropic, httpx, file parsers) are mocked — tests don't burn tokens, hit networks, or depend on real fixtures.

---

## Architecture

### Project layout

```
app/
├── main.py              FastAPI app factory, CORS, lifespan, route registration
├── config.py            Pydantic settings, env loading, fail-fast validation
├── schemas.py           Shared Pydantic models — request/response/SSE event shapes
├── routes/              Thin HTTP handlers — validate input, call services, map errors
│   ├── health.py
│   ├── parse.py
│   ├── fetch_jd.py
│   └── analyze.py
├── services/            Real logic — testable functions, custom exception hierarchies
│   ├── parser.py        PDF/DOCX/text extraction, scanned-PDF detection
│   ├── fetcher.py       URL fetch + trafilatura + bot-block detection
│   └── analyzer.py      Claude streaming, JSON parsing, Pydantic validation
├── middleware/
│   └── auth.py          X-API-Key dependency, optional enforcement
└── prompts/
    └── advisor.md       System prompt as a markdown file (editable by non-engineers)

tests/
├── test_health.py       Service identity, no-auth requirement
├── test_parse.py        Real PDF/DOCX fixtures generated in-memory via reportlab
├── test_fetch_jd.py     httpx mocked via respx — no real network calls
├── test_analyze.py      Anthropic SDK mocked — no real Claude calls
└── test_auth.py         All four auth states (off, missing, wrong, right)
```

### Design principles

**Routes are thin, services are testable.** Routes do input validation, error mapping to HTTP status codes, and response serialization. All real logic — parsing, fetching, prompting — lives in `services/` as plain functions, independently testable without spinning up FastAPI.

**Pydantic validation as a contract gate.** Every Claude response goes through `AnalyzeResponse.model_validate()` before reaching the client. If the LLM hallucinates a field name, returns an out-of-range score, or omits a required key, the request fails with a typed `parse_error` event instead of poisoning the frontend with malformed data.

**Custom exceptions per domain.** Each service has its own exception hierarchy (`ParserError`, `FetcherError`, `AnalyzerError` with subclasses). Routes catch the base class, map to HTTP via the `code` attribute. Cleaner than tuple returns or generic `ValueError`s.

**Honest LLM prompting.** The system prompt in `app/prompts/advisor.md` is explicit: never fabricate, distinguish "change now" from "do over time," cite verbatim text for find-and-replace, suggest concrete starter actions for skill gaps. This is the philosophical core of the tool.

### Key technical decisions

- **`pdfplumber` over `pypdf`** — better layout handling, exposes per-character positions for tight-kerning detection
- **`x_tolerance=1.5` in PDF extraction** — handles tightly-kerned PDFs (LaTeX, Canva, designer templates) where the default fails silently
- **`trafilatura` for URL content extraction** — strips nav/ads/cookie banners cleanly, beats hand-rolled BeautifulSoup
- **SSE streaming over WebSockets** — one-way server-to-client, no protocol complexity, native browser support via `EventSource`
- **No retry on malformed JSON** — single attempt, surface the failure as `parse_error` event with raw text for the frontend to handle
- **API key as opt-in via `None` default** — auth disabled in dev, enforced in prod, same code path

---

## Configuration

All settings load from environment variables (or `.env` in dev). Required vs. optional listed in `.env.example`.

| Variable                  | Required | Default                      | Notes                                          |
|---------------------------|----------|------------------------------|------------------------------------------------|
| `ANTHROPIC_API_KEY`       | yes      | —                            | Production key from console.anthropic.com      |
| `API_KEY`                 | no       | `None` (auth off)            | Shared secret for `X-API-Key` enforcement      |
| `ANTHROPIC_MODEL`         | no       | `claude-sonnet-4-20250514`   |                                                |
| `ANTHROPIC_MAX_TOKENS`    | no       | `8000`                       |                                                |
| `ENVIRONMENT`             | no       | `development`                | Affects `/health` response only                |
| `CORS_ORIGINS`            | no       | `http://localhost:5173`      | Comma-separated allowed origins                |
| `MAX_UPLOAD_SIZE_MB`      | no       | `10`                         | File upload limit                              |
| `REQUEST_TIMEOUT_SECONDS` | no       | `60`                         |                                                |
| `FETCH_TIMEOUT_SECONDS`   | no       | `15`                         | Per-URL fetch timeout in `/fetch-jd`           |

---

## Deploy

### Production: Render

Auto-deploys from `main` via `render.yaml` (Blueprint config). Render watches the GitHub repo and rebuilds on every push.

To change deployment config:

1. Edit `render.yaml`
2. Commit and push
3. Render auto-syncs (or click "Sync" in the dashboard)

To rotate secrets without code changes:

1. Render dashboard → service → Environment tab
2. Edit env var, save
3. Render restarts the service

### Building the Docker image locally

```bash
# Build for production target (amd64, what Render runs)
docker build --platform linux/amd64 -t resume-advisor-api:local .

# Run with secrets from .env
docker run --rm -p 8000:8000 --env-file .env --name resume-advisor-local resume-advisor-api:local

# Verify
curl http://localhost:8000/api/health
```

The image is multi-stage — a `uv`-based builder produces the venv, then a slim Python runtime copies just the venv and source. Final image is ~96 MB.

### Operational basics

- **Live logs:** Render dashboard → service → Logs tab
- **Deployment events:** Render dashboard → service → Events tab
- **Manual redeploy:** Render dashboard → "Manual Deploy" → "Deploy latest commit"

---

## Limitations and known issues

- **Cold starts on free tier.** Render's free plan sleeps after 15 minutes of no traffic. First request after sleep takes 30-50s. For an internal tool used a few times a day, this is acceptable; if it becomes painful, options are: (a) ping `/api/health` every 14 minutes via cron-job.org, or (b) upgrade to Render's paid tier ($7/month for always-on).

- **No retry on malformed Claude output.** ~1-3% of analyze calls return JSON that fails Pydantic validation (Claude duplicating keys, missing fields, etc.). User has to resubmit. Trade-off chosen for V1 simplicity; revisit if observed error rate becomes painful.

- **No OCR for scanned PDFs.** PDFs without text layers (photo-of-a-resume scans) are detected and rejected with a clear message. Adding Tesseract.js or a similar OCR layer would unblock these but adds significant deploy complexity.

- **No rate limiting.** Auth is the only protection against abuse. Internal-tool assumption — if the API key leaks, rotate it. For external use, add a per-IP rate limiter at the route layer.

- **Bot-blocked job boards.** LinkedIn and some Indeed listings return login walls instead of JD content; we detect this and return a clear "paste manually" error. No headless browser fallback in V1.

---

## Roadmap

V2 candidates, in rough priority order:

1. **Frontend** — React + Vite + TypeScript app consuming this API, with the editorial UI from the original artifact
2. **Cover letter generation** — same inputs, different prompt, ~30 minutes of work given the existing analyzer infrastructure
3. **Interview prep output** — given the analysis, generate likely interview questions tied to matched strengths and gaps
4. **Saved base résumé** — paste once, tailor against many JDs without re-uploading
5. **Sentry integration** — error tracking for production failures
6. **Per-IP rate limiting** — guard against API key leakage
7. **Streaming retry** — single corrective retry on malformed JSON
8. **OCR for scanned PDFs** — Tesseract.js integration for image-only resumes

---

## Credits

Built by Neel Raval at Odyssey Therapeia.

Tooling: FastAPI · Pydantic · Anthropic Python SDK · pdfplumber · python-docx · trafilatura · httpx · uv · pytest · respx · Docker · Render
