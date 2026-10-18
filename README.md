# 🎬 CineMatch — Personalized Movie Recommendation Engine

A full-stack web app that learns a user's taste from their star ratings and viewing behaviour, then ranks a movie catalog using **collaborative filtering** adjusted for real-world context (weather, time, occasion, mood).

B.Tech CSE (AI) project, GLA University, Greater Noida · **Shubhankar Sharma** · Supervisor: Mr. Palash Singh

---

## Problem
Genre and release-year browsing doesn't surface movies that match a person's actual taste. CineMatch predicts the rating a user would give each unseen movie and builds personalized carousels such as *"Recommended for You"* and *"Because You Rated X"*.
It only recommends from a fixed catalog: no video streaming, payments or live critic-score feeds.

## Features
- **Accounts & ratings:** bcrypt + JWT login; 0.5–5.0 star ratings in half steps, invalid values rejected with an error
- **Catalog:** browse by genre/year, search by title, cards with poster, genres, year and average rating
- **Collaborative filtering:** SVD model trained offline; each user's taste profile is computed on the fly from their ratings
- **Context filters:** weather (live, with manual override), time of day, occasion, festival, start/end emotion, nostalgia, reference film, director, actor, language, age rating, franchise
- **Behaviour signals:** drop-off point, rewatches, pause/rewind/skip counts, browse-to-select time, clicks, binge behaviour
- **Explainable picks:** each recommendation has a reason; users can dismiss a movie
- **Watch-party mode:** blends several users' tastes into one list
- **Resilience:** "Trending now" fallback if the model is unavailable; failed retraining keeps the last good model
- **Logging & admin panel:** every recommendation request is logged for offline evaluation

## How it works
```
final score = weighted blend of
  collaborative-filtering taste + plot similarity + reference-film match
  + context fit + trending + behaviour
→ hard filters → diversity re-rank (MMR) → reasons attached
```
- **Model:** Surprise `SVD` (biased matrix factorization), `r̂ = μ + b_u + b_i + q_i·p_u`. It is trained on `ratings.csv`; movie vectors are exported, and a user's own vector is solved from their ratings at request time (`_fold_in`), so new ratings apply instantly.
- **Content features:** TMDB plot text → embeddings (TF-IDF+SVD, or MiniLM optionally) and a start/end emotional arc.
- **Context:** hand-written rule tables map weather/occasion/festival/mood to genre and mood weights. These are not learned.
- **Evaluation:** per-user temporal split (oldest 80% train / newest 20% test). Metrics: RMSE (primary), MAE, precision@10, compared with global-mean, bias-only and popularity baselines.

## Architecture
```
Offline (ml/): MovieLens + TMDB + IMDb → features → train SVD → versioned artifacts
                                   ↓ shared PostgreSQL ↑
Online: Frontend (vanilla JS) ⇄ FastAPI recommendation API + weather/context service
```

## Tech stack
Python · FastAPI · SQLAlchemy · PostgreSQL (SQLite for dev) · scikit-surprise · scikit-learn · NumPy/pandas · Vanilla HTML/CSS/JS · OpenWeatherMap · TMDB · MovieLens 25M.
Classical ML only, so no GPU is needed.

## Run locally
```bash
# backend
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload          # needs a .env with DATABASE_URL

# frontend
cd frontend && python -m http.server 5500   # add ?mock=1 to run without the backend

# train the model
cd ml && pip install -r requirements.txt
python run_all.py --sample             # demo on bundled synthetic data
python run_all.py                      # full MovieLens run (set MOVIELENS_DIR)

# tests
cd backend && pytest                   # 95 tests
```
Never commit `.env`, API keys or the raw MovieLens files (licence forbids redistribution).

## Project status

**✅ Done**
- Backend API (auth, ratings, catalog, recommendations, fallback, playback/event logging, party, admin)
- Training pipeline (steps 1–9), versioned model artifacts, safe retraining
- Context engine, hard filters, MMR re-ranking, behaviour → pseudo-ratings
- Frontend pages: login, onboarding, home, browse, search, results, profile, party, admin
- 95 automated tests passing

**🔄 In progress**
- Training on the full MovieLens 25M. The bundled model is a **demo** trained on synthetic data (800 users, 378 titles), so its metrics only show the pipeline works.

| Model | RMSE | MAE | Precision@10 |
|---|---|---|---|
| Level 0: global mean | _TBD_ | _TBD_ | – |
| Level 1: user + item bias | _TBD_ | _TBD_ | – |
| SVD | _TBD_ | _TBD_ | _TBD_ |

**📝 Planned**
- Public deployment (Render + Neon), user manual, test report and bug log

**Limitations:** the player is simulated; critic scores and trending data are periodic snapshots; Render's free tier sleeps after 15 minutes idle; the context rule tables are hand-designed.

## Future scope
Hybrid and neural recommenders, a natural-language chat front end, live critic scores and trending feeds.

## Credits
[MovieLens](https://grouplens.org/datasets/movielens/) (GroupLens), [TMDB](https://www.themoviedb.org/) (not endorsed by TMDB), IMDb datasets, OpenWeatherMap, [Surprise](https://surpriselib.com/).
