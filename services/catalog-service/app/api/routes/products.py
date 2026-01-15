"""
Product API routes (read-only).
Implements cursor-based pagination and filtering.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_
from typing import Optional
from uuid import UUID

from app.db.session import get_db
from app.db.models import Product, Category, Seller
from app.api.schemas import ProductListResponse, ProductDetail, ProductResponse, PaginationMeta, CategorySummary, SellerSummary
from app.core.config import settings

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", response_model=ProductListResponse)
def list_products(
    category_id: Optional[UUID] = Query(None, description="Filter by category UUID"),
    min_price: Optional[float] = Query(None, ge=0, description="Minimum price"),
    max_price: Optional[float] = Query(None, ge=0, description="Maximum price"),
    cursor: Optional[UUID] = Query(None, description="Cursor for pagination (product ID)"),
    limit: int = Query(settings.DEFAULT_PAGE_SIZE, ge=1, le=settings.MAX_PAGE_SIZE, description="Page size"),
    db: Session = Depends(get_db)
):
    """
    List products with cursor-based pagination and filtering.
    
    Filtering:
    - category_id: Filter by category UUID
    - min_price/max_price: Price range filter
    
    Pagination:
    - cursor: UUID of last product from previous page
    - limit: Number of products per page (default 20, max 100)
    
    Returns:
    - products: List of products
    - pagination: Metadata (next_cursor, has_more, limit)
    """
    # Build query with filters
    query = db.query(Product).filter(Product.deleted_at.is_(None))
    
    # Category filter
    if category_id:
        query = query.filter(Product.category_id == category_id)
    
    # Price range filters
    if min_price is not None:
        query = query.filter(Product.price >= min_price)
    if max_price is not None:
        query = query.filter(Product.price <= max_price)
    
    # Cursor pagination (fetch products with ID > cursor)
    if cursor:
        query = query.filter(Product.id > cursor)
    
    # Order by ID (stable sort) and fetch limit + 1 to detect if more results exist
    query = query.order_by(Product.id).limit(limit + 1)
    
    # Eager load relationships to avoid N+1 queries
    query = query.options(
        joinedload(Product.category),
        joinedload(Product.seller)
    )
    
    products = query.all()
    
    # Check if more results exist
    has_more = len(products) > limit
    if has_more:
        products = products[:limit]  # Trim extra product
    
    # Determine next cursor
    next_cursor = products[-1].id if products and has_more else None
    
    # Build response with USD to INR conversion
    return ProductListResponse(
        products=[
            ProductResponse(
                id=p.id,
                name=p.name,
                description=p.description,
                price=round(float(p.price) * settings.USD_TO_INR_RATE, 2),
                currency="INR",
                stock_quantity=p.stock_quantity,
                image_url=p.image_url,
                thumbnail_url=p.thumbnail_url,
                attributes=p.attributes,
                category=CategorySummary(
                    id=p.category.id,
                    name=p.category.name,
                    path=p.category.path
                ),
                seller=SellerSummary(
                    id=p.seller.id,
                    name=p.seller.name,
                    rating=p.seller.rating
                ) if p.seller else None
            )
            for p in products
        ],
        pagination=PaginationMeta(
            next_cursor=next_cursor,
            has_more=has_more,
            limit=limit
        )
    )


@router.get("/{product_id}", response_model=ProductDetail)
def get_product(
    product_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Get detailed product information by UUID.
    
    Returns:
    - Full product details including category, seller, timestamps
    
    Raises:
    - 404 if product not found or deleted
    """
    product = db.query(Product).filter(
        and_(
            Product.id == product_id,
            Product.deleted_at.is_(None)
        )
    ).options(
        joinedload(Product.category),
        joinedload(Product.seller)
    ).first()
    
    if not product:
        raise HTTPException(status_code=404, detail=f"Product {product_id} not found")
    
    return ProductDetail(
        id=product.id,
        name=product.name,
        description=product.description,
        price=round(float(product.price) * settings.USD_TO_INR_RATE, 2),
        currency="INR",
        stock_quantity=product.stock_quantity,
        image_url=product.image_url,
        thumbnail_url=product.thumbnail_url,
        attributes=product.attributes,
        category=CategorySummary(
            id=product.category.id,
            name=product.category.name,
            path=product.category.path
        ),
        seller=SellerSummary(
            id=product.seller.id,
            name=product.seller.name,
            rating=product.seller.rating
        ) if product.seller else None,
        created_at=product.created_at,
        updated_at=product.updated_at
    )
