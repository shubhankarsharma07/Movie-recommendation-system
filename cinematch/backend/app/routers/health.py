"""GET /api/health — public, used by Render's health check and the frontend's
"waking up the server" screen."""
from fastapi import APIRouter, Depends

from app.deps import get_model_state
from app.services.model_store import store

router = APIRouter(prefix="/api", tags=["health"])


@router.get("/health")
def health(state=Depends(get_model_state)):
    return {
        "status": "ok",
        "model_loaded": store.model_loaded,
        "model_version": state.version if state is not None else None,
        "dataset_mode": state.dataset_mode if state is not None else None,
        "catalog_size": state.n if state is not None else 0,
    }
