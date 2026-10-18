"""
step4_build_catalog.py - join MovieLens + TMDB + IMDb into one catalog (movies AND series).

Input : movies.parquet (step1), tmdb_meta.parquet (step2, optional), scores.parquet (step3, optional),
        popularity snapshots (data/raw/tmdb/snapshots or ml/sample_data/snapshots)
Output: data/processed/catalog_base.parquet - every CONTRACT catalog column except the three
        emotion columns (step6 adds those), plus a few helper columns (ml_tags, velocity_source).

Computed columns (each has its own small function below so it is easy to explain):
  age_rating        CBFC-style bucket U / UA 7+ / UA 13+ / UA 16+ / A. Prefer the Indian certificate,
                    else US (movie MPA or TV rating), else UK. All mappings live in AGE_RATING_MAP.
  critic_score      0-100: Metacritic > Rotten Tomatoes > IMDb x 10 > TMDB x 10
  quality_score     0-1: Bayesian-average user rating (so 3 ratings of 5 stars do not beat
                    10,000 ratings of 4.5) blended 70/30 with the critic score
  popularity_score  0-1: log-scaled MovieLens rating count, TMDB popularity and IMDb votes, averaged
  trending_velocity relative popularity change between the last two TMDB snapshots; if there are
                    fewer than 2 snapshots, the recent MovieLens rating velocity from step1
  decade, mood_tags (rules from genres + keywords; step6 later adds emotion-based tags)
Time: a few seconds (ml-25m: < 1 min).
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

import config
from utils import banner, fail, join_list, log, split_list, warn

# ----------------------------------------------------------------------------------------------
# Age ratings: one dictionary for every certificate we understand -> CONTRACT AGE_RATINGS bucket
# ----------------------------------------------------------------------------------------------
AGE_RATING_MAP = {
    "IN": {  # CBFC (cinema) + the 7+/13+/16+/18+ labels Indian streaming services use
        "U": "U", "ALL": "U", "UA": "UA 13+", "U/A": "UA 13+",
        "UA 7+": "UA 7+", "UA 13+": "UA 13+", "UA 16+": "UA 16+",
        "7+": "UA 7+", "13+": "UA 13+", "16+": "UA 16+", "18+": "A", "A": "A", "S": "A",
    },
    "US": {  # MPA film ratings + US TV parental guidelines
        "G": "U", "PG": "UA 7+", "PG-13": "UA 13+", "R": "UA 16+", "NC-17": "A",
        "TV-Y": "U", "TV-G": "U", "TV-Y7": "UA 7+", "TV-Y7-FV": "UA 7+", "TV-PG": "UA 7+",
        "TV-14": "UA 16+", "TV-MA": "A",
    },
    "GB": {  # BBFC
        "U": "U", "UC": "U", "PG": "UA 7+", "12A": "UA 13+", "12": "UA 13+", "15": "UA 16+",
        "18": "A", "R18": "A",
    },
}
COUNTRY_PRIORITY = ["IN", "US", "GB"]


def _canon(cert: str) -> str:
    """'U/A 13+' and 'UA13+' and 'ua 13+' all become 'UA13+'."""
    return cert.upper().replace(" ", "").replace("/", "")


_LOOKUP = {country: {_canon(k): v for k, v in table.items()} for country, table in AGE_RATING_MAP.items()}


def age_rating_from(certifications: str) -> tuple[str, str]:
    """'US:PG-13|IN:UA' -> ('UA 13+', 'IN:UA'). Unknown -> ('', first raw certificate or '')."""
    certs = {}
    for item in split_list(certifications):
        country, _, cert = item.partition(":")
        if cert:
            certs.setdefault(country.strip().upper(), cert.strip())
    for country in COUNTRY_PRIORITY:
        cert = certs.get(country)
        bucket = _LOOKUP.get(country, {}).get(_canon(cert)) if cert else None
        if bucket:
            return bucket, f"{country}:{cert}"
    first = next(iter(certs.items()), None)
    return "", (f"{first[0]}:{first[1]}" if first else "")


# ----------------------------------------------------------------------------------------------
# Scores
# ----------------------------------------------------------------------------------------------
def critic_score(df: pd.DataFrame) -> pd.Series:
    """0-100. Metacritic > Rotten Tomatoes > IMDb*10 > TMDB*10 (TMDB only with >= 50 votes)."""
    tmdb = (df["tmdb_vote_avg"] * 10).where(df["tmdb_vote_count"].fillna(0) >= 50)
    score = df["metascore"].combine_first(df["rt_score"]).combine_first(df["imdb_rating"] * 10).combine_first(tmdb)
    return score.round(1)


def _bayes(mean: pd.Series, count: pd.Series, prior_weight: float) -> pd.Series:
    """Bayesian average: pulls titles with few votes towards the overall average.

    bayes = (count * mean + m * C) / (count + m)   where C = vote-weighted overall mean, m = prior weight
    """
    ok = mean.notna() & (count.fillna(0) > 0)
    if not ok.any():
        return pd.Series(np.nan, index=mean.index)
    c = float((mean[ok] * count[ok]).sum() / count[ok].sum())
    n = count.fillna(0)
    return ((n * mean.fillna(c) + prior_weight * c) / (n + prior_weight)).where(ok)


def compute_quality_score(df: pd.DataFrame, mean_col: str = "ml_rating_mean",
                          count_col: str = "ml_rating_count") -> pd.Series:
    """0-1 quality. User part (MovieLens > IMDb > TMDB) blended 70/30 with the critic score.

    step8 calls this with ratings from the TRAINING split only, so tuning never peeks at test data.
    """
    ml_count = df[count_col].fillna(0).astype("float64")
    prior = float(np.clip(ml_count[ml_count > 0].median() if (ml_count > 0).any() else 20, 20, 200))
    ml = (_bayes(df[mean_col].astype("float64"), ml_count, prior) - 0.5) / 4.5      # 0.5-5 stars -> 0-1
    ml = ml.where(ml_count >= config.MIN_RATINGS)
    imdb = (_bayes(df["imdb_rating"].astype("float64"), df["imdb_votes"].astype("float64"), 1000.0) - 1.0) / 9.0
    tmdb = _bayes(df["tmdb_vote_avg"].astype("float64"), df["tmdb_vote_count"].astype("float64"), 100.0) / 10.0
    # IMDb/TMDB voters are more generous than MovieLens raters, so put their scores on the
    # MovieLens scale first (match mean and spread on titles that have both) - otherwise every
    # series (IMDb only) would look better than every movie.
    imdb, tmdb = _rescale_like(imdb, ml), _rescale_like(tmdb, ml)
    user = ml.combine_first(imdb).combine_first(tmdb)
    critic = df["critic_score"].astype("float64") / 100.0
    quality = (0.7 * user + 0.3 * critic).combine_first(user).combine_first(critic)
    # Stretch to the full 0-1 range (1st percentile -> 0, 99th -> 1) so that thresholds such as
    # "quality > 0.7" in the backend mean "clearly better than most titles".
    lo, hi = quality.quantile(0.01), quality.quantile(0.99)
    if pd.notna(lo) and hi > lo:
        quality = (quality - lo) / (hi - lo)
    return quality.fillna(0.5).clip(0, 1).round(4).astype("float64")


def _rescale_like(values: pd.Series, target: pd.Series) -> pd.Series:
    """Linear rescale so `values` has the same mean/std as `target` on titles that have both."""
    both = values.notna() & target.notna()
    if both.sum() < 30 or values[both].std() == 0:
        return values
    v, t = values[both], target[both]
    return (values - v.mean()) / v.std() * t.std() + t.mean()


def _log_minmax(values: pd.Series) -> pd.Series:
    x = np.log1p(values.where(values > 0))
    lo, hi = x.min(), x.max()
    if pd.isna(lo) or hi <= lo:
        return x * 0
    return (x - lo) / (hi - lo)


def compute_popularity_score(df: pd.DataFrame, count_col: str = "ml_rating_count") -> pd.Series:
    """0-1: average of the log-scaled popularity signals each title has (missing ones are skipped)."""
    parts = pd.concat([_log_minmax(df[count_col].astype("float64")),
                       _log_minmax(df["tmdb_popularity"].astype("float64")),
                       _log_minmax(df["imdb_votes"].astype("float64"))], axis=1)
    return parts.mean(axis=1, skipna=True).fillna(0.0).round(4)


def trending_velocity(df: pd.DataFrame, snapshot_dir: Path) -> tuple[pd.Series, pd.Series]:
    """Relative popularity change between the last two snapshots (+ where the value came from)."""
    velocity = pd.Series(np.nan, index=df.index)
    snaps = sorted(snapshot_dir.glob("popularity_*.csv")) if snapshot_dir.exists() else []
    if len(snaps) >= 2:
        old, new = (pd.read_csv(p, dtype={"tmdb_id": "int64"}) for p in snaps[-2:])
        both = new.merge(old, on=["content_type", "tmdb_id"], suffixes=("_new", "_old"))
        both["v"] = (both["popularity_new"] - both["popularity_old"]) / both["popularity_old"].clip(lower=1.0)
        keyed = df[["content_type", "tmdb_id"]].astype({"tmdb_id": "Int64"}).merge(
            both[["content_type", "tmdb_id", "v"]].astype({"tmdb_id": "Int64"}),
            on=["content_type", "tmdb_id"], how="left")
        velocity = pd.Series(keyed["v"].to_numpy(), index=df.index)
        log(f"Trending velocity from snapshots {snaps[-2].stem[-8:]} -> {snaps[-1].stem[-8:]} "
            f"for {velocity.notna().sum():,} titles")
    else:
        log(f"{len(snaps)} popularity snapshot(s) found - using MovieLens rating velocity instead")
    source = pd.Series(np.where(velocity.notna(), "tmdb", "none"), index=df.index)
    ml_velocity = df["ml_velocity"].where(df["ml_rating_count"] > 0)
    use_ml = velocity.isna() & ml_velocity.notna()
    velocity = velocity.where(~use_ml, ml_velocity)
    source = source.where(~use_ml, "movielens")
    return velocity.fillna(0.0).clip(-1.0, 5.0).round(4), source


# ----------------------------------------------------------------------------------------------
# Mood tags (base rules from genres + keywords; step6 adds emotion-based tags)
# ----------------------------------------------------------------------------------------------
WORDS = {
    "dark": {"revenge", "serial killer", "murder", "dystopia", "corruption", "drugs", "violence", "gangster",
             "mafia", "psychopath", "torture", "crime boss", "dark comedy", "neo-noir", "noir", "drug cartel",
             "post-apocalypse", "nuclear war", "holocaust", "caste violence"},
    "cozy": {"christmas", "small town", "village", "cooking", "food", "holiday", "cat", "dog", "village life",
             "slice of life", "small town life", "everyday life", "bookshop", "seaside town", "countryside"},
    "thrilling": {"heist", "chase", "conspiracy", "spy", "hostage", "survival", "manhunt", "cat and mouse",
                  "assassin", "escape", "bomb", "countdown", "car chase", "investigation", "kidnapping"},
    "romantic": {"love", "romance", "wedding", "love triangle", "first love", "romantic comedy", "forbidden love",
                 "true love", "young love", "lost love", "love story", "teenage romance", "office romance"},
    "mind-bending": {"time travel", "dream", "dreams", "parallel universe", "memory loss", "twist ending",
                     "alternate reality", "simulation", "time loop", "nonlinear timeline", "multiverse",
                     "layered reality", "unreliable narrator", "split personality", "alternate timeline",
                     "time dilation", "memory erasure", "subconscious", "mind-bending", "parallel lives",
                     "work life split", "alternate outcomes", "illusion"},
    "epic": {"epic", "kingdom", "battle", "empire", "quest", "mythology", "warrior", "final battle", "middle-earth",
             "space opera", "king", "chola empire", "roman empire", "galactic empire", "noble houses"},
    "heartwarming": {"friendship", "family", "father son", "father daughter", "mother daughter", "dog",
                     "coming of age", "kindness", "teacher", "found family", "reunion", "childhood", "siblings",
                     "brothers", "sisters", "grandfather", "healing", "second chance"},
    "scary": {"ghost", "haunted", "demon", "monster", "zombie", "zombies", "supernatural", "curse", "possession",
              "slasher", "haunted house", "haunted hotel", "haunting", "creature", "folk horror", "masked killer",
              "haunted mansion", "exorcism"},
    "inspiring": {"biography", "sports", "underdog", "based on true story", "true story", "education",
                  "perseverance", "freedom fighters", "struggle", "upsc", "wrestling", "boxing", "cricket",
                  "hockey", "self respect", "courage", "honesty", "entrepreneur", "civil services", "dream"},
    "melancholic": {"grief", "loss", "loneliness", "death", "regret", "nostalgia", "terminal illness",
                    "bittersweet", "longing", "unspoken feelings", "memories", "tragedy", "tearjerker"},
}
HEAVY_GENRES = {"Horror", "Thriller", "War", "Crime"}


def base_mood_tags(genres: list[str], keywords: set[str], runtime, age_rating: str) -> list[str]:
    g = set(genres)
    kw = keywords

    def has(tag):
        return bool(WORDS[tag] & kw)

    tags = set()
    if "Comedy" in g:
        tags.add("funny")
    if "Action" in g:
        tags.add("action-packed")
    if "Horror" in g or (has("scary") and g & {"Thriller", "Fantasy", "Mystery"}):
        tags.add("scary")
    if "Romance" in g or has("romantic"):
        tags.add("romantic")
    if "Thriller" in g or has("thrilling") or {"Action", "Crime"} <= g:
        tags.add("thrilling")
    if has("mind-bending") or ("Sci-Fi" in g and g & {"Mystery", "Thriller"}):
        tags.add("mind-bending")
    dark = ("Film-Noir" in g or ("Horror" in g and "Comedy" not in g)
            or (has("dark") and not g & {"Children", "Animation"})
            or ("War" in g and age_rating in ("UA 16+", "A") and "Comedy" not in g))
    if dark:
        tags.add("dark")
    kid_safe = age_rating not in ("UA 16+", "A")
    if g & {"Children", "Animation"} and kid_safe:
        tags.add("family")
    if (g & {"Children", "Animation"} or {"Comedy", "Romance"} <= g or has("cozy")) \
            and not dark and not g & {"Horror", "Thriller"}:
        tags.add("cozy")
    if g & {"Comedy", "Children", "Musical", "Animation"} and not g & HEAVY_GENRES and not dark:
        tags.add("feel-good")
    if has("heartwarming") and g & {"Drama", "Comedy", "Children", "Animation"} and not dark and "Horror" not in g:
        tags.add("heartwarming")
    if has("inspiring") or "Documentary" in g:
        tags.add("inspiring")
    if "Drama" in g and has("melancholic"):
        tags.add("melancholic")
    long_film = pd.notna(runtime) and runtime >= 150
    if (has("epic") and g & {"Adventure", "Fantasy", "War", "Action"}) or (long_film and g & {"Adventure", "War", "Fantasy"}):
        tags.add("epic")
    if g & {"Drama", "Mystery", "Thriller"} and pd.notna(runtime) and runtime >= 130 \
            and not g & {"Action", "Comedy", "Children"}:
        tags.add("slow-burn")
    if g & {"Comedy", "Children", "Animation"} and (pd.isna(runtime) or runtime <= 120) \
            and not dark and "scary" not in tags and "War" not in g:
        tags.add("light")
    return [t for t in config.MOOD_TAGS if t in tags]


# ----------------------------------------------------------------------------------------------
# Building the table
# ----------------------------------------------------------------------------------------------
def load_optional(path: Path, what: str) -> pd.DataFrame | None:
    if path.exists():
        return pd.read_parquet(path)
    warn(f"{path.name} not found - continuing without {what}")
    return None


def build_movies(movies: pd.DataFrame, tmdb: pd.DataFrame | None) -> pd.DataFrame:
    cat = movies.rename(columns={"movieId": "movie_id"}).copy()
    cat["movie_id"] = cat["movie_id"].astype("int64")
    cat["content_type"] = "movie"
    if tmdb is None or tmdb.empty:
        return cat
    t = tmdb[tmdb["content_type"] == "movie"].drop(columns=["content_type"]).drop_duplicates("movie_id")
    cat = cat.merge(t, on="movie_id", how="left", suffixes=("", "_tmdb"))
    # Prefer TMDB's clean title ("The Shawshank Redemption"); keep MovieLens values as fallback
    cat["title"] = cat["title_tmdb"].where(cat["title_tmdb"].fillna("") != "", cat["title"])
    cat["year"] = cat["year"].combine_first(cat["year_tmdb"])
    cat["genres"] = cat["genres"].where(cat["genres"].fillna("") != "", cat["genres_tmdb"])
    cat["imdb_id"] = cat["imdb_id"].where(cat["imdb_id"].fillna("") != "", cat["imdb_id_tmdb"])
    cat["tmdb_id"] = cat["tmdb_id"].combine_first(cat["tmdb_id_tmdb"])
    return cat.drop(columns=[c for c in cat.columns if c.endswith("_tmdb")])


def build_series(tmdb: pd.DataFrame | None, sample: bool) -> pd.DataFrame:
    if tmdb is None or tmdb.empty:
        return pd.DataFrame()
    s = tmdb[tmdb["content_type"] == "series"].copy()
    before = len(s)
    only_junk = s["tmdb_genres"].map(lambda g: bool(split_list(g)) and set(split_list(g)) <= {"News", "Talk", "Reality", "Soap"})
    s = s[(s["overview"].fillna("") != "") & (s["genres"].fillna("") != "") & ~only_junk]
    if not sample:
        s = s[s["tmdb_vote_count"].fillna(0) >= config.TMDB_MIN_SERIES_VOTES]
    log(f"Series: kept {len(s):,} of {before:,} (dropped talk/news/reality shows, missing overviews, "
        f"< {config.TMDB_MIN_SERIES_VOTES} votes)")
    s["ml_rating_mean"] = np.nan
    s["ml_rating_count"] = 0
    s["ml_velocity"] = 0.0
    s["ml_tags"] = ""
    return s


def main(argv=None):
    parser = argparse.ArgumentParser(description="Step 4 - build the catalog")
    parser.add_argument("--sample", action="store_true", help="use the demo-data folders")
    args = parser.parse_args(argv)

    banner("Step 4/9 - Build catalog (movies + series)")
    out_dir = config.processed_dir(args.sample)
    if not (out_dir / "movies.parquet").exists():
        fail("movies.parquet not found -> run step1_prepare_movielens.py first")
    movies = pd.read_parquet(out_dir / "movies.parquet")
    tmdb = load_optional(out_dir / "tmdb_meta.parquet", "TMDB metadata (no posters/overviews/series)")
    scores = load_optional(out_dir / "scores.parquet", "IMDb/critic scores")

    cat = pd.concat([build_movies(movies, tmdb), build_series(tmdb, args.sample)], ignore_index=True)
    if scores is not None:
        sc = scores.drop_duplicates("movie_id").rename(columns={"imdb_id": "imdb_id_scores"})
        cat = cat.merge(sc, on="movie_id", how="left")
        cat["imdb_id"] = cat["imdb_id"].where(cat["imdb_id"].fillna("") != "", cat["imdb_id_scores"])
        cat = cat.drop(columns=["imdb_id_scores"])

    # Make sure every expected column exists (e.g. when TMDB/scores were skipped)
    text_cols = ["imdb_id", "title", "genres", "overview", "poster_path", "backdrop_path", "original_language",
                 "certifications", "directors", "cast", "keywords", "collection_name", "trailer_key", "ml_tags"]
    num_cols = ["tmdb_id", "year", "runtime", "seasons", "ml_rating_mean", "ml_rating_count", "tmdb_popularity",
                "tmdb_vote_avg", "tmdb_vote_count", "imdb_rating", "imdb_votes", "metascore", "rt_score", "ml_velocity"]
    for col in text_cols:
        cat[col] = cat[col].fillna("").astype(str) if col in cat.columns else ""
    for col in num_cols:
        cat[col] = pd.to_numeric(cat[col], errors="coerce") if col in cat.columns else np.nan
    cat["ml_rating_count"] = cat["ml_rating_count"].fillna(0).astype("int64")
    cat["keywords"] = cat["keywords"].str.lower()

    log(f"Catalog: {len(cat):,} titles ({(cat['content_type'] == 'movie').sum():,} movies, "
        f"{(cat['content_type'] == 'series').sum():,} series)")

    # ---- computed columns -------------------------------------------------------------------
    ages = cat["certifications"].map(age_rating_from)
    cat["age_rating"] = ages.map(lambda a: a[0])
    cat["certification_raw"] = ages.map(lambda a: a[1])
    cat["critic_score"] = critic_score(cat)
    cat["quality_score"] = compute_quality_score(cat)
    cat["popularity_score"] = compute_popularity_score(cat)
    cat["trending_velocity"], cat["velocity_source"] = trending_velocity(
        cat, (config.SAMPLE_DIR if args.sample else config.TMDB_RAW_DIR) / "snapshots")
    cat["decade"] = (cat["year"] // 10 * 10).astype("Int64")
    cat["mood_tags"] = [
        join_list(base_mood_tags(split_list(g), set(split_list(k)) | set(split_list(t)), r, a))
        for g, k, t, r, a in zip(cat["genres"], cat["keywords"], cat["ml_tags"], cat["runtime"], cat["age_rating"])
    ]
    for col in ("tmdb_id", "year", "runtime", "seasons", "tmdb_vote_count", "imdb_votes"):
        cat[col] = cat[col].round().astype("Int64")

    keep = [c for c in config.CATALOG_COLUMNS if c not in ("start_emotion", "end_emotion", "emotion_arc")]
    extra = ["ml_tags", "velocity_source", "ml_velocity", "metascore", "rt_score"]
    cat = cat[keep + extra].sort_values("movie_id").reset_index(drop=True)
    if cat["movie_id"].duplicated().any():
        fail("Duplicate movie_id values in the catalog - check SERIES_ID_OFFSET / input data")
    cat.to_parquet(out_dir / "catalog_base.parquet", index=False)

    known_age = (cat["age_rating"] != "").mean() * 100
    log(f"age_rating known for {known_age:.0f}% | critic_score for {cat['critic_score'].notna().mean() * 100:.0f}% "
        f"| overview for {(cat['overview'] != '').mean() * 100:.0f}%")
    tag_counts = pd.Series([t for tags in cat["mood_tags"] for t in split_list(tags)]).value_counts()
    log("Most common mood tags: " + ", ".join(f"{k} {v}" for k, v in tag_counts.head(8).items()))
    log(f"Saved {out_dir / 'catalog_base.parquet'}")


if __name__ == "__main__":
    main()
