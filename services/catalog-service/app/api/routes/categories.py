"""
Category API routes (read-only).
Implements hierarchical navigation and product filtering.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_
from typing import Optional, List
from uuid import UUID

from app.db.session import get_db
from app.db.models import Category, Product
from app.api.schemas import (
    CategoryListResponse,
    CategoryDetail,
    CategoryResponse,
    CategoryWithSubcategories,
    CategorySummary,
    CategoryBreadcrumb,
    ProductListResponse,
    ProductResponse,
    SellerSummary,
    PaginationMeta
)
from app.core.config import settings

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("", response_model=CategoryListResponse)
def list_categories(
    parent_id: Optional[UUID] = Query(None, description="Filter by parent category UUID (null = top-level)"),
    db: Session = Depends(get_db)
):
    """
    List categories filtered by parent.
    
    Query Parameters:
    - parent_id: UUID of parent category (omit or null for top-level categories)
    
    Returns:
    - categories: List of categories with subcategory counts
    
    Note: Returns all matching categories (no pagination)
    """
    # Build query
    query = db.query(Category)
    
    # Filter by parent_id (None for top-level categories)
    if parent_id:
        query = query.filter(Category.parent_id == parent_id)
    else:
        query = query.filter(Category.parent_id.is_(None))
    
    # Order by display_order
    query = query.order_by(Category.display_order)
    
    # Eager load subcategories relationship
    query = query.options(joinedload(Category.subcategories))
    
    categories = query.all()
    
    # Build response
    return CategoryListResponse(
        categories=[
            CategoryWithSubcategories(
                id=c.id,
                name=c.name,
                slug=c.slug,
                description=c.description,
                path=c.path,
                subcategories=[
                    CategorySummary(
                        id=sub.id,
                        name=sub.name,
                        path=sub.path
                    )
                    for sub in sorted(c.subcategories, key=lambda x: x.display_order)
                ]
            )
            for c in categories
        ]
    )


@router.get("/{category_id}", response_model=CategoryDetail)
def get_category(
    category_id: UUID,
    db: Session = Depends(get_db)
):
    """
    Get detailed category information by UUID.
    
    Returns:
    - Full category details including breadcrumb path, subcategories
    
    Raises:
    - 404 if category not found
    """
    category = db.query(Category).filter(
        Category.id == category_id
    ).options(
        joinedload(Category.subcategories)
    ).first()
    
    if not category:
        raise HTTPException(status_code=404, detail=f"Category {category_id} not found")
    
    # Build breadcrumb (traverse path upwards)
    breadcrumb = _build_breadcrumb(category, db)
    
    return CategoryDetail(
        id=category.id,
        name=category.name,
        slug=category.slug,
        description=category.description,
        path=category.path,
        breadcrumb=breadcrumb,
        subcategories=[
            CategorySummary(
                id=sub.id,
                name=sub.name,
                path=sub.path
            )
            for sub in sorted(category.subcategories, key=lambda x: x.display_order)
        ],
        created_at=category.created_at,
        updated_at=category.updated_at
    )


@router.get("/{category_id}/products", response_model=ProductListResponse)
def list_category_products(
    category_id: UUID,
    cursor: Optional[UUID] = Query(None, description="Cursor for pagination (product ID)"),
    limit: int = Query(settings.DEFAULT_PAGE_SIZE, ge=1, le=settings.MAX_PAGE_SIZE, description="Page size"),
    db: Session = Depends(get_db)
):
    """
    List products in a specific category with cursor-based pagination.
    
    Path Parameters:
    - category_id: UUID of category
    
    Query Parameters:
    - cursor: UUID of last product from previous page
    - limit: Number of products per page (default 20, max 100)
    
    Returns:
    - products: List of products in category
    - pagination: Metadata (next_cursor, has_more, limit)
    
    Raises:
    - 404 if category not found
    """
    # Verify category exists
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail=f"Category {category_id} not found")
    
    # Build query with filters
    query = db.query(Product).filter(
        and_(
            Product.category_id == category_id,
            Product.deleted_at.is_(None)
        )
    )
    
    # Cursor pagination
    if cursor:
        query = query.filter(Product.id > cursor)
    
    # Order by ID and fetch limit + 1
    query = query.order_by(Product.id).limit(limit + 1)
    
    # Eager load relationships
    query = query.options(
        joinedload(Product.category),
        joinedload(Product.seller)
    )
    
    products = query.all()
    
    # Check if more results exist
    has_more = len(products) > limit
    if has_more:
        products = products[:limit]
    
    # Determine next cursor
    next_cursor = products[-1].id if products and has_more else None
    
    # Build response
    return ProductListResponse(
        products=[
            ProductResponse(
                id=p.id,
                name=p.name,
                description=p.description,
                price=p.price,
                currency=p.currency,
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


def _build_breadcrumb(category: Category, db: Session) -> List[CategoryBreadcrumb]:
    """
    Build breadcrumb trail from root to current category.
    Traverses parent_id chain upwards.
    """
    breadcrumb = []
    current = category
    
    # Traverse upwards to root
    while current:
        breadcrumb.append(
            CategoryBreadcrumb(
                id=current.id,
                name=current.name,
                slug=current.slug,
                path=current.path
            )
        )
        # Fetch parent if exists
        if current.parent_id:
            current = db.query(Category).filter(Category.id == current.parent_id).first()
        else:
            current = None
    
    # Reverse to get root → current order
    return list(reversed(breadcrumb))
