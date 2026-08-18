"""
Reference & Mock Implementation for External ML Inference Server.

Purpose:
- Implements the contract defined in schemas.py
- Returns deterministic candidate generation + ranking for testing
- Serves as a reference architecture for the eventual Hugging Face Space
"""
import time
from typing import List
from fastapi import FastAPI, HTTPException
from app.inference.schemas import InferenceRequest, InferenceResponse, InferredItem

# Create lightweight FastAPI app
mock_ml_app = FastAPI(
    title="Atlas External ML Inference Service (Reference/Mock)",
    description="Reference implementation of the external ML inference boundary for Atlas",
    version="1.0.0"
)


@mock_ml_app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "atlas-external-ml-inference",
        "version": "1.0.0",
        "models_loaded": {
            "svd": True,
            "similarity": True,
            "lightgbm_ranker": True,
            "features": True
        }
    }


@mock_ml_app.post("/infer", response_model=InferenceResponse)
async def infer(request: InferenceRequest):
    """
    Execute ML inference (SVD, Item Similarity, and LightGBM ranking).
    
    Deterministic mock behavior for validation:
    1. If candidate_ids provided: ranks candidate_ids with descending scores.
    2. If item_id provided: returns similar item candidates with scores.
    3. If user_id provided: returns personalized SVD candidates with scores.
    4. If none provided: returns empty list with status='cold_start'.
    """
    start_time = time.time()
    k = request.k or 100
    model_version = request.model_version or "production_v1"

    # Case 1: Pre-selected candidates to re-rank with LightGBM
    if request.candidate_ids:
        items = [
            InferredItem(
                item_id=cid,
                score=round(1.0 - (idx * 0.005), 4)
            )
            for idx, cid in enumerate(request.candidate_ids[:k])
        ]
        elapsed = (time.time() - start_time) * 1000
        return InferenceResponse(
            status="success",
            items=items,
            strategy_used="lightgbm_ranking",
            model_version=model_version,
            execution_time_ms=round(elapsed, 2)
        )

    # Case 2: Product context (Item-Item Similarity + LightGBM ranking)
    if request.item_id is not None:
        try:
            base_item = int(request.item_id)
        except (ValueError, TypeError):
            base_item = 1000

        # Generate deterministic synthetic neighbors based on base_item
        similar_ids = [(base_item + (i * 17) + 1) for i in range(min(k, 50))]
        items = [
            InferredItem(
                item_id=sim_id,
                score=round(0.95 - (idx * 0.01), 4)
            )
            for idx, sim_id in enumerate(similar_ids)
        ]
        elapsed = (time.time() - start_time) * 1000
        return InferenceResponse(
            status="success",
            items=items,
            strategy_used="two_stage_item_sim_lgbm",
            model_version=model_version,
            execution_time_ms=round(elapsed, 2)
        )

    # Case 3: User personalization (SVD Collaborative Filtering + LightGBM ranking)
    if request.user_id:
        # Check for simulated cold start test user
        if str(request.user_id).startswith("cold_start") or str(request.user_id) == "unknown":
            elapsed = (time.time() - start_time) * 1000
            return InferenceResponse(
                status="cold_start",
                items=[],
                strategy_used="svd_cold_start",
                model_version=model_version,
                execution_time_ms=round(elapsed, 2)
            )

        # Generate deterministic synthetic candidates based on user hash
        user_hash = abs(hash(str(request.user_id))) % 10000
        candidate_ids = [(user_hash + (i * 23) + 100) for i in range(min(k, 50))]
        items = [
            InferredItem(
                item_id=cid,
                score=round(0.98 - (idx * 0.008), 4)
            )
            for idx, cid in enumerate(candidate_ids)
        ]
        elapsed = (time.time() - start_time) * 1000
        return InferenceResponse(
            status="success",
            items=items,
            strategy_used="two_stage_svd_lgbm",
            model_version=model_version,
            execution_time_ms=round(elapsed, 2)
        )

    # Case 4: Neither user nor item supplied
    elapsed = (time.time() - start_time) * 1000
    return InferenceResponse(
        status="cold_start",
        items=[],
        strategy_used="empty_query",
        model_version=model_version,
        error="No user_id or item_id provided for inference",
        execution_time_ms=round(elapsed, 2)
    )
