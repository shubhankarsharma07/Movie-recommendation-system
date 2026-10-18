# CineMatch — Build Contract (shared by ml/, backend/, frontend/)

This file is the single source of truth that lets the three parts be built separately and still fit
together. If you are building one part, follow this exactly; do not rename fields, endpoints or files.

Source documents: the project Synopsis + SRS v1.0 (summarised in section 0). Owner's style: simple, obvious
names (frontend, backend, ml), plain code, well commented for a B.Tech student, production-shaped.

---------------------------------------------------------------------------------------------------
## 0. What the SRS requires (summary — every item must be implemented)

* Auth & profile (bcrypt hashing, never store/log plaintext — NFR-2).
* Catalog browser: filter by genre, year, title search (FR-1.3); each card shows title, poster, genre, year,
  average user rating (FR-1.4).
* Ratings: 0.5–5.0 in half steps (FR-1.1); anything else rejected with an error that states the valid range and
  NO row written (FR-1.2, AC-2). Re-rating updates the row (unique user+movie), updates created_at.
* Context & preference selection (FR-2.1): occasion/festival, starting/ending emotion, reference film(s),
  director, actor, language, age rating, franchise. Plus weather, time available, nostalgia (decade), genres,
  content type (movie / series).
* Auto-detect local weather + time of day when location permission granted (FR-2.2); user can override any
  value (FR-2.3); if location denied → no weather lookup, use time of day + manual filters (FR-2.4).
  OpenWeatherMap free tier (60 calls/min) — if limit hit or service down, silently drop the weather signal.
* Behavioural logging: drop-off timestamp per playback session (FR-3.1, AC-4), rewatch count (FR-3.2),
  browse-to-select time (FR-3.3), plus pause/rewind, fast-forward, details-page clicks, binge behaviour.
* Recommendation API (FR-4.1): takes user + context object; missing/invalid user → HTTP 400
  "User could not be identified". Returns up to 20 ranked items (FR-4.2), each with a short reason
  ("Because you rated X highly") (FR-4.3). If model unavailable / no usable results → top popularity list
  labelled "Trending now" (FR-4.4, AC-3) — never empty, never a 500. User can dismiss/downvote an item and it
  never comes back for that user (FR-4.5).
* Watch-party mode: one list blending 2+ users' taste profiles.
* Admin/analytics panel: engagement with recommendations.
* NFR-1: ranked list in < 2 s at p95 for up to 65,000 movies. NFR-3: log every recommendation request with a
  unique request id, movies returned and context used; keep ≥ 90 days. NFR-4: if retraining fails keep serving
  the last good model.
* Hosting: FastAPI backend on Render free web service (512 MB RAM, sleeps after 15 min idle → frontend must
  show a friendly "waking up the server" state and retry). PostgreSQL in production; SQLite allowed for local dev.

---------------------------------------------------------------------------------------------------
## 1. Folder layout

```
cinematch/
  README.md                 # how to run everything (written last by the coordinator)
  CONTRACT.md               # this file
  .env.example
  data/                     # never committed (gitignore). raw/ and processed/ live here
  ml/                       # OFFLINE pipeline (run on laptop / Colab). Produces model artifacts.
  backend/                  # FastAPI app. Reads artifacts from backend/artifacts/
    app/
    artifacts/
      current.txt           # contains the folder name of the live version, e.g. v20261002_1030
      v20261002_1030/       # one folder per trained version (files in section 2)
  frontend/                 # static site, vanilla HTML/CSS/JS (ES modules, no build step)
```

---------------------------------------------------------------------------------------------------
## 2. Model artifacts (ml/ writes them, backend/ reads them)

Folder: `backend/artifacts/<version>/` where `<version>` = `v%Y%m%d_%H%M%S`.
After ALL files are written successfully, the ml step writes `<version>` into `backend/artifacts/current.txt`
(write to `current.txt.tmp` then `os.replace` → atomic). If anything fails, current.txt is not touched (NFR-4).

All arrays are aligned to the ROW ORDER of `catalog.csv` (row i in the CSV == index i in every .npy).

| File | Type | Meaning |
|---|---|---|
| `catalog.csv` | CSV, UTF-8, header | one row per item (movie or series), columns below |
| `item_factors.npy` | float32 [N, k] | SVD item latent factors q_i (zeros if item has no CF data) |
| `item_bias.npy` | float32 [N] | SVD item bias b_i (0 if no CF data) |
| `has_cf.npy` | bool [N] | True if item was in the CF training set |
| `plot_emb.npy` | float16 [N, d] | L2-normalised content embedding (plot + genres + keywords). zeros if missing |
| `has_emb.npy` | bool [N] | True if embedding exists |
| `model_meta.json` | JSON | see below |

### catalog.csv columns (exact names; list fields are pipe-separated `a|b|c`; missing = empty string)
```
movie_id            int    MovieLens movieId. Series (not in MovieLens) use 10_000_000 + tmdb tv id
content_type        str    "movie" | "series"
tmdb_id             int|empty
imdb_id             str|empty   e.g. tt0111161
title               str
year                int|empty
genres              list   MovieLens-style names: Action|Adventure|Animation|Children|Comedy|Crime|Documentary|
                           Drama|Fantasy|Film-Noir|Horror|IMAX|Musical|Mystery|Romance|Sci-Fi|Thriller|War|Western
overview            str    short plot text
poster_path         str|empty   TMDB path like /abc.jpg (frontend builds https://image.tmdb.org/t/p/w342<path>)
backdrop_path       str|empty   TMDB path (frontend uses /t/p/w1280)
runtime             int|empty   minutes (series: typical episode runtime)
seasons             int|empty   series only
original_language   str    ISO 639-1 code, e.g. en, hi, ta, te, ml, ko, ja, fr, es
age_rating          str    one of: U | UA 7+ | UA 13+ | UA 16+ | A   (CBFC-style buckets; empty if unknown)
certification_raw   str    original certificate string + country, e.g. "US:PG-13"
directors           list   (series: creators)
cast                list   top 5 billed
keywords            list   TMDB keywords (lowercase)
collection_name     str|empty   TMDB belongs_to_collection.name = franchise
ml_rating_mean      float|empty  mean MovieLens rating
ml_rating_count     int    number of MovieLens ratings (0 for series)
tmdb_popularity     float|empty
tmdb_vote_avg       float|empty
tmdb_vote_count     int|empty
imdb_rating         float|empty
imdb_votes          int|empty
critic_score        float|empty  0–100 unified critic score (Metacritic > Rotten Tomatoes > IMDb*10 > TMDB*10)
popularity_score    float  0–1 normalised popularity (used for "Trending now" fallback ordering)
trending_velocity   float  relative change in popularity between the last two snapshots (can be negative; 0 if unknown)
quality_score       float  0–1 (Bayesian-averaged rating blended with critic score)
start_emotion       str    one of EMOTIONS (section 4) — tone of the beginning of the plot
end_emotion         str    one of EMOTIONS — tone of the ending
emotion_arc         str    one of ARCS (section 4)
mood_tags           list   subset of MOOD_TAGS (section 4)
decade              int|empty   e.g. 1990
trailer_key         str|empty   YouTube video key (TMDB videos, type Trailer, site YouTube)
```

### model_meta.json
```json
{
  "version": "v20261002_103000",
  "trained_at": "2026-10-02T10:30:00Z",
  "algorithm": "SVD (Surprise, biased matrix factorisation)",
  "n_factors": 100, "n_epochs": 20, "lr_all": 0.005, "reg_all": 0.02,
  "global_mean": 3.53,
  "fold_in_reg": 0.1,
  "n_items": 20000, "n_cf_items": 18000, "n_train_ratings": 24000000, "n_users_trained": 160000,
  "embedding_model": "all-MiniLM-L6-v2" ,
  "emotion_model": "j-hartmann/emotion-english-distilroberta-base",
  "metrics": {"rmse": 0.78, "mae": 0.59, "baseline_global_mean_rmse": 1.05, "baseline_bias_rmse": 0.86,
              "precision_at_10": 0.0, "recall_at_10": 0.0, "ndcg_at_10": 0.0},
  "blend_weights": {"cf": 0.45, "content": 0.15, "ref": 0.35, "ctx": 0.25, "quality": 0.12, "trend": 0.05, "behavior": 0.10},
  "data_sources": ["MovieLens 25M", "TMDB API", "IMDb non-commercial datasets"],
  "dataset_mode": "full" 
}
```
(`dataset_mode` is "sample" when built from the bundled demo data.) Backend must tolerate missing keys
(use sensible defaults).

---------------------------------------------------------------------------------------------------
## 3. Database (backend owns it; ml/retrain.py reads ratings + playback_sessions from it)

SQLAlchemy 2.x, works on PostgreSQL (prod) and SQLite (local). `DATABASE_URL` env; default
`sqlite:///./cinematch.db`. Normalise `postgres://` → `postgresql+psycopg://`.

```
users            id UUID pk, email unique, display_name, password_hash, is_admin bool, created_at
movies           movie_id INT pk, title, year, content_type, genres (text pipe), poster_path, backdrop_path,
                 original_language, age_rating, runtime, ml_rating_mean, ml_rating_count, popularity_score
                 (seeded from catalog.csv on startup if empty or when version changes)
ratings          id UUID pk, user_id FK, movie_id FK, rating NUMERIC(2,1) CHECK 0.5..5.0 and half steps,
                 created_at (updated on re-rate), UNIQUE(user_id, movie_id)
playback_sessions id UUID pk, user_id, movie_id, request_id nullable, started_at, ended_at nullable,
                 drop_off_sec float nullable, duration_sec float nullable, completed bool,
                 pause_count int, seek_back_count int, seek_forward_count int, is_rewatch bool, start_number int
events           id UUID pk, user_id, movie_id nullable, type str, request_id nullable, row_id nullable,
                 value float nullable, position_sec float nullable, created_at
request_logs     id UUID pk (= request_id), user_id nullable, endpoint, context JSON, movie_ids JSON,
                 fallback bool, latency_ms float, created_at        (NFR-3; never delete rows < 90 days old)
dismissals       id UUID pk, user_id, movie_id, created_at, UNIQUE(user_id, movie_id)
parties          id UUID pk, code (6 chars, unique), host_id, created_at
party_members    id UUID pk, party_id FK, user_id FK, UNIQUE(party_id, user_id)
```

---------------------------------------------------------------------------------------------------
## 4. Shared vocabularies (backend serves them via GET /api/meta/filters; ml uses the same strings)

```
EMOTIONS   = ["joy", "sadness", "fear", "anger", "surprise", "disgust", "neutral"]
EMOTION_LABELS (UI) = {"joy":"Happy","sadness":"Sad","fear":"Tense","anger":"Angry","surprise":"Surprised",
                       "disgust":"Disturbed","neutral":"Calm"}
ARCS       = ["rise", "fall", "fall-rise", "rise-fall", "steady"]
             (rise = ends more positive than it starts, fall = opposite, steady = same polarity;
              fall-rise / rise-fall when start and end are the same polarity but the middle differs —
              only if a 3-segment analysis is available, else use rise/fall/steady)
MOOD_TAGS  = ["feel-good","dark","cozy","thrilling","romantic","mind-bending","epic","heartwarming","scary",
              "funny","inspiring","melancholic","action-packed","family","slow-burn","light"]
WEATHER    = ["sunny","cloudy","rainy","stormy","snowy","foggy","hot","cold"]
TIME_OF_DAY= ["morning","afternoon","evening","night","late_night"]   (5–11,12–16,17–20,21–23,0–4 local hour)
TIME_AVAILABLE_MIN options = [30, 60, 90, 120, 150, 180, null(=no limit)]
OCCASIONS  = ["date_night","family_night","friends_hangout","solo_chill","kids_time","late_night_thrills",
              "rainy_day_in","weekend_binge"]
FESTIVALS  = ["diwali","holi","navratri","eid","christmas","new_year","halloween","valentines",
              "raksha_bandhan","independence_day","onam","pongal","thanksgiving"]
AGE_RATINGS= ["U","UA 7+","UA 13+","UA 16+","A"]   (ordered; "max_age_rating" means <= that bucket)
FRANCHISE_MODE = ["any","only","exclude"]
CONTENT_TYPE  = ["any","movie","series"]
```

---------------------------------------------------------------------------------------------------
## 5. REST API (backend implements, frontend calls). Base path `/api`. JSON everywhere.

Auth: `Authorization: Bearer <JWT>` (HS256, `JWT_SECRET` env, 7-day expiry).
Errors: `{"detail": "message"}` with proper status codes.

### 5.1 Auth
* `POST /api/auth/register` body `{email, password (>=6), display_name}` → `201 {access_token, token_type:"bearer", user}`
* `POST /api/auth/login` body `{email, password}` → `{access_token, token_type, user}` ; bad creds → 401
* `GET /api/auth/me` → `user`
* `user` = `{id, email, display_name, is_admin, created_at, rating_count}`
  (is_admin = email in `ADMIN_EMAILS` env, comma-separated, or the very first registered user)

### 5.2 Shared item shape — `MovieCard`
```json
{"movie_id": 1, "title": "Toy Story", "year": 1995, "content_type": "movie",
 "genres": ["Adventure","Animation"], "poster_url": "https://image.tmdb.org/t/p/w342/x.jpg" | null,
 "backdrop_url": "https://image.tmdb.org/t/p/w1280/y.jpg" | null,
 "avg_rating": 3.9, "rating_count": 57309, "runtime": 81, "age_rating": "U", "language": "en",
 "critic_score": 92.0, "mood_tags": ["feel-good","family"], "start_emotion": "joy", "end_emotion": "joy",
 "overview": "short text", "trailer_key": "abc" | null, "collection_name": "Toy Story Collection" | null}
```
`avg_rating`/`rating_count` = MovieLens stats merged with in-app ratings. Recommendation items add
`"score": 0.83, "reason": "Because you rated Inception 5★"`, and in watch-party mode `"member_scores": {"Aman": 4.3, ...}`.

### 5.3 Catalog
* `GET /api/movies?q=&genre=&year_from=&year_to=&language=&content_type=&sort=popular|rating|year|title&page=1&page_size=40`
  → `{items:[MovieCard], total, page, page_size}`
* `GET /api/movies/search?q=inc&limit=10` → `{items:[MovieCard]}` (title prefix/contains, popular first)
* `GET /api/movies/{movie_id}` → `MovieCard` + `{directors:[], cast:[], keywords:[], emotion_arc, decade,
  quality_score, popularity_score, trending_velocity, imdb_rating, user_rating: 4.5|null, dismissed: bool,
  similar:[MovieCard x12]}` (similar = CF item-factor cosine blended with plot-embedding cosine). 404 if unknown.
  Must work without auth (user_rating null then); with auth fills user_rating.
* `GET /api/meta/filters` → `{genres:[], languages:[{code,name}], age_ratings:[], decades:[], weather:[{id,label,icon}],
  time_of_day:[], time_available:[{minutes,label}], occasions:[{id,label,icon}], festivals:[{id,label,icon,date?}],
  emotions:[{id,label}], franchises:[top 50 names], directors:[top 100], actors:[top 150], content_types:[]}`
* `GET /api/meta/people?role=director|actor&q=nol&limit=10` → `{items:["Christopher Nolan", ...]}`
* `GET /api/onboarding/movies` → `{items:[MovieCard x30]}` diverse popular titles for new users to rate (cold start).

### 5.4 Ratings
* `POST /api/ratings` body `{movie_id, rating}` → `{movie_id, rating, created_at}`.
  Invalid value → **400** `{"detail":"Rating must be between 0.5 and 5.0 in steps of 0.5"}` and nothing written.
  Unknown movie → 404. Requires auth (401 otherwise).
* `GET /api/ratings/me` → `{items:[{movie: MovieCard, rating, created_at}]}` newest first
* `DELETE /api/ratings/{movie_id}` → 204

### 5.5 Context
* `GET /api/context?lat=&lon=&hour=` → 
```json
{"weather": {"id":"rainy","label":"Rainy","temp_c":24.1,"city":"Mathura","description":"light rain","source":"live"} | null,
 "time_of_day":"evening", "hour":19,
 "upcoming_festival": {"id":"diwali","label":"Diwali","date":"2026-11-08","days_away":37} | null,
 "weather_status": "live" | "no_location" | "unavailable"}
```
  `hour` = browser local hour (server is UTC). No lat/lon → no weather call (`weather_status:"no_location"`).
  OWM key from env `OPENWEATHER_API_KEY`; missing key, rate-limit (keep ≤ 55 calls/min) or error →
  `weather:null, weather_status:"unavailable"` (never an error). Cache per rounded (lat,lon) 10 minutes.

### 5.6 Recommendations
`Context` object (all optional):
```json
{"weather":"rainy","time_of_day":"evening","hour":19,"time_available_min":120,"occasion":"date_night",
 "festival":"diwali","reference_movie_ids":[79132,109487],"directors":["Christopher Nolan"],"actors":[],
 "language":"en","max_age_rating":"UA 13+","franchise_mode":"any","nostalgia_decade":1990,
 "start_emotion":"sadness","end_emotion":"joy","genres":["Drama"],"content_type":"any"}
```
* `POST /api/recommendations` body `{context: Context, limit: 20}` (limit max 20 — FR-4.2)
  → `{request_id, label, fallback: bool, items:[MovieCard+score+reason], context_used: Context}`.
  No/invalid token → **400** `{"detail":"User could not be identified"}` (FR-4.1).
  Fallback (no model / nothing usable) → `fallback:true, label:"Trending now"` popularity list that still
  respects the hard filters, relaxing them if they would make the list empty (AC-3).
* `GET /api/home?lat=&lon=&hour=` (auth required; 401 otherwise) →
```json
{"request_id":"uuid","context":{...same as /api/context...},"needs_onboarding": true|false,
 "hero": MovieCard+reason,
 "rows":[{"id":"for_you","title":"Recommended for you","subtitle":"Based on your ratings",
          "filter": {Context preset that reproduces this row in the Mood Mixer},
          "items":[MovieCard+score+reason]}]}
```
  Rows (skip a row if it would have < 4 items): `continue_watching` (sessions with drop-off < 90%),
  `for_you`, `because_<movie_id>` ("Because you rated X"), `weather` ("Perfect for this rainy evening"),
  `time_fit` ("Fits in 90 minutes"), `festival` (if upcoming within 21 days), `trending` ("Trending now"),
  `acclaimed` ("Critically acclaimed"), `hidden_gems` (high quality, low popularity), `feel_good`
  (start any → end joy), `nostalgia` ("90s nostalgia"), `series_binge` ("Series to binge"),
  `date_night`, `mind_bending`. Every row carries the `filter` preset so "See all" opens the Mood Mixer with
  the same filters and returns the same kind of list.
* `POST /api/recommendations/{movie_id}/dismiss` → 204 (FR-4.5; also logs event `dismiss`)
* `DELETE /api/recommendations/{movie_id}/dismiss` → 204 (undo)

### 5.7 Behaviour logging (Module 3)
* `POST /api/playback/start` body `{movie_id, request_id?}` → `{session_id, is_rewatch, start_number}`
* `POST /api/playback/{session_id}/event` body `{type: "pause"|"resume"|"seek_back"|"seek_forward", position_sec}` → 204
* `POST /api/playback/{session_id}/stop` body `{position_sec, duration_sec, completed}` → `{session_id, drop_off_sec, completion_ratio}` (AC-4)
* `GET /api/playback/me` → `{items:[{session_id, movie: MovieCard, started_at, ended_at, drop_off_sec, duration_sec, completed, is_rewatch}]}`
* `POST /api/events` body `{events:[{type, movie_id?, request_id?, row_id?, value?, position_sec?}]}` → 204
  types: `impression` (row shown), `details_open` (details-page click), `select` (value = browse-to-select ms,
  measured from list shown → first play/details click on an item of that list), `trailer_open`, `search`,
  `filter_apply`, `dismiss`, `binge_next` (auto-play next episode).
* `GET /api/profile/insights` → `{top_genres:[{genre,score}], completion_rate, avg_browse_to_select_ms,
  rewatch_count, binge_score, seek_forward_rate, favourite_decade, ratings_count, sessions_count,
  taste_summary:"You love mind-bending sci-fi and feel-good comedies…"}`

### 5.8 Watch party
* `POST /api/party` body `{member_emails?: []}` → `{code, host, members:[user]}` (host auto-member; unknown emails → 404 listing them)
* `POST /api/party/{code}/join` → party
* `GET /api/party/{code}` → party
* `POST /api/party/{code}/recommendations` body `{context, limit}` → same as /api/recommendations plus each
  item has `member_scores` {display_name: predicted stars} and `reason` like "Everyone should enjoy this".
  Strategy: average of members' normalised scores minus a disagreement penalty, and drop items where any
  member's predicted rating < 2.5 ("average without misery").

### 5.9 Admin (is_admin only; 403 otherwise)
* `GET /api/admin/stats` → `{users, ratings, sessions, events, requests, ratings_by_day:[{date,count}],
  rating_histogram:{"0.5":n,...}, top_rated:[{movie,avg,count}], rec_ctr, avg_browse_to_select_ms,
  avg_completion, dismiss_rate, latency_p50_ms, latency_p95_ms, requests_by_day:[...],
  context_usage:{weather:n, occasion:n, ...}, model: model_meta}`
* `POST /api/admin/reload-model` → re-reads current.txt → `{version}`
* `POST /api/admin/retrain` → starts `python ml/retrain.py` in a background subprocess if
  `ENABLE_INAPP_RETRAIN=true`, returns `{status:"started"}`; `GET /api/admin/retrain` → `{status, last_log_tail}`
* `GET /api/health` → `{status:"ok", model_loaded, model_version, dataset_mode, catalog_size}` (public)

---------------------------------------------------------------------------------------------------
## 6. Environment variables (.env)
```
DATABASE_URL=sqlite:///./cinematch.db        # prod: Postgres URL (Neon / Supabase / Render)
JWT_SECRET=change-me
ADMIN_EMAILS=you@example.com
OPENWEATHER_API_KEY=
TMDB_API_KEY=                                # used by ml/ only (offline enrichment)
OMDB_API_KEY=                                # optional, ml/ only
CORS_ORIGINS=*                               # prod: your frontend URL
ARTIFACTS_DIR=./artifacts
ENABLE_INAPP_RETRAIN=false
```
Frontend: `frontend/js/config.js` exports `API_BASE` (default `""` = same origin; set to the Render URL in prod).
For local dev the backend also serves `../frontend` at `/` so `http://localhost:8000` runs the whole app.
