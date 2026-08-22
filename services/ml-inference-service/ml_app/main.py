"""
Atlas External ML Inference Service.

Standalone FastAPI application for hosting the compute-intensive recommendation models:
- SVD Collaborative Filtering
- Item-Item Similarity Matrix
- User & Item Feature Store (Parquet)
- LightGBM LambdaRank Precision Scoring
"""
import time
from contextlib import asynccontextmanager
from typing import Optional, List
import numpy as np
from fastapi import FastAPI, HTTPException, status
from fastapi.responses import JSONResponse

from ml_app.core.config import settings, get_active_model_version
from ml_app.core.logging import setup_logging, get_logger
from ml_app.schemas import (
    InferenceRequest,
    InferenceResponse,
    InferredItem,
    HealthResponse,
    ReadinessResponse,
    MetadataResponse,
)
from ml_app.models.svd import get_svd_model
from ml_app.models.similarity import get_similarity_model
from ml_app.models.lightgbm_ranker import get_ranker
from ml_app.features.loader import get_feature_loader
from ml_app.core.manifest import ArtifactVerifier, ArtifactVerificationResult

# Initialize logging
setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Service lifespan: load ML artifacts at startup and verify integrity/compatibility.
    """
    logger.info("=" * 70)
    logger.info("STARTING ATLAS EXTERNAL ML INFERENCE SERVICE")
    logger.info("=" * 70)

    # 1. SVD Model Serving (Disabled in production path)
    if settings.enable_svd_serving:
        logger.info("[1/4] Loading SVD Model...")
        svd = get_svd_model()
        svd_loaded = svd.load()
    else:
        logger.info("[1/4] SVD Model serving disabled in production path (skipping artifact load)")
        svd_loaded = False

    # 2. Load Item-Item Similarity Model
    logger.info("[2/4] Loading Item Similarity Matrix...")
    similarity = get_similarity_model()
    sim_loaded = similarity.load()

    # 3. Load Feature Tables
    logger.info("[3/4] Loading Feature Tables from Parquet...")
    features = get_feature_loader()
    feats_loaded = features.load_all()

    # 4. Load LightGBM Ranker
    logger.info("[4/4] Loading LightGBM Ranker...")
    ranker = get_ranker()
    ranker_loaded = ranker.load()

    # 5. Verify Artifact Checksums & Compatibility
    logger.info("[5/5] Verifying Artifact Integrity and Schema Compatibility...")
    verifier = ArtifactVerifier()
    verification_result = verifier.verify_all(
        ranker_features=ranker.feature_names if ranker.is_available() else None,
        user_features_cols=features.user_feature_cols if features.is_available() else None,
        item_features_cols=features.item_feature_cols if features.is_available() else None,
    )
    app.state.verification_result = verification_result

    logger.info("=" * 70)
    logger.info(
        "ML ARTIFACTS LOAD STATUS: SVD=%s | Similarity=%s | Features=%s | LightGBM=%s | IntegrityVerified=%s",
        svd_loaded,
        sim_loaded,
        feats_loaded,
        ranker_loaded,
        verification_result.is_valid,
    )
    if not verification_result.is_valid:
        logger.error("ARTIFACT INTEGRITY/COMPATIBILITY ERRORS: %s", verification_result.errors)
    logger.info("=" * 70)

    yield

    logger.info("Shutting down Atlas ML Inference Service...")


app = FastAPI(
    title="Atlas External ML Inference Service",
    description="Dedicated high-throughput ML inference service for Atlas recommendation platform",
    version="2.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)


@app.get("/health", response_model=HealthResponse)
async def health():
    """Liveness probe: verifies the service process is alive."""
    return HealthResponse(
        status="ok",
        service=settings.service_name,
        version="1.0.0"
    )


@app.get("/ready", response_model=ReadinessResponse)
async def readiness():
    """Readiness probe: verifies all model artifacts are loaded and pass integrity checks."""
    svd = get_svd_model()
    similarity = get_similarity_model()
    ranker = get_ranker()
    features = get_feature_loader()

    models_status = {
        "svd": svd.is_available(),
        "similarity": similarity.is_available(),
        "lightgbm_ranker": ranker.is_available(),
        "features": features.is_available(),
    }

    # Retrieve verification result from app state if available
    verification_result: Optional[ArtifactVerificationResult] = getattr(app.state, "verification_result", None)
    if verification_result is None:
        verifier = ArtifactVerifier()
        verification_result = verifier.verify_all(
            ranker_features=ranker.feature_names if ranker.is_available() else None,
            user_features_cols=features.user_feature_cols if features.is_available() else None,
            item_features_cols=features.item_feature_cols if features.is_available() else None,
        )

    has_models = any(models_status.values())
    is_ready = has_models and verification_result.is_valid

    response = ReadinessResponse(
        ready=is_ready,
        model_version=get_active_model_version(),
        models_loaded=models_status,
        integrity_verified=verification_result.is_valid,
        errors=verification_result.errors,
    )

    if not is_ready:
        payload = response.dict() if hasattr(response, "dict") else response.model_dump()
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content=payload)

    return response


@app.get("/metadata", response_model=MetadataResponse)
async def metadata():
    """Metadata probe: returns loaded artifact versions, checksum statuses, and feature schemas."""
    svd = get_svd_model()
    ranker = get_ranker()
    features = get_feature_loader()

    active_version = get_active_model_version()
    verification_result: Optional[ArtifactVerificationResult] = getattr(app.state, "verification_result", None)
    if verification_result is None or getattr(verification_result, "model_version", None) != active_version:
        verifier = ArtifactVerifier(model_version=active_version)
        verification_result = verifier.verify_all(
            ranker_features=ranker.feature_names if ranker.is_available() else None,
            user_features_cols=features.user_feature_cols if features.is_available() else None,
            item_features_cols=features.item_feature_cols if features.is_available() else None,
        )

    return MetadataResponse(
        service_name=settings.service_name,
        model_version=active_version,
        integrity_verified=verification_result.is_valid,
        manifest_found=verification_result.manifest_found,
        artifacts=verification_result.artifacts_checked,
        feature_compatibility=verification_result.feature_compatibility,
        errors=verification_result.errors,
    )


@app.post("/infer", response_model=InferenceResponse)
@app.post("/api/v1/infer", response_model=InferenceResponse)
async def infer(request: InferenceRequest):
    """
    Execute full two-stage ML inference:
    Stage 1 (Recall): Candidate generation via SVD, Similarity, or pre-supplied candidates.
    Stage 2 (Precision): Feature assembly & LightGBM ranking.
    """
    start_time = time.time()
    k = request.k or settings.candidate_pool_size
    model_version = request.model_version or get_active_model_version()

    candidate_ids: Optional[List[int]] = None
    strategy_source = "unknown"

    # Case 1: Pre-supplied candidate pool to re-rank with LightGBM
    if request.candidate_ids:
        candidate_ids = request.candidate_ids[:settings.max_candidates]
        strategy_source = "candidate_pool"

    # Case 2: Product-based similarity lookup
    elif request.item_id is not None:
        try:
            item_int_id = int(request.item_id)
            sim_model = get_similarity_model()
            similar_candidates = sim_model.get_similar_items(item_int_id, k=k)
            if similar_candidates:
                candidate_ids = similar_candidates
                strategy_source = "item_similarity"
            else:
                elapsed_ms = (time.time() - start_time) * 1000
                return InferenceResponse(
                    status="cold_start",
                    items=[],
                    strategy_used="item_similarity_unknown_item",
                    model_version=model_version,
                    execution_time_ms=round(elapsed_ms, 2)
                )
        except (ValueError, TypeError):
            logger.warning("Invalid item_id for similarity: %s", request.item_id)

    # Case 3: User personalization via SVD collaborative filtering
    elif request.user_id:
        user_str = str(request.user_id)
        is_explicit_svd = request.strategy == "svd"
        
        # Check if user_id is a production guest session or UUID
        is_guest = user_str.startswith("guest_")
        is_uuid_format = False
        try:
            from uuid import UUID
            UUID(user_str)
            is_uuid_format = True
        except (ValueError, AttributeError):
            is_uuid_format = False

        # Frontend guest/UUID traffic safely bypasses SVD unless explicitly overridden
        if not settings.enable_svd_serving or ((is_guest or is_uuid_format) and not is_explicit_svd):
            elapsed_ms = (time.time() - start_time) * 1000
            strategy_name = "svd_disabled" if not settings.enable_svd_serving else "svd_cold_start"
            return InferenceResponse(
                status="cold_start",
                items=[],
                strategy_used=strategy_name,
                model_version=model_version,
                execution_time_ms=round(elapsed_ms, 2)
            )

        svd_model = get_svd_model()
        if not svd_model.is_available():
            svd_model.load()

        svd_candidates = svd_model.get_candidates(user_str, k=k) if svd_model.is_available() else None
        if svd_candidates:
            candidate_ids = svd_candidates
            strategy_source = "svd"
        else:
            elapsed_ms = (time.time() - start_time) * 1000
            return InferenceResponse(
                status="cold_start",
                items=[],
                strategy_used="svd_cold_start",
                model_version=model_version,
                execution_time_ms=round(elapsed_ms, 2)
            )

    # Case 4: No user or item context provided
    if not candidate_ids:
        elapsed_ms = (time.time() - start_time) * 1000
        return InferenceResponse(
            status="cold_start",
            items=[],
            strategy_used="empty_context",
            model_version=model_version,
            error="No user_id, item_id, or candidate_ids provided for inference",
            execution_time_ms=round(elapsed_ms, 2)
        )

    # Stage 2: Feature Assembly & LightGBM Ranking
    ranker = get_ranker()
    feature_loader = get_feature_loader()

    if ranker.is_available() and feature_loader.is_available():
        try:
            features_df = feature_loader.assemble_features(
                user_id=request.user_id,
                retailrocket_item_ids=candidate_ids,
            )

            scores = ranker.predict(features_df)

            # Sort descending by score
            sorted_indices = np.argsort(scores)[::-1][:k]
            ranked_items = [
                InferredItem(
                    item_id=int(candidate_ids[idx]),
                    score=round(float(scores[idx]), 4)
                )
                for idx in sorted_indices
            ]

            strategy_name = (
                "two_stage_svd_lgbm" if strategy_source == "svd"
                else ("two_stage_item_sim_lgbm" if strategy_source == "item_similarity" else "lightgbm_ranking")
            )

            elapsed_ms = (time.time() - start_time) * 1000
            return InferenceResponse(
                status="success",
                items=ranked_items,
                strategy_used=strategy_name,
                model_version=model_version,
                execution_time_ms=round(elapsed_ms, 2)
            )

        except Exception as exc:
            logger.exception("Stage 2 ranking failed: %s", exc)

    # Fallback: return candidates with descending default scores if ranker unavailable
    fallback_items = [
        InferredItem(
            item_id=int(cid),
            score=round(1.0 - (idx * 0.01), 4)
        )
        for idx, cid in enumerate(candidate_ids[:k])
    ]

    strategy_name = f"{strategy_source}_no_ranking"
    elapsed_ms = (time.time() - start_time) * 1000

    return InferenceResponse(
        status="success",
        items=fallback_items,
        strategy_used=strategy_name,
        model_version=model_version,
        execution_time_ms=round(elapsed_ms, 2)
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=settings.service_port,
        reload=False
    )
