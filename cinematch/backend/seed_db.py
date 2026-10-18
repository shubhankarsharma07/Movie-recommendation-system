"""
Load catalog.csv of the CURRENT artifact version into the `movies` table.

The API does this automatically on startup (and after a hot reload) whenever
the version changed, so you normally don't need this script. It is handy to
prepare a fresh production database before the first deploy:

    cd backend
    python seed_db.py            # only if the version changed / table is empty
    python seed_db.py --force    # upsert every row again
"""
import argparse
import sys

from app.config import settings
from app.database import init_db
from app.services.catalog_sync import sync_movies
from app.services.model_store import load_state, store


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy catalog.csv into the movies table")
    parser.add_argument("--force", action="store_true", help="upsert even if this version was already loaded")
    args = parser.parse_args()

    version = store.read_current_version()
    if not version:
        print(f"No current.txt found in {settings.artifacts_dir}", file=sys.stderr)
        return 1
    init_db()
    state = load_state(settings.artifacts_dir, version, catalog_only=True)   # CSV only, no .npy needed
    written = sync_movies(state, force=args.force)
    if written:
        print(f"movies table: upserted {written} rows from {version}")
    else:
        print(f"movies table already up to date with {version} (use --force to rewrite)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
