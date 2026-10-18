# CineMatch: Personalized Movie Recommendation Engine

A full-stack recommender with a Netflix-style ambient UI. It covers everything in the Synopsis and SRS v1.0:
auth, catalog, ratings, context filters, behaviour logging, a hybrid collaborative-filtering engine,
personalized carousels, watch party, and an admin/analytics panel.

```
cinematch/
  ml/         offline pipeline: prepare data -> enrich -> embeddings -> emotion arcs -> train -> export
  backend/    FastAPI API (reads the trained model from backend/artifacts/)
  frontend/   static site (vanilla HTML/CSS/JS, no build step)
  data/       your raw + processed data (never commit)
  CONTRACT.md the exact API / artifact / database spec all three parts follow
```

---

## PART A: Run it right now, in 5 minutes (demo data, no API keys)

A demo model is already trained and included. It uses about 340 real titles (Hollywood, Indian, Korean,
Japanese, plus 40 web series) and 800 synthetic users.

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate      Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```
Open **http://localhost:8000**. The backend also serves the frontend.
1. Register. The first account automatically becomes the admin.
2. Rate 5 movies in onboarding. Your home carousels appear straight away.
3. Try the Mood Mixer, Play (the simulated player logs drop-off, pause, rewind and skip), Watch Party, Profile and Admin.

The demo has no real posters, so CineMatch draws generated poster art. Real posters appear after Part B.

To see the UI with no backend at all, run `cd frontend && python -m http.server 5500` and open `http://localhost:5500/?mock=1`.

---

## PART B: Build it on the real data (beginning to end)

### Step 0: Get the free keys and data
| What | Where | Used for |
|---|---|---|
| MovieLens 25M (you have it). 32M is now GroupLens's recommended version and works too | grouplens.org/datasets/movielens | ratings for CF (`ratings.csv`, `movies.csv`, `links.csv`) |
| TMDB API key (free, non-commercial) | themoviedb.org → Settings → API | plot, posters, cast, director, keywords, franchise, language, age certificate (incl. India), runtime, trailer, web series |
| IMDb datasets (free, no key) | datasets.imdbws.com (`title.ratings.tsv.gz`) | audience score and votes, joined through links.csv imdbId |
| OMDb key (optional, 1,000 calls/day) | omdbapi.com | Rotten Tomatoes % and Metascore → critic score (fetch the most-rated titles first) |
| OpenWeatherMap key (free: 60 calls/min, 1M calls/month) | openweathermap.org | live weather. Use the `/data/2.5/weather` endpoint. A new key can take up to 2 hours to activate |
| Optional long plots | Kaggle "Wikipedia Movie Plots" / MPST / CMU Movie Summary Corpus | better emotional arcs than short TMDB overviews |

Copy `backend/.env.example` to `.env` at the repo root and fill in `TMDB_API_KEY`, `OPENWEATHER_API_KEY`, `JWT_SECRET`,
`MOVIELENS_DIR=path/to/ml-25m`.

**Where each SRS feature gets its data**
| Feature | Data source |
|---|---|
| Ratings / CF | MovieLens + your app's own ratings |
| Plot embeddings | TMDB overview (+ Wikipedia plot) → sentence-transformers (fallback TF-IDF+SVD) |
| Emotion arc (start → end emotion) | emotion classifier `j-hartmann/emotion-english-distilroberta-base` run on the first and last third of the plot |
| Critic score | OMDb (RT/Metacritic) → IMDb rating → TMDB vote average |
| Popularity / trending velocity | TMDB popularity snapshots (TMDB's free daily export files include popularity; compare over 7 days) |
| Director, actor, language, age rating, franchise, runtime, trailer | TMDB (`append_to_response=credits,keywords,release_dates,videos`) |
| Web series | TMDB `/tv/popular`, `/tv/top_rated` (content-based only, since MovieLens has no TV) |
| Weather | OpenWeatherMap, live, called from the backend (the key stays secret) |
| Occasion / festival / time / nostalgia | rule tables in `backend/app/services/rules.py` + `festivals.py` (no public data exists, so these are documented design choices) |
| Drop-off, rewatch, pause/rewind, fast-forward, browse-to-select, details clicks, binge | **no public movie dataset has these.** CineMatch logs them itself from the player and UI. For research reference, ContentWise Impressions is the closest public dataset. |

### Step 1: Train the model (laptop with 8 GB RAM, or Google Colab)
```bash
cd ml
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-extra.txt     # optional: real embeddings + emotion model (needs torch; use Colab if slow)
python run_all.py                          # runs steps 1-9 in order
# useful flags: --tune (hyper-parameter search)  --from-step 5 (resume)  --skip-tmdb  --skip-scores  --sample
```
What the steps do:
1. `step1_prepare_movielens.py`: cleans the data, keeps movies with at least 20 ratings, and saves parquet files.
2. `step2_fetch_tmdb.py`: fetches TMDB details for every movie plus popular web series. Results are cached, and it resumes if interrupted (roughly 20-40 min).
3. `step3_fetch_scores.py`: IMDb ratings + optional OMDb critic scores.
4. `step4_build_catalog.py`: joins everything and computes the age bucket (CBFC U / UA 7+ / UA 13+ / UA 16+ / A), critic, quality, popularity, trending velocity and mood tags.
5. `step5_embeddings.py`: plot embeddings.
6. `step6_emotion_arcs.py`: start emotion, end emotion, and arc (rise / fall / steady).
7. `step7_train.py`: **Surprise SVD** (biased matrix factorisation). Uses a temporal split (the latest 20% of each user's ratings) and prints Level 0 / Level 1 / SVD RMSE, MAE and precision@10. Surprise needs about 290 bytes per rating, so 25M ratings would need about 7 GB. The script samples whole users down to `MAX_RATINGS` (8M by default). On Colab you can raise it.
8. `step8_tune_blend.py`: tunes the hybrid blend weights on precision@10.
9. `step9_export.py`: writes `backend/artifacts/<version>/` and switches `current.txt` only if everything succeeded (NFR-4).

### Step 2: How the model works (the "algorithm")
A **hybrid, two-stage recommender**. Every part is classical ML and runs on CPU only (SRS C2):
1. **Collaborative filtering (SVD)** learns a vector for each movie from 25M ratings.
2. **Fold-in for app users**: when you rate a movie, the backend solves a small ridge regression for *your* vector against the fixed movie vectors (under 2 ms). Recommendations therefore change immediately, without retraining.
3. **Content similarity**: your liked movies' plot embeddings, which also handles cold start and reference films.
4. **Context score**: weather, time of day, occasion, festival, start and end emotion, nostalgia decade.
5. **Quality + trending priors**, plus a **behaviour profile** built from your sessions (completion, rewatch, skips, binge).
6. `score = Σ weight × component`, then **hard filters** (time available, language, age rating, director, actor, franchise, type), then **MMR diversity**. Each item gets a **reason** ("Because you rated X 5★", "Starts sad, ends happy").
7. **Watch party** uses "average without misery": it averages everyone's scores and drops anything a member is predicted to rate below 2.5.
8. **Fallback**: if the model is missing or returns nothing, you get a "Trending now" list, never an empty screen.

Demo-data results (temporal split): global-mean RMSE 0.859 → bias baseline 0.727 → **SVD 0.667**;
precision@10: popularity 0.077 → SVD 0.082 → **hybrid blend 0.126**. Expect roughly RMSE 0.78-0.80 for SVD on real MovieLens.

### Step 3: Retrain on your users' data (scheduled, never live)
`python ml/retrain.py` reads app ratings and playback sessions from `DATABASE_URL` and converts behaviour into
pseudo-ratings (completed → 4.0, rewatched → 4.5, dropped early → 2.0). It then retrains and swaps the model in atomically.
If it fails, the API keeps serving the old model. Run it weekly with a GitHub Actions cron job (free for public repos).

---

## PART C: Deploy for free (updated October 2026)
| Piece | Use | Why |
|---|---|---|
| Backend | **Render free web service** (Singapore region). The blueprint is `backend/render.yaml` | 512 MB RAM. Sleeps after 15 min, and the frontend shows a "waking up the server" screen |
| Database | **Neon free Postgres** (paste its URL into `DATABASE_URL`) | Render's free Postgres is deleted after about 30+14 days, which breaks the SRS 90-day log retention |
| Frontend | GitHub Pages or Cloudflare Pages. Set `API_BASE` in `frontend/js/config.js` to your Render URL | Render's free bandwidth is now only 5 GB/month |
| Retraining | GitHub Actions scheduled workflow | Render cron jobs aren't free |

Render tips: set `PYTHON_VERSION=3.12.x` (new services default to 3.14). Set `CORS_ORIGINS` to your frontend URL.
Commit the artifacts folder, because the Render disk is wiped on every restart. Keep the catalog at about 20k movies so the model fits in 512 MB.

## Tests
`cd backend && pytest`: 95 tests pass on SQLite and PostgreSQL 16. They cover AC-1 to AC-4, FR-1.2, FR-4.1, FR-4.4, FR-4.5,
NFR-3, NFR-4 and the latency check. On a 65,000-movie catalog, p95 is about 106-182 ms, against the 2 s target.
