"""
Context rules: how weather, time of day, occasion and festival change what we
recommend.

The idea is "mood management": people pick films that fit (or fix) how they
feel. A cold rainy evening calls for something warm and cosy; a sunny afternoon
for adventure and laughs; a stormy late night for thrills.

Each rule is ONE readable dict:
    genres    {MovieLens genre: weight 0..1}       item gets the best matching weight
    moods     {mood tag: weight 0..1}              item gets the best matching weight
    keywords  {TMDB keyword: weight 0..1}          e.g. "christmas", "haunted house"
    languages {ISO code: weight 0..1}              e.g. Indian languages for Diwali
    series    weight 0..1                          boost for TV series
    franchise weight 0..1                          boost for films in a collection
    max_age   age bucket cap (HARD filter)         only for kid/family occasions
    reason    text shown on the card when this rule is the main reason

Everything here is a hand-written heuristic: easy to read, easy to tune.
"""
import numpy as np

from app.vocab import (
    AGE_RATINGS, ARCS, EMOTION_LABELS, EMOTION_VALENCE, EMOTIONS, FESTIVAL_INFO, GENRES, MOOD_TAGS,
    OCCASION_INFO, TIME_OF_DAY_WORDS, INDIAN_LANGUAGES,
)

# ------------------------------------------------------------------------------------------ weather
WEATHER_RULES = {
    # Grey, wet days: people want comfort. Cosy, feel-good, romance and drama.
    "rainy": {
        "genres": {"Romance": 1.0, "Drama": 0.9, "Comedy": 0.7, "Animation": 0.5, "Musical": 0.5},
        "moods": {"cozy": 1.0, "feel-good": 0.9, "romantic": 0.9, "heartwarming": 0.8, "melancholic": 0.5},
        "keywords": {"rain": 1.0, "monsoon": 1.0},
    },
    # Thunder and lightning: lean into the atmosphere - thrillers, horror, mind-benders.
    "stormy": {
        "genres": {"Thriller": 1.0, "Horror": 0.9, "Mystery": 0.9, "Sci-Fi": 0.6},
        "moods": {"thrilling": 1.0, "scary": 0.9, "mind-bending": 0.9, "dark": 0.8},
        "keywords": {"storm": 1.0, "haunted house": 0.6},
    },
    # Snow outside: warm, family, a bit magical.
    "snowy": {
        "genres": {"Fantasy": 0.9, "Animation": 0.9, "Children": 0.7, "Romance": 0.6, "Drama": 0.5},
        "moods": {"cozy": 1.0, "heartwarming": 1.0, "family": 0.8, "feel-good": 0.8},
        "keywords": {"snow": 1.0, "christmas": 0.7, "winter": 1.0},
    },
    # Cold (but dry): comfort viewing again - cosy dramas and romances.
    "cold": {
        "genres": {"Drama": 0.9, "Romance": 0.9, "Comedy": 0.6, "Fantasy": 0.5},
        "moods": {"cozy": 1.0, "heartwarming": 0.9, "feel-good": 0.7, "romantic": 0.7},
        "keywords": {"winter": 0.8},
    },
    # Bright and sunny: energy! Adventure, comedy, big fun films.
    "sunny": {
        "genres": {"Adventure": 1.0, "Comedy": 0.9, "Action": 0.8, "Animation": 0.6},
        "moods": {"feel-good": 1.0, "light": 0.9, "funny": 0.9, "epic": 0.7, "action-packed": 0.7},
        "keywords": {"summer": 1.0, "road trip": 0.8, "beach": 0.8},
    },
    # Too hot to move: light, easy, funny films (and cool escapes).
    "hot": {
        "genres": {"Comedy": 1.0, "Animation": 0.8, "Adventure": 0.7, "Romance": 0.5},
        "moods": {"light": 1.0, "funny": 0.9, "feel-good": 0.9},
        "keywords": {"beach": 1.0, "summer": 0.9, "ocean": 0.7},
    },
    # Overcast: reflective - dramas, mysteries, slow-burners.
    "cloudy": {
        "genres": {"Drama": 0.9, "Mystery": 0.8, "Crime": 0.6, "Romance": 0.5},
        "moods": {"slow-burn": 0.9, "melancholic": 0.8, "mind-bending": 0.7, "cozy": 0.6},
        "keywords": {},
    },
    # Foggy and eerie: mysteries, thrillers, a little horror.
    "foggy": {
        "genres": {"Mystery": 1.0, "Thriller": 0.9, "Horror": 0.7, "Film-Noir": 0.7},
        "moods": {"dark": 0.9, "mind-bending": 0.9, "slow-burn": 0.8, "scary": 0.6},
        "keywords": {"fog": 1.0},
    },
}
WEATHER_ADJECTIVE = {"rainy": "rainy", "stormy": "stormy", "snowy": "snowy", "cold": "chilly",
                     "sunny": "sunny", "hot": "hot", "cloudy": "cloudy", "foggy": "foggy"}

# ------------------------------------------------------------------------------------------ time of day
TIME_RULES = {
    # Mornings: light, positive, easy to start the day with.
    "morning": {"genres": {"Animation": 0.8, "Comedy": 0.8, "Documentary": 0.8, "Children": 0.6},
                "moods": {"light": 1.0, "feel-good": 0.9, "inspiring": 0.8}},
    # Afternoons: big fun films - adventure and action.
    "afternoon": {"genres": {"Adventure": 1.0, "Action": 0.8, "Comedy": 0.8, "Fantasy": 0.6},
                  "moods": {"epic": 0.8, "action-packed": 0.8, "feel-good": 0.7}},
    # Evenings: prime time - drama, romance, crime stories.
    "evening": {"genres": {"Drama": 0.9, "Romance": 0.8, "Crime": 0.8, "Comedy": 0.6},
                "moods": {"heartwarming": 0.7, "romantic": 0.7, "thrilling": 0.6}},
    # Night: more intense - thrillers, crime, sci-fi.
    "night": {"genres": {"Thriller": 1.0, "Crime": 0.8, "Sci-Fi": 0.8, "Mystery": 0.8},
              "moods": {"thrilling": 1.0, "mind-bending": 0.8, "dark": 0.6}},
    # Late night: horror, thrillers and mind-bending stuff.
    "late_night": {"genres": {"Horror": 1.0, "Thriller": 0.9, "Mystery": 0.9, "Sci-Fi": 0.6},
                   "moods": {"scary": 1.0, "mind-bending": 0.9, "dark": 0.9, "thrilling": 0.8}},
}

# ------------------------------------------------------------------------------------------ occasions
OCCASION_RULES = {
    # Date night: romance, comedy, feel-good - nothing too heavy.
    "date_night": {"genres": {"Romance": 1.0, "Comedy": 0.8, "Drama": 0.5, "Musical": 0.5},
                   "moods": {"romantic": 1.0, "feel-good": 0.8, "funny": 0.6, "heartwarming": 0.7},
                   "keywords": {"love": 0.6}},
    # Family night: something everyone can watch -> cap at UA 13+.
    "family_night": {"genres": {"Animation": 1.0, "Children": 0.9, "Adventure": 0.8, "Comedy": 0.8, "Fantasy": 0.7},
                     "moods": {"family": 1.0, "heartwarming": 0.9, "feel-good": 0.8},
                     "max_age": "UA 13+"},
    # Friends: loud, funny or scary - things to react to together.
    "friends_hangout": {"genres": {"Comedy": 1.0, "Action": 0.8, "Horror": 0.7, "Adventure": 0.6},
                        "moods": {"funny": 1.0, "action-packed": 0.8, "thrilling": 0.7, "scary": 0.5}},
    # Alone: room for slower, deeper films.
    "solo_chill": {"genres": {"Drama": 0.9, "Sci-Fi": 0.8, "Documentary": 0.7, "Mystery": 0.7},
                   "moods": {"slow-burn": 0.9, "mind-bending": 0.9, "melancholic": 0.7, "cozy": 0.6}},
    # Kids: animation / children's films only up to UA 7+.
    "kids_time": {"genres": {"Animation": 1.0, "Children": 1.0, "Musical": 0.6, "Fantasy": 0.6, "Comedy": 0.5},
                  "moods": {"family": 1.0, "funny": 0.8, "feel-good": 0.8, "light": 0.8},
                  "max_age": "UA 7+"},
    "late_night_thrills": {"genres": {"Horror": 1.0, "Thriller": 1.0, "Mystery": 0.8},
                           "moods": {"scary": 1.0, "thrilling": 1.0, "dark": 0.8, "mind-bending": 0.6}},
    # Staying in on a rainy day: comfort films plus something long to sink into.
    "rainy_day_in": {"genres": {"Drama": 0.8, "Romance": 0.8, "Comedy": 0.7, "Fantasy": 0.6},
                     "moods": {"cozy": 1.0, "feel-good": 0.8, "heartwarming": 0.8},
                     "series": 0.5},
    # Weekend binge: series and franchises you can keep watching.
    "weekend_binge": {"genres": {"Crime": 0.6, "Sci-Fi": 0.6, "Fantasy": 0.6, "Drama": 0.5},
                      "moods": {"epic": 0.8, "thrilling": 0.7},
                      "series": 1.0, "franchise": 0.7},
}

# ------------------------------------------------------------------------------------------ festivals
FESTIVAL_RULES = {
    # Diwali: family get-togethers, feel-good and Indian films.
    "diwali": {"genres": {"Drama": 0.7, "Comedy": 0.8, "Musical": 0.8, "Romance": 0.6},
               "moods": {"family": 1.0, "feel-good": 1.0, "heartwarming": 0.9},
               "languages": {lang: 1.0 for lang in INDIAN_LANGUAGES},
               "keywords": {"diwali": 1.0, "family": 0.6, "india": 0.6}},
    # Holi: colourful, fun, romantic.
    "holi": {"genres": {"Comedy": 1.0, "Romance": 0.9, "Musical": 0.9},
             "moods": {"feel-good": 1.0, "light": 0.9, "funny": 0.9, "romantic": 0.7},
             "languages": {lang: 0.9 for lang in INDIAN_LANGUAGES},
             "keywords": {"holi": 1.0}},
    "navratri": {"genres": {"Musical": 1.0, "Drama": 0.7, "Romance": 0.6},
                 "moods": {"family": 0.8, "feel-good": 0.8, "inspiring": 0.6},
                 "languages": {lang: 0.9 for lang in INDIAN_LANGUAGES},
                 "keywords": {"navratri": 1.0, "dance": 0.7, "goddess": 0.6}},
    "eid": {"genres": {"Drama": 0.8, "Romance": 0.7, "Comedy": 0.6},
            "moods": {"family": 1.0, "heartwarming": 1.0, "feel-good": 0.8},
            "keywords": {"eid": 1.0, "ramadan": 0.9}},
    # Christmas: family, heartwarming, a bit of magic.
    "christmas": {"genres": {"Comedy": 0.8, "Animation": 0.8, "Fantasy": 0.8, "Children": 0.7, "Romance": 0.6},
                  "moods": {"heartwarming": 1.0, "family": 1.0, "cozy": 0.9, "feel-good": 0.8},
                  "keywords": {"christmas": 1.0, "santa claus": 1.0, "holiday": 0.7, "snow": 0.5}},
    "new_year": {"genres": {"Comedy": 1.0, "Romance": 0.8},
                 "moods": {"feel-good": 1.0, "funny": 0.9, "inspiring": 0.8},
                 "keywords": {"new year's eve": 1.0, "party": 0.6}},
    # Halloween: horror and anything spooky.
    "halloween": {"genres": {"Horror": 1.0, "Thriller": 0.7, "Mystery": 0.7, "Fantasy": 0.4},
                  "moods": {"scary": 1.0, "dark": 0.8, "thrilling": 0.7},
                  "keywords": {"halloween": 1.0, "haunted house": 0.9, "ghost": 0.8, "witch": 0.8,
                               "vampire": 0.7, "zombie": 0.7}},
    "valentines": {"genres": {"Romance": 1.0, "Comedy": 0.6, "Drama": 0.5},
                   "moods": {"romantic": 1.0, "feel-good": 0.8, "heartwarming": 0.7},
                   "keywords": {"love": 0.8, "valentine's day": 1.0}},
    # Raksha Bandhan: sibling stories and family films.
    "raksha_bandhan": {"genres": {"Drama": 0.9, "Comedy": 0.6},
                       "moods": {"family": 1.0, "heartwarming": 1.0, "feel-good": 0.7},
                       "languages": {lang: 0.8 for lang in INDIAN_LANGUAGES},
                       "keywords": {"brother sister relationship": 1.0, "sibling relationship": 0.9}},
    # Independence Day: inspiring, patriotic, history.
    "independence_day": {"genres": {"War": 1.0, "Drama": 0.8, "Documentary": 0.5},
                         "moods": {"inspiring": 1.0, "epic": 0.8},
                         "languages": {lang: 0.8 for lang in INDIAN_LANGUAGES},
                         "keywords": {"patriotism": 1.0, "independence": 1.0, "freedom fighter": 1.0}},
    # Onam: Kerala's harvest festival -> family films, Malayalam cinema.
    "onam": {"genres": {"Comedy": 0.8, "Drama": 0.8},
             "moods": {"family": 1.0, "feel-good": 0.9, "heartwarming": 0.8},
             "languages": {"ml": 1.0, "ta": 0.4},
             "keywords": {"kerala": 1.0}},
    # Pongal: Tamil harvest festival -> family films, Tamil/Telugu cinema.
    "pongal": {"genres": {"Comedy": 0.8, "Drama": 0.8, "Action": 0.5},
               "moods": {"family": 1.0, "feel-good": 0.9},
               "languages": {"ta": 1.0, "te": 0.7},
               "keywords": {"village": 0.6, "farmer": 0.6}},
    "thanksgiving": {"genres": {"Comedy": 0.8, "Drama": 0.8},
                     "moods": {"family": 1.0, "heartwarming": 1.0, "cozy": 0.8},
                     "keywords": {"thanksgiving": 1.0, "family reunion": 0.9}},
}

# ------------------------------------------------------------------------------------------ home-row presets
# Some /api/home rows ("Trending now", "Critically acclaimed", "Hidden gems",
# "Mind-bending") cannot be described with the normal Context fields, so their
# `filter` carries {"preset": "..."} and /api/recommendations understands it.
PRESET_RULES = {
    "trending": {"label": "Trending now",
                 "weights": {"trend": 1.0, "quality": 0.15, "cf": 0.15, "content": 0.05, "behavior": 0.05}},
    "acclaimed": {"label": "Critically acclaimed",
                  "weights": {"quality": 1.0, "cf": 0.2, "content": 0.05, "trend": 0.0},
                  "min_quality_pct": 0.75},
    "hidden_gems": {"label": "Hidden gems",
                    "weights": {"quality": 0.8, "cf": 0.4, "trend": 0.0},
                    "min_quality_pct": 0.6, "max_popularity_pct": 0.5},
    "mind_bending": {"label": "Mind-bending",
                     "moods": {"mind-bending": 1.0, "dark": 0.4, "thrilling": 0.4},
                     "genres": {"Sci-Fi": 0.8, "Mystery": 0.8, "Thriller": 0.6}},
}

# How strongly each context signal counts inside the "ctx" component.
CTX_PART_WEIGHTS = {
    "genres": 1.5,        # the user explicitly picked genres -> strongest
    "emotion": 1.2,
    "occasion": 1.2,
    "preset": 1.2,
    "festival": 1.0,
    "weather": 1.0,
    "nostalgia": 1.0,
    "time_of_day": 0.5,   # weakest: everyone always has a time of day
    "content_type": 0.3,
}

# Every keyword any rule boosts (the model store indexes only these).
ALL_RULE_KEYWORDS = sorted({
    kw for table in (WEATHER_RULES, OCCASION_RULES, FESTIVAL_RULES)
    for rule in table.values() for kw in rule.get("keywords", {})
})


# ================================================================================== scoring helpers
def occasion_age_cap(occasion: str | None) -> str | None:
    rule = OCCASION_RULES.get(occasion or "")
    return rule.get("max_age") if rule else None


def stricter_age(a: str | None, b: str | None) -> str | None:
    """The lower of two age caps (None = no cap)."""
    if a is None:
        return b
    if b is None:
        return a
    return a if AGE_RATINGS.index(a) <= AGE_RATINGS.index(b) else b


def _best_weight(matrix: np.ndarray, vocab: list[str], weights: dict) -> np.ndarray:
    """For each item: the highest weight among the genres/moods it has (0 if none).
    Loops over the few weighted columns instead of building an [N, 19] float
    matrix (saves memory on big catalogs)."""
    best = np.zeros(matrix.shape[0], dtype=np.float32)
    for name, weight in weights.items():
        if name in vocab and weight > 0:
            column = matrix[:, vocab.index(name)]
            best[column] = np.maximum(best[column], weight)
    return best


def rule_match(state, rule: dict) -> np.ndarray:
    """How well every item fits one rule, 0..1 (vectorised over all items)."""
    parts = []  # (weight, array)
    if rule.get("genres"):
        parts.append((0.45, _best_weight(state.genre_matrix, GENRES, rule["genres"])))
    if rule.get("moods"):
        parts.append((0.40, _best_weight(state.mood_matrix, MOOD_TAGS, rule["moods"])))
    if rule.get("keywords"):
        kw = np.zeros(state.n, dtype=np.float32)
        for word, weight in rule["keywords"].items():
            rows = state.keyword_index.get(word.lower())
            if rows is not None:
                kw[rows] = np.maximum(kw[rows], weight)
        parts.append((0.20, kw))
    if rule.get("languages"):
        lookup = np.array([rule["languages"].get(code, 0.0) for code in state.lang_codes] + [0.0],
                          dtype=np.float32)
        parts.append((0.35, lookup[state.lang_idx]))   # lang_idx -1 -> last entry (0.0)
    if rule.get("series"):
        parts.append((0.30, state.is_series.astype(np.float32) * float(rule["series"])))
    if rule.get("franchise"):
        parts.append((0.20, state.in_collection.astype(np.float32) * float(rule["franchise"])))
    if not parts:
        return np.zeros(state.n, dtype=np.float32)
    total = sum(w for w, _ in parts)
    return (sum(w * arr for w, arr in parts) / total).astype(np.float32)


def emotion_match(state, start: str | None, end: str | None) -> np.ndarray:
    """Starting/ending emotion. Exact emotion = 1, same feeling direction
    (e.g. joy vs surprise) = 0.5. The END counts more than the start: people
    remember how a film leaves them. A matching emotional arc adds a bonus."""
    def one_side(item_idx: np.ndarray, wanted: str) -> np.ndarray:
        wanted_valence = EMOTION_VALENCE[wanted]
        valence = np.array([EMOTION_VALENCE[e] for e in EMOTIONS] + [99], dtype=np.int8)[item_idx]
        score = np.where(valence == wanted_valence, 0.5, 0.0).astype(np.float32)
        score[item_idx == EMOTIONS.index(wanted)] = 1.0
        return score

    parts = []
    if start:
        parts.append((0.35, one_side(state.start_emo_idx, start)))
    if end:
        parts.append((0.65, one_side(state.end_emo_idx, end)))
    score = sum(w * a for w, a in parts) / sum(w for w, _ in parts)
    if start and end:
        delta = EMOTION_VALENCE[end] - EMOTION_VALENCE[start]
        wanted_arcs = {"rise", "fall-rise"} if delta > 0 else {"fall", "rise-fall"} if delta < 0 else {"steady"}
        arc_ok = np.isin(state.arc_idx, [ARCS.index(a) for a in wanted_arcs])
        score = np.minimum(1.0, score + 0.15 * arc_ok)
    return score.astype(np.float32)


def nostalgia_match(state, decade: int) -> np.ndarray:
    """Gaussian on decade distance: same decade 1.0, next decade 0.61, two away 0.14."""
    distance = (state.decade - float(decade)) / 10.0
    score = np.exp(-0.5 * distance ** 2)
    return np.nan_to_num(score, nan=0.0).astype(np.float32)


def genre_choice_match(state, genres: list[str]) -> np.ndarray:
    """Items with any chosen genre get 0.6, plus up to 0.4 for matching more of them."""
    cols = [GENRES.index(g) for g in genres if g in GENRES]
    if not cols:
        return np.zeros(state.n, dtype=np.float32)
    hits = state.genre_matrix[:, cols].sum(axis=1).astype(np.float32)
    return np.where(hits > 0, 0.6 + 0.4 * hits / len(cols), 0.0).astype(np.float32)


class CtxPart:
    """One context signal: its weight, per-item match (0..1) and a reason builder."""

    def __init__(self, key: str, values: np.ndarray, reason):
        self.key = key
        self.weight = CTX_PART_WEIGHTS[key]
        self.values = values
        self.reason = reason   # function(state, i) -> str


def context_parts(state, ctx: dict) -> list[CtxPart]:
    """Build every soft context signal present in `ctx`."""
    parts: list[CtxPart] = []
    tod = ctx.get("time_of_day")
    tod_word = TIME_OF_DAY_WORDS.get(tod, "day")

    if ctx.get("genres"):
        chosen = ctx["genres"]
        def genre_reason(st, i, chosen=chosen):
            mine = [g for g in chosen if st.genre_matrix[i, GENRES.index(g)]]
            return f"Matches your pick: {mine[0] if mine else chosen[0]}"
        parts.append(CtxPart("genres", genre_choice_match(state, chosen), genre_reason))

    if ctx.get("start_emotion") or ctx.get("end_emotion"):
        def emotion_reason(st, i):
            start = EMOTION_LABELS.get(st.start_emotion[i])
            end = EMOTION_LABELS.get(st.end_emotion[i])
            if start and end:
                return f"Starts {start.lower()}, ends {end.lower()}"
            return f"Leaves you {end.lower()}" if end else "Fits the mood you picked"
        parts.append(CtxPart("emotion", emotion_match(state, ctx.get("start_emotion"), ctx.get("end_emotion")),
                             emotion_reason))

    if ctx.get("occasion") in OCCASION_RULES:
        label = OCCASION_INFO[ctx["occasion"]][0]
        parts.append(CtxPart("occasion", rule_match(state, OCCASION_RULES[ctx["occasion"]]),
                             lambda st, i, label=label: f"Great for {label.lower()}"))

    if ctx.get("preset") in PRESET_RULES and (PRESET_RULES[ctx["preset"]].get("moods")
                                              or PRESET_RULES[ctx["preset"]].get("genres")):
        label = PRESET_RULES[ctx["preset"]]["label"]
        parts.append(CtxPart("preset", rule_match(state, PRESET_RULES[ctx["preset"]]),
                             lambda st, i, label=label: f"{label} pick"))

    if ctx.get("festival") in FESTIVAL_RULES:
        label = FESTIVAL_INFO[ctx["festival"]][0]
        parts.append(CtxPart("festival", rule_match(state, FESTIVAL_RULES[ctx["festival"]]),
                             lambda st, i, label=label: f"Perfect for {label}"))

    if ctx.get("weather") in WEATHER_RULES:
        adjective = WEATHER_ADJECTIVE[ctx["weather"]]
        parts.append(CtxPart("weather", rule_match(state, WEATHER_RULES[ctx["weather"]]),
                             lambda st, i, a=adjective, t=tod_word: f"Perfect for a {a} {t}"))

    if ctx.get("nostalgia_decade"):
        decade = int(ctx["nostalgia_decade"])
        parts.append(CtxPart("nostalgia", nostalgia_match(state, decade),
                             lambda st, i, d=decade: f"A trip back to the {str(d)[2:]}s"))

    if tod in TIME_RULES:
        parts.append(CtxPart("time_of_day", rule_match(state, TIME_RULES[tod]),
                             lambda st, i, t=tod_word: f"Great for a {t} watch"))

    if ctx.get("content_type") in ("movie", "series"):
        is_match = state.is_series if ctx["content_type"] == "series" else ~state.is_series
        parts.append(CtxPart("content_type", is_match.astype(np.float32),
                             lambda st, i: "Matches what you picked"))
    return parts


def combine_parts(parts: list[CtxPart]) -> np.ndarray | None:
    """Weighted average of the context signals (None if there are none)."""
    if not parts:
        return None
    total = sum(p.weight for p in parts)
    return (sum(p.weight * p.values for p in parts) / total).astype(np.float32)
