"""
Seller API routes (read-only).
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from uuid import UUID

from app.db.session import get_db
from app.db.models import Seller
from app.api.schemas import SellerResponse

router = APIRouter(prefix="/sellers", tags=["sellers"])


@router.get("/{seller_id}", response_model=SellerResponse)
def get_seller(
    seller_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Get seller information by UUID.
    
    Path Parameters:
    - seller_id: UUID of seller
    
    Returns:
    - Seller details (name, email, rating, active status, timestamps)
    
    Raises:
    - 404 if seller not found
    """
    seller = db.query(Seller).filter(Seller.id == seller_id).first()
    
    if not seller:
        raise HTTPException(status_code=404, detail=f"Seller {seller_id} not found")
    
    return SellerResponse(
        id=seller.id,
        name=seller.name,
        email=seller.email,
        rating=seller.rating,
        is_active=seller.is_active,
        created_at=seller.created_at,
        updated_at=seller.updated_at
    )
