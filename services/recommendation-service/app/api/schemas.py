"""
Pydantic schemas for Recommendation API.

Why Pydantic:
- Automatic validation
- OpenAPI documentation
- Type safety
- Clear contracts
"""
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Union
from uuid import UUID


class RecommendationRequest(BaseModel):
    """
    Request schema for recommendations endpoint.
    
    Validation rules:
    - At least one of user_id or product_id required
    - k must be positive and <= max
    - user_id/product_id can be UUID (catalog) or str (RetailRocket)
    """
    user_id: Optional[Union[UUID, str]] = Field(None, description="User ID for personalized recommendations (UUID or RetailRocket ID)")
    product_id: Optional[Union[UUID, str]] = Field(None, description="Product ID for similar item recommendations (UUID or RetailRocket ID)")
    k: int = Field(10, ge=1, le=50, description="Number of recommendations to return")
    include_metadata: bool = Field(False, description="Include explainability metadata")
    
    @validator('k')
    def validate_k(cls, v):
        """Ensure k within allowed range."""
        if v < 1 or v > 50:
            raise ValueError("k must be between 1 and 50")
        return v
    
    class Config:
        schema_extra = {
            "example": {
                "user_id": "550e8400-e29b-41d4-a716-446655440000",
                "k": 10,
                "include_metadata": False
            }
        }


class RecommendedProduct(BaseModel):
    """Single recommended product."""
    product_id: UUID = Field(..., description="Catalog product UUID")
    score: float = Field(..., description="Recommendation score (higher = better)")
    rank: int = Field(..., description="Rank in recommendation list (1-indexed)")
    
    # Product metadata
    name: Optional[str] = Field(None, description="Product name")
    price: Optional[float] = Field(None, description="Product price")
    category_name: Optional[str] = Field(None, description="Category name")
    category_slug: Optional[str] = Field(None, description="Category slug for filtering")
    image_url: Optional[str] = Field(None, description="Product image URL")
    
    # Optional explainability fields
    reason: Optional[str] = Field(None, description="Why this product was recommended")
    confidence: Optional[float] = Field(None, description="Mapping confidence score")
    pipeline_stage: Optional[str] = Field(None, description="Pipeline stage that generated this recommendation")
    session_boosted: Optional[bool] = Field(None, description="Whether session signals boosted this item")


class RecommendationResponse(BaseModel):
    """
    Response schema for recommendations endpoint.
    
    Always returns a response (never empty unless catalog empty).
    Includes explainability metadata when requested.
    """
    recommendations: List[RecommendedProduct] = Field(..., description="Ranked list of recommendations")
    strategy_used: str = Field(..., description="Strategy used (svd, similarity, popularity)")
    total_candidates: int = Field(..., description="Number of candidates before filtering")
    total_returned: int = Field(..., description="Number of recommendations returned")
    
    # Explainability metadata
    pipeline_explanation: Optional[dict] = Field(None, description="Pipeline stage explanations")
    session_reranking: Optional[dict] = Field(None, description="Session re-ranking metadata")
    
    class Config:
        schema_extra = {
            "example": {
                "recommendations": [
                    {
                        "product_id": "660f9511-e89b-12d3-a456-426614174000",
                        "score": 0.89,
                        "rank": 1,
                        "reason": "Similar to viewed product",
                        "confidence": 0.92
                    }
                ],
                "strategy_used": "svd",
                "total_candidates": 100,
                "total_returned": 10
            }
        }


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = Field(..., description="Service status")
    models_loaded: dict = Field(..., description="Model availability status")
    database_connected: bool = Field(..., description="Database connection status")


class SessionTrackRequest(BaseModel):
    """Request to track session event."""
    user_id: str = Field(..., description="User identifier")
    event_type: str = Field(..., description="Event type: 'category_view' or 'product_view'")
    category_slug: Optional[str] = Field(None, description="Category slug (for category_view)")
    product_id: Optional[UUID] = Field(None, description="Product UUID (for product_view)")


class SessionTrackResponse(BaseModel):
    """Response for session tracking."""
    success: bool = Field(..., description="Whether tracking succeeded")
    message: str = Field(..., description="Status message")

