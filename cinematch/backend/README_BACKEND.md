# CineMatch backend (FastAPI)

The API behind CineMatch: login, catalog, ratings, context (weather / time /
festival), personalised recommendations, watch party, behaviour logging and the
admin panel. It follows `../CONTRACT.md` exactly.

It reads the model files that `ml/` produces (`artifacts/<version>/…`). At
runtime there is **no torch / sentence-transformers**: only numpy arrays, so it
fits Render's free tier (512 MB RAM).

## Folder layout

```
backend/
  app/
    main.py          app setup, startup, CORS, static frontend at "/"
    config.py        environment variables
    database.py      SQLAlchemy engine/session (SQLite or PostgreSQL)
    models.py        database tables (CONTRACT section 3)
    schemas.py       request bodies + the Context object
    security.py      bcrypt passwords + JWT tokens
    deps.py          "current user", "admin only", model state
    vocab.py         shared vocabularies (CONTRACT section 4)
    routers/         one file per API area (auth, movies, meta, ratings, context,
                     recommend, home, playback, events, profile, party, admin, health)
    services/
      model_store.py   loads artifacts, hot reload, keeps the last good model (NFR-4)
      recommender.py   the scoring engine (fold-in CF, content, context, MMR, fallback, party)
      rules.py         context rules: weather / time / occasion / festival -> genres, moods
      festivals.py     festival dates Oct 2026 - Dec 2027
      weather.py       OpenWeatherMap with rate limit + 10 min cache
      behavior.py      viewing behaviour profile (completion, rewatch, skipping, binge)
      explain.py       "Because you rated Inception 5★" reasons
      logging.py       request logging + request_logs table (NFR-3)
      catalog_sync.py  copies catalog.csv into the movies table
      rating_stats.py  in-app rating averages (cached 60 s)
      cards.py         MovieCard / user JSON shapes
  tests/             pytest suite + make_fixture_artifacts.py (synthetic catalog)
  seed_db.py         copy catalog.csv into the movies table by hand (optional)
  requirements.txt   render.yaml   .python-version (3.12)   .env.example
```

## Run it locally

```bash
cd backend
python3.12 -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                   # then edit if you like

# A) with the real model from ml/ (backend/artifacts/current.txt must exist)
uvicorn app.main:app --reload

# B) no model yet? use the small synthetic test catalog
ARTIFACTS_DIR=tests/fixtures/artifacts uvicorn app.main:app --reload
```

Open http://localhost:8000 (the frontend is served from `../frontend`),
http://localhost:8000/docs (interactive API docs) or
http://localhost:8000/api/health.

The first account you register becomes the admin. With no artifacts at all the
API still runs and every list falls back to "Trending now".

## Tests

```bash
cd backend
pytest                                    # SQLite in a temp folder, ~30 s
pytest --deselect tests/test_latency.py   # skip the 65,000-title speed test, ~4 s

# same tests on PostgreSQL:
TEST_DATABASE_URL=postgresql+psycopg://user:pass@localhost:5432/cinematch_test pytest
```

The tests never touch `backend/artifacts/`. They use `tests/fixtures/artifacts/`
(120 synthetic titles) and generate a 65,000-title catalog in a temp folder for
the speed test.

What is covered: AC-1…AC-4, FR-1.2 (5.5 and 4.3 rejected, nothing written),
FR-4.1 (400), FR-4.4 fallback (with no model, no catalog, or no database),
FR-4.5 dismissals, hard filters and relaxing, watch party, admin 403,
playback drop-off, NFR-3 logging and the 90/180-day cleanup, NFR-4 (corrupt new
version keeps the old model), hot reload, weather (mocked), festivals, and
NFR-1 latency.

## How a recommendation is made (short version)

1. **Your taste (CF fold-in).** The item factors from training are fixed. Your
   own vector is solved from your ratings each request, so the list changes right
   after you rate something. Finishing a film counts like a 4★, rewatching like
   4.5★ and quitting early like 2★, at half weight.
2. **Plot similarity.** Plots of titles you liked minus plots you disliked.
3. **Reference films.** "More like these": 50 % CF similarity + 50 % plot similarity.
4. **Context.** Weather, time of day, occasion, festival, start/end emotion,
   decade, genres. See the readable rules in `services/rules.py`.
5. **Quality, trend, behaviour.**
6. `score = Σ weight × component`, using the weights from `model_meta.json`.
   Components with no data get weight 0.
7. **Hard filters**: time, language, age, director, actor, franchise, type. If
   fewer than 20 titles match, filters are relaxed (actors → directors →
   language → franchise → runtime), exact matches stay first, and the label says
   so.
8. **MMR re-ranking**, so the 20 results are not all the same kind of film.
   Each one gets a reason.
9. **Fallback**: no model, or nothing usable, gives the popularity list
   "Trending now". It never returns empty and never returns a 500.

## Deploying on Render (free tier)

1. Create a PostgreSQL database (Neon / Supabase / Render) and copy its URL.
   `postgres://…` URLs are fixed up automatically.
2. Commit the artifacts the ml pipeline produced (`backend/artifacts/…`).
3. In Render choose **New → Blueprint**. Point it at this repo and set the
   blueprint path to `backend/render.yaml` (or copy the file to the repo root).
4. Fill in `DATABASE_URL`, `ADMIN_EMAILS`, `CORS_ORIGINS` (your static site
   URL) and optionally `OPENWEATHER_API_KEY`. `JWT_SECRET` is generated for you.
5. In `frontend/js/config.js` set `API_BASE` to the API URL.

On startup the API creates the tables, loads `artifacts/current.txt` and copies
the catalog into the `movies` table.

Measured on a 65,000-title catalog (k=100 factors, 384-d float16 embeddings):

| | |
|---|---|
| `POST /api/recommendations` | p50 70 ms, p95 ~110 ms (in-process); ~90 ms over HTTP |
| `GET /api/home` (13 rows) | p95 ~240 ms |
| Memory | ~345 MB after start, ~410 MB after a burst of 38 parallel requests (realistic text sizes) |

`render.yaml` sets `MALLOC_ARENA_MAX=2` and `MALLOC_MMAP_THRESHOLD_=131072`.
Without them memory grows much more under load. Heavy scoring runs at most 4
requests at a time (`recommender.ENGINE_SLOTS`).

**Hot reload vs. memory.** A new version is loaded next to the old one, so the
old one can keep serving if the new one is broken (NFR-4). For a full
65,000-title catalog, two copies do not fit in 512 MB. On the free tier, ship
new artifacts with a normal redeploy (restart) instead of
`/api/admin/reload-model`. Smaller catalogs (e.g. 20,000 titles) hot-reload fine.

## Small additions to the contract (backwards compatible)

These are optional extras; clients that ignore them work unchanged.

* `Context.preset`: `"trending" | "acclaimed" | "hidden_gems" | "mind_bending"`.
  Some home rows cannot be described with the normal Context fields, so their
  `filter` carries a preset. "See all" sends it back to `/api/recommendations`
  and gets the same kind of list.
* `relaxed_filters` in recommendation responses: the hard filters that were
  dropped because too few titles matched (the label also says so).
* `continue_watching` items also carry `progress` (0…1) and `resume_sec`.
* Validation errors (422) return `{"detail": "field: message", "errors": [...]}`,
  so `detail` is always a readable string. The submitted value is never echoed
  back, because it could be a password.
* `GET /api/movies/{id}` also returns `seasons` and `certification_raw`.
* `app_state` table: a tiny key/value table that remembers which artifact
  version was copied into `movies`.
* Series have no MovieLens ratings. Until someone rates a series in the app,
  its card shows the TMDB vote average (converted to a 5-point scale).
