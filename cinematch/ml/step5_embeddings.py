"""
step5_embeddings.py - turn each title's text into a vector, so "similar" titles are close together.

Content text = title + genres + keywords + directors + franchise + overview (+ MovieLens user tags).

Two ways to make the vectors (chosen automatically):
  1. sentence-transformers installed (pip install -r requirements-extra.txt):
       model all-MiniLM-L6-v2 -> 384 numbers per title. Understands meaning ("space" ~ "galaxy").
       ~5-10 min on a laptop CPU for 30k titles, ~1 min on a Colab GPU.
  2. otherwise (default, no extra install): TF-IDF word weights + TruncatedSVD (also called LSA)
       -> 128 numbers per title. Fast (< 1 min) and good at shared keywords/genres/people.
Every vector is L2-normalised (length 1), so cosine similarity = a simple dot product, and it is
saved as float16 to halve the file size (the backend has only 512 MB RAM).

Output: data/processed/plot_emb.npy (float16 [N, d]), plot_emb_ids.npy (movie_id per row),
        has_emb.npy (bool [N]), embedding_info.json (which model was used)
Options: --tfidf forces the fallback even if sentence-transformers is installed.
"""
from __future__ import annotations

import argparse
import time

import numpy as np
import pandas as pd

import config
from utils import banner, fail, log, save_json, split_list, warn

ST_MODEL = "all-MiniLM-L6-v2"
TFIDF_DIM = 128


def build_texts(cat: pd.DataFrame, for_tfidf: bool) -> tuple[list[str], np.ndarray]:
    """One text per title + a flag saying whether there was anything to describe it."""
    texts, has_text = [], []
    for row in cat.itertuples(index=False):
        genres = split_list(row.genres)
        keywords = split_list(row.keywords) + split_list(row.ml_tags)
        directors = split_list(row.directors)
        overview = row.overview or ""
        has_text.append(bool(overview or keywords or genres))
        if for_tfidf:
            # Names become single tokens ("christopher_nolan") so a director matches as one word;
            # genres and keywords are repeated to give them a bit more weight than plot words.
            people = " ".join(d.lower().replace(" ", "_").replace(".", "") for d in directors)
            franchise = row.collection_name.lower().replace(" collection", "").replace(" ", "_")
            text = " ".join([row.title, " ".join(genres) * 2, " ".join(keywords) * 2, people, franchise, overview])
        else:
            parts = [f"{row.title}."]
            if genres:
                parts.append(f"Genres: {', '.join(genres)}.")
            if keywords:
                parts.append(f"Keywords: {', '.join(keywords[:15])}.")
            if directors:
                parts.append(f"Directed by {', '.join(directors[:3])}.")
            if row.collection_name:
                parts.append(f"Part of {row.collection_name}.")
            parts.append(overview)
            text = " ".join(parts)
        texts.append(text)
    return texts, np.array(has_text, dtype=bool)


def embed_sentence_transformers(cat: pd.DataFrame):
    from sentence_transformers import SentenceTransformer      # only exists with requirements-extra.txt
    import torch

    device = "cuda" if torch.cuda.is_available() else "cpu"
    texts, has_text = build_texts(cat, for_tfidf=False)
    log(f"sentence-transformers on {device}: encoding {len(texts):,} texts "
        f"(estimated {len(texts) / (900 if device == 'cuda' else 80) / 60:.1f} min)")
    model = SentenceTransformer(f"sentence-transformers/{ST_MODEL}", device=device)
    emb = model.encode(texts, batch_size=64, show_progress_bar=True,
                       normalize_embeddings=True, convert_to_numpy=True)
    return emb.astype(np.float32), has_text, ST_MODEL


def embed_tfidf(cat: pd.DataFrame):
    from sklearn.decomposition import TruncatedSVD
    from sklearn.feature_extraction.text import TfidfVectorizer

    texts, has_text = build_texts(cat, for_tfidf=True)
    log(f"TF-IDF + TruncatedSVD on {len(texts):,} texts")
    vectorizer = TfidfVectorizer(max_features=50_000, ngram_range=(1, 2), sublinear_tf=True,
                                 stop_words="english", min_df=2 if len(texts) > 2000 else 1)
    matrix = vectorizer.fit_transform(texts)
    dim = max(2, min(TFIDF_DIM, matrix.shape[0] - 1, matrix.shape[1] - 1))
    svd = TruncatedSVD(n_components=dim, random_state=config.SEED)
    emb = svd.fit_transform(matrix)
    log(f"Vocabulary {matrix.shape[1]:,} terms -> {dim} dimensions "
        f"(explains {svd.explained_variance_ratio_.sum() * 100:.0f}% of the variance)")
    return emb.astype(np.float32), has_text, f"tfidf-svd-{dim}"


def main(argv=None):
    parser = argparse.ArgumentParser(description="Step 5 - content embeddings")
    parser.add_argument("--sample", action="store_true", help="use the demo-data folders")
    parser.add_argument("--tfidf", action="store_true", help="force the TF-IDF fallback")
    args = parser.parse_args(argv)

    banner("Step 5/9 - Content embeddings")
    start = time.time()
    out_dir = config.processed_dir(args.sample)
    path = out_dir / "catalog_base.parquet"
    if not path.exists():
        fail(f"{path} not found -> run step4_build_catalog.py first")
    cat = pd.read_parquet(path)
    for col in ("title", "genres", "keywords", "ml_tags", "directors", "collection_name", "overview"):
        cat[col] = cat[col].fillna("").astype(str) if col in cat.columns else ""

    emb = None
    if not args.tfidf:
        try:
            emb, has_text, model_name = embed_sentence_transformers(cat)
        except ImportError:
            log("sentence-transformers not installed -> using the TF-IDF fallback "
                "(pip install -r requirements-extra.txt for the neural model)")
        except Exception as error:               # e.g. no internet to download the model
            warn(f"sentence-transformers failed ({error}) -> using the TF-IDF fallback")
    if emb is None:
        emb, has_text, model_name = embed_tfidf(cat)

    # L2-normalise (length 1) and zero out titles with no text at all
    norms = np.linalg.norm(emb, axis=1, keepdims=True)
    emb = np.where(norms > 0, emb / np.maximum(norms, 1e-12), 0.0)
    has_emb = has_text & (norms[:, 0] > 0)
    emb[~has_emb] = 0.0

    np.save(out_dir / "plot_emb.npy", emb.astype(np.float16))
    np.save(out_dir / "plot_emb_ids.npy", cat["movie_id"].to_numpy(dtype=np.int64))
    np.save(out_dir / "has_emb.npy", has_emb)
    save_json(out_dir / "embedding_info.json", {
        "model": model_name, "dim": int(emb.shape[1]), "n_items": int(len(cat)),
        "n_with_embedding": int(has_emb.sum()),
    })

    # Quick sanity check: nearest neighbours of a well-known title
    probe = cat.index[cat["title"].str.contains("Inception|Toy Story|3 Idiots", regex=True)]
    if len(probe):
        i = int(probe[0])
        sims = emb @ emb[i]
        nearest = [cat["title"].iat[j] for j in np.argsort(-sims)[1:6]]
        log(f"Most similar to '{cat['title'].iat[i]}': {', '.join(nearest)}")
    log(f"Saved {emb.shape[0]:,} x {emb.shape[1]} embeddings ({model_name}) in {time.time() - start:.1f}s")


if __name__ == "__main__":
    main()
