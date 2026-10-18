"""
step6_emotion_arcs.py - how does each story START and END emotionally?

For every title we estimate start_emotion, end_emotion and emotion_arc (CONTRACT vocabularies):
    EMOTIONS = joy, sadness, fear, anger, surprise, disgust, neutral
    ARCS     = rise, fall, fall-rise, rise-fall, steady
This powers filters like "start sad -> end happy" in the Mood Mixer.

How the plot is split
    3+ sentences  -> first third / middle third / last third of the sentences
    1-2 sentences -> first vs last sentence (a single sentence is split at a clause such as
                     ", but", " until ", " and " near its middle), no middle part
Polarity: joy/surprise = +1, sadness/fear/anger/disgust = -1, neutral = 0
Arc     : end more positive than start -> rise; less positive -> fall; same polarity -> steady,
          unless a middle part exists and dips below (fall-rise) or rises above (rise-fall).

Two engines (chosen automatically):
  1. transformers + torch installed (requirements-extra.txt): the pretrained classifier
     j-hartmann/emotion-english-distilroberta-base (its 7 labels are exactly our EMOTIONS).
     Batched; ~20-40 min on a laptop CPU for 30k titles, ~2-4 min on a Colab GPU.
  2. otherwise: a small, transparent keyword lexicon written for this project + genre hints.
     Runs in seconds.
Note: plot summaries rarely give away the ending, so the END estimate also leans a little on
how stories of that genre usually resolve (comedies tend to end happily, horror in fear).

Output: data/processed/emotions.parquet (movie_id, start_emotion, end_emotion, emotion_arc,
        emotion_mood_tags) + emotion_info.json. step9 merges these into catalog.csv.
"""
from __future__ import annotations

import argparse
import re
import time

import numpy as np
import pandas as pd

import config
from utils import banner, fail, join_list, log, save_json, split_list, warn

HF_MODEL = "j-hartmann/emotion-english-distilroberta-base"
LEXICON_NAME = "keyword-lexicon-v1 (fallback)"
EMOTIONS = config.EMOTIONS                       # ["joy","sadness","fear","anger","surprise","disgust","neutral"]
POLARITY = {e: (1 if e in config.POSITIVE_EMOTIONS else -1 if e in config.NEGATIVE_EMOTIONS else 0) for e in EMOTIONS}

# ----------------------------------------------------------------------------------------------
# Fallback lexicon - our own small word lists (base forms; a tiny stemmer handles kills/killed/...)
# ----------------------------------------------------------------------------------------------
LEXICON = {
    "joy": """love loving happy happiness joy celebrate celebration wedding fun laugh laughter delight cheer
        cheerful hope hopeful win victory triumph success succeed reunite reunion friendship together free
        freedom magic magical wonder wonderful warm kind kindness gentle charming playful sweet bright
        festival holiday party dance sing music smile heal peace perfect colourful colorful gift heart
        romance sweetheart champion inspire embrace dream joyful glorious best grow bond unlikely""",
    "sadness": """death die dead dying grief grieve loss lose lost tragic tragedy alone lonely loneliness mourn
        illness ill cancer terminal widow widower funeral poverty poor heartbroken heartbreak sacrifice
        divorce orphan regret struggle despair suffering failure fail broken abandon exile farewell goodbye
        tear sorrow melancholy separate separation drought hardship debt unhappy sick wound memory
        bittersweet behind miss grieving sad doomed dies passed""",
    "fear": """kill killer murder murderer monster ghost haunt terror terrify terrifying hunt escape danger
        dangerous threat threaten demon survive survival trap trapped nightmare creature serial kidnap chase
        horror deadly sinister evil curse cursed shadow stalker stalk panic scream attack infected outbreak
        zombie possession possessed bomb hostage disappear vanish predator prey unstoppable relentless
        afraid fear risk desperate paranoia paranoid assassin hitman spiral dread menace lurk""",
    "anger": """revenge avenge vengeance betray betrayal corrupt corruption injustice rage fight war rival rivalry
        brutal oppress oppression rebel rebellion gang gangster feud violent violence battle enemy tyrant
        ruthless crime criminal clash conflict defy defiant uprising mob mafia abuse abusive bully cruel
        greed greedy wrongly framed accuse hate hatred furious confront destroy invasion invade siege
        vigilante warlord bloody tormented raid dominate""",
    "surprise": """discover discovery secret mystery mysterious twist unexpected sudden suddenly strange stranger
        reveal revelation hidden unknown bizarre impossible shock shocking uncover puzzle riddle alien
        otherworldly astonish learn realise realize truth identity mistaken accidentally accident chance
        coincidence find stumble suspicious enigmatic legend legendary uncanny wake""",
    "disgust": """gore gory cannibal depraved sleazy filth filthy grotesque toxic rot rotting disgusting perverse
        sadistic decay vile repulsive excess sleaze degenerate mutate mutated mutant parasite poison
        poisoned slime vomit fraud con scam swindle exploit""",
}
WORD_TO_EMOTION = {w: e for e, words in LEXICON.items() for w in words.split()}

# How each genre colours a story (weights per emotion)
GENRE_TONE = {
    "Comedy": {"joy": 1.0}, "Romance": {"joy": 0.8, "sadness": 0.2}, "Animation": {"joy": 0.6, "surprise": 0.2},
    "Children": {"joy": 0.9}, "Musical": {"joy": 0.8}, "Horror": {"fear": 1.2, "disgust": 0.3},
    "Thriller": {"fear": 0.8, "surprise": 0.3}, "Crime": {"anger": 0.6, "fear": 0.3}, "Drama": {"sadness": 0.5},
    "War": {"sadness": 0.6, "anger": 0.5, "fear": 0.3}, "Mystery": {"surprise": 0.8, "fear": 0.2},
    "Sci-Fi": {"surprise": 0.6}, "Fantasy": {"surprise": 0.4, "joy": 0.3}, "Adventure": {"joy": 0.4, "surprise": 0.4},
    "Action": {"anger": 0.5, "fear": 0.2}, "Film-Noir": {"fear": 0.4, "anger": 0.3}, "Western": {"anger": 0.5},
}
# How stories of a genre usually END
GENRE_ENDING = {
    "Comedy": {"joy": 0.7}, "Romance": {"joy": 0.6}, "Children": {"joy": 0.8}, "Animation": {"joy": 0.7},
    "Musical": {"joy": 0.6}, "Adventure": {"joy": 0.4}, "Fantasy": {"joy": 0.3}, "Horror": {"fear": 0.7},
    "War": {"sadness": 0.5}, "Drama": {"sadness": 0.2, "joy": 0.2}, "Thriller": {"surprise": 0.3},
    "Mystery": {"surprise": 0.4}, "Crime": {"anger": 0.2},
}
NEUTRAL_BASELINE = 0.6           # lexicon: a segment needs more evidence than this to get an emotion
SPLIT_WORDS = re.compile(r",\s+(?:but|until|only to|before|when|while|and|as)\s+|\s+(?:but|until|only to)\s+|;\s+|,\s+")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])")


def split_segments(text: str) -> tuple[str, str | None, str]:
    """(start, middle or None, end) parts of an overview."""
    text = " ".join(str(text or "").split())
    if not text:
        return "", None, ""
    sentences = [s for s in SENTENCE_END.split(text) if s.strip()]
    if len(sentences) >= 3:
        third = max(1, round(len(sentences) / 3))
        return (" ".join(sentences[:third]), " ".join(sentences[third:-third]) or None,
                " ".join(sentences[-third:]))
    if len(sentences) == 2:
        return sentences[0], None, sentences[1]
    # One sentence: split at the clause boundary closest to the middle
    cuts = [m for m in SPLIT_WORDS.finditer(text) if 15 < m.start() < len(text) - 15]
    if not cuts:
        return text, None, text
    cut = min(cuts, key=lambda m: abs(m.start() - len(text) / 2))
    return text[: cut.start()], None, text[cut.end():]


def _stems(word: str):
    yield word
    for suffix in ("ies", "ied"):
        if word.endswith(suffix):
            yield word[: -len(suffix)] + "y"
    for suffix in ("ing", "ed", "es", "s", "ly", "er", "ness", "ful"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            base = word[: -len(suffix)]
            yield base
            yield base + "e"                      # "escaped" -> "escap" -> "escape"
            if len(base) > 3 and base[-1] == base[-2]:
                yield base[:-1]                   # "running" -> "runn" -> "run"


def lexicon_scores(text: str) -> np.ndarray:
    scores = np.zeros(len(EMOTIONS))
    for word in re.findall(r"[a-z]+", text.lower()):
        for stem in _stems(word):
            emotion = WORD_TO_EMOTION.get(stem)
            if emotion:
                scores[EMOTIONS.index(emotion)] += 1.0
                break
    return scores


def genre_vector(genres: list[str], table: dict) -> np.ndarray:
    vec = np.zeros(len(EMOTIONS))
    for g in genres:
        for emotion, weight in table.get(g, {}).items():
            vec[EMOTIONS.index(emotion)] += weight
    return vec / max(1, len(genres)) * 1.5


def label_from_scores(scores: np.ndarray) -> str:
    """Strongest emotion, or neutral when the evidence is weak."""
    scores = scores.copy()
    scores[EMOTIONS.index("neutral")] = max(scores[EMOTIONS.index("neutral")], NEUTRAL_BASELINE)
    return EMOTIONS[int(np.argmax(scores))]


def label_from_probs(probs: np.ndarray) -> str:
    """Model probabilities -> label. Plot summaries read 'neutral' a lot, so a clear runner-up
    emotion (>= 0.25) wins over neutral."""
    best = int(np.argmax(probs))
    if EMOTIONS[best] == "neutral":
        others = probs.copy()
        others[best] = -1
        if others.max() >= 0.25:
            best = int(np.argmax(others))
    return EMOTIONS[best]


def arc_for(start: str, end: str, middle: str | None) -> str:
    s, e = POLARITY[start], POLARITY[end]
    if e > s:
        return "rise"
    if e < s:
        return "fall"
    if middle is not None:
        m = POLARITY[middle]
        if m < s:
            return "fall-rise"
        if m > s:
            return "rise-fall"
    return "steady"


def emotion_mood_tags(start: str, end: str, arc: str, genres: list[str]) -> str:
    """Extra mood tags implied by the emotions (step9 merges them with step4's base tags)."""
    tags = set()
    if end == "joy" and "Horror" not in genres:
        tags.add("feel-good")
    if arc in ("rise", "fall-rise") and end == "joy":
        tags.add("heartwarming")
    if end == "sadness":
        tags.add("melancholic")
    tense_genres = {"Thriller", "Horror", "Crime", "Mystery", "Action", "Sci-Fi", "War"}
    if "fear" in (start, end) and tense_genres & set(genres):      # not for a scary moment in a kids' film
        tags.add("scary" if "Horror" in genres else "thrilling")
    if end in ("anger", "disgust"):
        tags.add("dark")
    return join_list(t for t in config.MOOD_TAGS if t in tags)


# ----------------------------------------------------------------------------------------------
# Engines
# ----------------------------------------------------------------------------------------------
def run_lexicon(segments, genres_list):
    labels = []
    for (start, middle, end), genres in zip(segments, genres_list):
        tone, ending = genre_vector(genres, GENRE_TONE), genre_vector(genres, GENRE_ENDING)
        s = label_from_scores(lexicon_scores(start) + 0.35 * tone)
        m = label_from_scores(lexicon_scores(middle) + 0.35 * tone) if middle else None
        e = label_from_scores(lexicon_scores(end) + 0.5 * tone + ending)
        labels.append((s, m, e))
    return labels


def run_transformer(segments, genres_list):
    import torch
    from transformers import pipeline

    device = 0 if torch.cuda.is_available() else -1
    texts, index = [], []                         # flatten every non-empty segment into one batch list
    for row, (start, middle, end) in enumerate(segments):
        for part, text in (("start", start), ("middle", middle), ("end", end)):
            if text:
                texts.append(text)
                index.append((row, part))
    log(f"{HF_MODEL} on {'GPU' if device == 0 else 'CPU'}: {len(texts):,} segments "
        f"(estimated {len(texts) / (400 if device == 0 else 25) / 60:.1f} min)")
    classifier = pipeline("text-classification", model=HF_MODEL, top_k=None, truncation=True,
                          max_length=256, device=device)
    order = np.argsort([len(t) for t in texts])   # similar lengths together = less padding = faster
    probs = np.zeros((len(texts), len(EMOTIONS)), dtype=np.float32)
    chunk = 2048
    for begin in range(0, len(order), chunk):
        ids = order[begin:begin + chunk]
        outputs = classifier([texts[i] for i in ids], batch_size=32)
        for i, out in zip(ids, outputs):
            for item in out:
                if item["label"] in EMOTIONS:
                    probs[i, EMOTIONS.index(item["label"])] = item["score"]
        log(f"  classified {min(begin + chunk, len(order)):,}/{len(order):,} segments")

    per_row: dict[int, dict[str, np.ndarray]] = {}
    for (row, part), p in zip(index, probs):
        per_row.setdefault(row, {})[part] = p
    labels = []
    for row, genres in enumerate(genres_list):
        parts = per_row.get(row, {})
        tone = genre_vector(genres, GENRE_TONE)
        ending = genre_vector(genres, GENRE_ENDING)
        prior_start = tone / tone.sum() if tone.sum() else None
        prior_end = (tone + ending) / (tone + ending).sum() if (tone + ending).sum() else None
        if "start" in parts:
            p = parts["start"] if prior_start is None else 0.9 * parts["start"] + 0.1 * prior_start
            s = label_from_probs(p)
        else:
            s = label_from_scores(0.35 * tone)
        m = label_from_probs(parts["middle"]) if "middle" in parts else None
        if "end" in parts:
            p = parts["end"] if prior_end is None else 0.75 * parts["end"] + 0.25 * prior_end
            e = label_from_probs(p)
        else:
            e = label_from_scores(0.5 * tone + ending)
        labels.append((s, m, e))
    return labels


def main(argv=None):
    parser = argparse.ArgumentParser(description="Step 6 - emotional start/end and arc of each plot")
    parser.add_argument("--sample", action="store_true", help="use the demo-data folders")
    parser.add_argument("--lexicon", action="store_true", help="force the keyword-lexicon fallback")
    args = parser.parse_args(argv)

    banner("Step 6/9 - Emotion arcs")
    start_time = time.time()
    out_dir = config.processed_dir(args.sample)
    path = out_dir / "catalog_base.parquet"
    if not path.exists():
        fail(f"{path} not found -> run step4_build_catalog.py first")
    cat = pd.read_parquet(path, columns=["movie_id", "title", "overview", "genres"])
    segments = [split_segments(t) for t in cat["overview"].fillna("")]
    genres_list = [split_list(g) for g in cat["genres"]]
    log(f"{len(cat):,} titles; {sum(1 for s in segments if s[1]):,} have a 3-part plot (middle segment)")

    labels, engine = None, LEXICON_NAME
    if not args.lexicon:
        try:
            labels, engine = run_transformer(segments, genres_list), HF_MODEL
        except ImportError:
            log("transformers/torch not installed -> using the keyword-lexicon fallback "
                "(pip install -r requirements-extra.txt for the neural model)")
        except Exception as error:
            warn(f"emotion model failed ({error}) -> using the keyword-lexicon fallback")
    if labels is None:
        labels = run_lexicon(segments, genres_list)

    rows = []
    for movie_id, (s, m, e), genres in zip(cat["movie_id"], labels, genres_list):
        arc = arc_for(s, e, m)
        rows.append({"movie_id": int(movie_id), "start_emotion": s, "end_emotion": e, "emotion_arc": arc,
                     "emotion_mood_tags": emotion_mood_tags(s, e, arc, genres)})
    out = pd.DataFrame(rows)
    out.to_parquet(out_dir / "emotions.parquet", index=False)
    save_json(out_dir / "emotion_info.json", {"model": engine, "n_items": int(len(out))})

    log("start: " + ", ".join(f"{k} {v}" for k, v in out["start_emotion"].value_counts().items()))
    log("end  : " + ", ".join(f"{k} {v}" for k, v in out["end_emotion"].value_counts().items()))
    log("arcs : " + ", ".join(f"{k} {v}" for k, v in out["emotion_arc"].value_counts().items()))
    log(f"Saved {out_dir / 'emotions.parquet'} ({engine}) in {time.time() - start_time:.1f}s")


if __name__ == "__main__":
    main()
