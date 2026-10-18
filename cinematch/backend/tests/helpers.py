"""Small helpers shared by the tests."""
from app.vocab import GENRES


def rate_many(client, headers, pairs):
    for movie_id, value in pairs:
        r = client.post("/api/ratings", json={"movie_id": movie_id, "rating": value}, headers=headers)
        assert r.status_code == 200, r.text


def ids_with_genre(state, genre, limit=10, movies_only=True):
    """Catalog movie ids that have `genre` (helper for building tastes)."""
    col = GENRES.index(genre)
    out = []
    for i in range(state.n):
        if state.genre_matrix[i, col] and (not movies_only or not state.is_series[i]) and state.has_cf[i]:
            out.append(int(state.movie_ids[i]))
        if len(out) >= limit:
            break
    return out
