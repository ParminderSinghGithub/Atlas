"""Initial schema: sellers, categories, products, latent_item_mappings

Revision ID: 001_initial_schema
Revises: 
Create Date: 2025-12-30 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001_initial_schema'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create all tables for Product Catalog Service."""
    
    # -------------------------
    # Table 1: sellers
    # -------------------------
    op.create_table(
        'sellers',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('email', sa.String(255), unique=True, nullable=False),
        sa.Column('description', sa.Text),
        sa.Column('website', sa.Text),
        sa.Column('phone', sa.String(50)),
        sa.Column('country', sa.String(100)),
        sa.Column('city', sa.String(100)),
        sa.Column('rating', sa.Numeric(3, 2)),
        sa.Column('total_reviews', sa.Integer, default=0),
        sa.Column('is_active', sa.Boolean, default=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('rating >= 0 AND rating <= 5', name='sellers_rating_check')
    )
    op.create_index('idx_sellers_is_active', 'sellers', ['is_active'])
    op.create_index('idx_sellers_rating', 'sellers', ['rating'])
    
    # -------------------------
    # Table 2: categories
    # -------------------------
    op.create_table(
        'categories',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('parent_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('categories.id'), nullable=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('slug', sa.String(255), nullable=False, unique=True),
        sa.Column('description', sa.Text),
        sa.Column('path', sa.Text, nullable=False),
        sa.Column('display_order', sa.Integer, default=0),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now())
    )
    op.create_index('idx_categories_parent_id', 'categories', ['parent_id'])
    op.create_index('idx_categories_path', 'categories', ['path'])
    op.create_index('idx_categories_slug', 'categories', ['slug'])
    
    # -------------------------
    # Table 3: products
    # -------------------------
    op.create_table(
        'products',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('category_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('categories.id'), nullable=False),
        sa.Column('seller_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('sellers.id'), nullable=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('description', sa.Text),
        sa.Column('price', sa.Numeric(10, 2), nullable=False),
        sa.Column('currency', sa.String(3), default='USD'),
        sa.Column('stock_quantity', sa.Integer, nullable=False, default=0),
        sa.Column('image_url', sa.Text),
        sa.Column('thumbnail_url', sa.Text),
        sa.Column('attributes', postgresql.JSONB, server_default='{}'),
        sa.Column('deleted_at', sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('price >= 0', name='products_price_check'),
        sa.CheckConstraint('stock_quantity >= 0', name='products_stock_check')
    )
    op.create_index('idx_products_category_id', 'products', ['category_id'])
    op.create_index('idx_products_seller_id', 'products', ['seller_id'])
    op.create_index('idx_products_deleted_at', 'products', ['deleted_at'])
    op.create_index('idx_products_price', 'products', ['price'])
    op.create_index('idx_products_created_at', 'products', ['created_at'])
    op.create_index('idx_products_attributes', 'products', ['attributes'], postgresql_using='gin')
    
    # -------------------------
    # Table 4: latent_item_mappings
    # -------------------------
    op.create_table(
        'latent_item_mappings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('product_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('products.id', ondelete='CASCADE'), nullable=False),
        sa.Column('latent_item_id', sa.Integer, nullable=False, unique=True),
        sa.Column('confidence_score', sa.Numeric(5, 4)),
        sa.Column('mapping_strategy', sa.String(50), nullable=False),
        sa.Column('mapping_metadata', postgresql.JSONB, server_default='{}'),
        sa.Column('created_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint('confidence_score >= 0 AND confidence_score <= 1', name='latent_mappings_confidence_check')
    )
    op.create_index('idx_latent_mappings_product_id', 'latent_item_mappings', ['product_id'])
    op.create_index('idx_latent_mappings_latent_item_id', 'latent_item_mappings', ['latent_item_id'], unique=True)


def downgrade() -> None:
    """Drop all tables in reverse order (respects foreign key constraints)."""
    op.drop_table('latent_item_mappings')
    op.drop_table('products')
    op.drop_table('categories')
    op.drop_table('sellers')
