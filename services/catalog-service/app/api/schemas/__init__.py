"""
Pydantic schemas for API request/response validation.
All responses use UUIDs (no RetailRocket IDs exposed).
"""
from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from datetime import datetime
from decimal import Decimal
from uuid import UUID


# -------------------------
# Seller Schemas
# -------------------------

class SellerBase(BaseModel):
    """Base seller schema (shared fields)."""
    name: str
    email: str
    description: Optional[str] = None
    website: Optional[str] = None
    phone: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    rating: Optional[Decimal] = None
    total_reviews: int = 0
    is_active: bool = True


class SellerResponse(SellerBase):
    """Seller response schema (includes ID and timestamps)."""
    id: UUID
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class SellerSummary(BaseModel):
    """Abbreviated seller info (used in product responses)."""
    id: UUID
    name: str
    rating: Optional[Decimal] = None
    
    model_config = ConfigDict(from_attributes=True)


# -------------------------
# Category Schemas
# -------------------------

class CategoryBase(BaseModel):
    """Base category schema."""
    name: str
    slug: str
    description: Optional[str] = None
    path: str
    display_order: int = 0


class CategoryResponse(CategoryBase):
    """Category response schema (includes ID and metadata)."""
    id: UUID
    parent_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


class CategorySummary(BaseModel):
    """Abbreviated category info (used in product responses)."""
    id: UUID
    name: str
    path: str
    
    model_config = ConfigDict(from_attributes=True)


class CategoryWithSubcategories(CategoryBase):
    """Category with nested subcategories (for category tree)."""
    id: UUID
    subcategories: List['CategorySummary'] = []
    
    model_config = ConfigDict(from_attributes=True)


class CategoryBreadcrumb(BaseModel):
    """Breadcrumb navigation item."""
    id: UUID
    name: str
    path: str
    
    model_config = ConfigDict(from_attributes=True)


class CategoryDetail(CategoryResponse):
    """Detailed category view (includes parent and breadcrumbs)."""
    parent: Optional[CategorySummary] = None
    breadcrumbs: List[CategoryBreadcrumb] = []
    product_count: int = 0
    
    model_config = ConfigDict(from_attributes=True)


# -------------------------
# Product Schemas
# -------------------------

class ProductBase(BaseModel):
    """Base product schema."""
    name: str
    description: Optional[str] = None
    price: Decimal
    currency: str = "USD"
    stock_quantity: int = 0
    image_url: Optional[str] = None
    thumbnail_url: Optional[str] = None
    attributes: dict = {}


class ProductResponse(ProductBase):
    """Product response schema (list view)."""
    id: UUID
    category: CategorySummary
    seller: Optional[SellerSummary] = None
    
    model_config = ConfigDict(from_attributes=True)


class ProductDetail(ProductBase):
    """Detailed product view (includes full category/seller info)."""
    id: UUID
    category: CategorySummary
    seller: Optional[SellerSummary] = None
    created_at: datetime
    updated_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


# -------------------------
# Pagination Schemas
# -------------------------

class PaginationMeta(BaseModel):
    """Pagination metadata for cursor-based pagination."""
    next_cursor: Optional[UUID] = Field(
        None,
        description="UUID cursor for next page (pass as ?cursor=<value>)"
    )
    has_more: bool = Field(
        description="True if more results available"
    )
    limit: int = Field(
        description="Page size used for this response"
    )


class ProductListResponse(BaseModel):
    """Paginated product list response."""
    products: List[ProductResponse]
    pagination: PaginationMeta


class CategoryListResponse(BaseModel):
    """Category list response."""
    categories: List[CategoryWithSubcategories]


# -------------------------
# Health Check Schema
# -------------------------

class HealthCheckResponse(BaseModel):
    """Health check response."""
    status: str = Field(description="Service status: healthy | unhealthy")
    database: str = Field(description="Database connection: connected | disconnected")
    timestamp: datetime = Field(description="Current server timestamp")
