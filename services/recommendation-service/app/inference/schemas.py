"""
Pydantic schemas for External ML Inference boundary.
"""
from typing import Optional, List, Union
from pydantic import BaseModel, Field, validator


class InferenceRequest(BaseModel):
    """
    Request schema for external ML inference endpoint.
    
    Fields:
    - user_id: User identifier (app UUID string or RetailRocket integer ID string)
    - item_id: Target item for similarity lookup (RetailRocket integer ID or numeric string)
    - candidate_ids: Optional list of pre-selected RetailRocket item IDs to rank
    - k: Number of candidates/recommendations requested (default: 100)
    - model_version: Requested model version artifact (optional)
    """
    user_id: Optional[str] = Field(None, description="User ID for personalized SVD & feature lookup")
    item_id: Optional[Union[int, str]] = Field(None, description="RetailRocket item ID for item-item similarity")
    candidate_ids: Optional[List[int]] = Field(None, description="Optional candidate item IDs to re-rank")
    k: int = Field(100, ge=1, le=500, description="Number of candidates to generate/rank")
    model_version: Optional[str] = Field(None, description="Optional model artifact version tag")

    @validator('k')
    def validate_k(cls, v):
        if v < 1 or v > 500:
            raise ValueError("k must be between 1 and 500")
        return v

    class Config:
        json_schema_extra = {
            "example": {
                "user_id": "12345",
                "item_id": 67890,
                "candidate_ids": None,
                "k": 100,
                "model_version": "production_v1"
            }
        }


class InferredItem(BaseModel):
    """Single scored candidate item produced by external ML inference."""
    item_id: int = Field(..., description="RetailRocket latent item integer ID")
    score: float = Field(..., description="Ranking or similarity score (higher = better)")


class InferenceResponse(BaseModel):
    """
    Response schema from external ML inference endpoint.
    
    Status values:
    - 'success': Candidates generated and/or ranked successfully
    - 'cold_start': User or item unknown to offline models (triggers local fallback)
    - 'error': Inference failed with error message
    """
    status: str = Field("success", description="Status code: 'success', 'cold_start', or 'error'")
    items: List[InferredItem] = Field(default_factory=list, description="Ranked list of items with scores")
    strategy_used: str = Field("external_inference", description="Strategy identifier (e.g. 'two_stage_svd_lgbm')")
    model_version: Optional[str] = Field(None, description="Model artifact version used for inference")
    error: Optional[str] = Field(None, description="Error message if status == 'error'")
    execution_time_ms: Optional[float] = Field(None, description="Inference execution duration in milliseconds")

    class Config:
        json_schema_extra = {
            "example": {
                "status": "success",
                "items": [
                    {"item_id": 10423, "score": 0.9421},
                    {"item_id": 8592, "score": 0.8834}
                ],
                "strategy_used": "two_stage_svd_lgbm",
                "model_version": "production_v1",
                "execution_time_ms": 14.5
            }
        }
