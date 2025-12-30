"""
SQLAlchemy models for Product Catalog Service.
Implements schema from docs/PHASE_2_CATALOG_DESIGN.md.

Tables:
1. sellers - Multi-seller marketplace support
2. categories - Hierarchical product taxonomy
3. products - Core product catalog
4. latent_item_mappings - Bridge to ML models (RetailRocket IDs → Catalog UUIDs)
"""
from sqlalchemy import (
    Column, String, Integer, Numeric, Boolean, Text, 
    TIMESTAMP, ForeignKey, CheckConstraint, Index
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid

from app.db.session import Base


class Seller(Base):
    """
    Multi-seller marketplace support.
    Each product is sold by one seller.
    """
    __tablename__ = "sellers"
    
    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Core Attributes
    name = Column(String(255), nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    description = Column(Text)
    
    # Contact
    website = Column(Text)
    phone = Column(String(50))
    
    # Location
    country = Column(String(100))
    city = Column(String(100))
    
    # Ratings (future feature)
    rating = Column(Numeric(3, 2))
    total_reviews = Column(Integer, default=0)
    
    # Status
    is_active = Column(Boolean, default=True)
    
    # Audit
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    
    # Relationships
    products = relationship("Product", back_populates="seller")
    
    # Indexes
    __table_args__ = (
        CheckConstraint('rating >= 0 AND rating <= 5', name='check_seller_rating_range'),
        Index('idx_sellers_is_active', 'is_active'),
        Index('idx_sellers_rating', 'rating'),
    )


class Category(Base):
    """
    Hierarchical product taxonomy with materialized path.
    Supports breadcrumb navigation and fast ancestor queries.
    
    Example hierarchy:
        /electronics/audio/headphones
    """
    __tablename__ = "categories"
    
    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Hierarchy (self-referencing foreign key)
    parent_id = Column(UUID(as_uuid=True), ForeignKey('categories.id'), nullable=True)
    
    # Attributes
    name = Column(String(255), nullable=False)
    slug = Column(String(255), nullable=False, unique=True)
    description = Column(Text)
    
    # Materialized Path for fast ancestor queries
    # Example: "/electronics/audio/headphones"
    path = Column(Text, nullable=False)
    
    # Display
    display_order = Column(Integer, default=0)
    
    # Audit
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    
    # Relationships
    parent = relationship("Category", remote_side=[id], backref="subcategories")
    products = relationship("Product", back_populates="category")
    
    # Indexes
    __table_args__ = (
        Index('idx_categories_parent_id', 'parent_id'),
        Index('idx_categories_path', 'path'),
        Index('idx_categories_slug', 'slug'),
    )


class Product(Base):
    """
    Core product catalog.
    Each product belongs to one category and one seller.
    """
    __tablename__ = "products"
    
    # Primary Key (UUID v4 to prevent ID enumeration)
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Foreign Keys
    category_id = Column(UUID(as_uuid=True), ForeignKey('categories.id'), nullable=False)
    seller_id = Column(UUID(as_uuid=True), ForeignKey('sellers.id'), nullable=True)
    
    # Core Attributes
    name = Column(String(255), nullable=False)
    description = Column(Text)
    price = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(3), default='USD')
    stock_quantity = Column(Integer, nullable=False, default=0)
    
    # Images
    image_url = Column(Text)
    thumbnail_url = Column(Text)
    
    # Extensible Attributes (JSONB for category-specific fields)
    # Example: {"color": "Black", "brand": "AudioTech", "battery_life_hours": 30}
    attributes = Column(JSONB, default={}, server_default='{}')
    
    # Soft Delete (preserves order history, analytics)
    deleted_at = Column(TIMESTAMP(timezone=True), nullable=True)
    
    # Audit
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    
    # Relationships
    category = relationship("Category", back_populates="products")
    seller = relationship("Seller", back_populates="products")
    latent_mappings = relationship("LatentItemMapping", back_populates="product", cascade="all, delete-orphan")
    
    # Indexes and Constraints
    __table_args__ = (
        CheckConstraint('price >= 0', name='check_price_non_negative'),
        CheckConstraint('stock_quantity >= 0', name='check_stock_non_negative'),
        Index('idx_products_category_id', 'category_id'),
        Index('idx_products_seller_id', 'seller_id'),
        Index('idx_products_deleted_at', 'deleted_at'),
        Index('idx_products_price', 'price'),
        Index('idx_products_created_at', 'created_at'),
        # GIN index for JSONB attributes (enables fast queries on nested fields)
        Index('idx_products_attributes', 'attributes', postgresql_using='gin'),
    )


class LatentItemMapping(Base):
    """
    CRITICAL: Bridge pretrained ML models (RetailRocket IDs) to catalog products (UUIDs).
    
    Problem: LightGBM model trained on RetailRocket integer IDs (1-235061)
    Solution: Map RetailRocket latent_item_id → catalog product_id (UUID)
    
    Usage:
        1. Model recommends RetailRocket ID 12345
        2. Query: SELECT product_id FROM latent_item_mappings WHERE latent_item_id = 12345
        3. Fetch catalog product with UUID
        4. Return to user (no RetailRocket exposure)
    
    Confidence score reflects mapping quality:
        1.0 = exact match (same name/category)
        0.8 = high similarity (same category, similar attributes)
        0.5 = weak match (popularity-based fallback)
    """
    __tablename__ = "latent_item_mappings"
    
    # Primary Key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Foreign Key to Catalog
    product_id = Column(
        UUID(as_uuid=True), 
        ForeignKey('products.id', ondelete='CASCADE'), 
        nullable=False
    )
    
    # ML Model Latent Space ID (integer from RetailRocket dataset)
    latent_item_id = Column(Integer, nullable=False, unique=True)
    
    # Mapping Quality
    confidence_score = Column(Numeric(5, 4))
    
    # Mapping Strategy
    # Values: "exact_match" | "category_popularity" | "random_sample" | "manual"
    mapping_strategy = Column(String(50), nullable=False)
    
    # Metadata (JSONB for extensibility)
    # Example: {"retailrocket_category": "headphones", "reason": "top popularity match"}
    mapping_metadata = Column(JSONB, default={}, server_default='{}')
    
    # Audit
    created_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(TIMESTAMP(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
    
    # Relationships
    product = relationship("Product", back_populates="latent_mappings")
    
    # Indexes and Constraints
    __table_args__ = (
        CheckConstraint('confidence_score >= 0 AND confidence_score <= 1', name='check_confidence_score_range'),
        Index('idx_latent_mappings_product_id', 'product_id'),
        # Unique constraint ensures 1-to-1 mapping (each RetailRocket ID maps to at most one catalog product)
        Index('idx_latent_mappings_latent_item_id', 'latent_item_id', unique=True),
    )
