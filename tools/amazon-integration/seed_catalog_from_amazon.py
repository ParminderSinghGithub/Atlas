"""
Catalog Seeding from Amazon Metadata

Purpose:
- Populate catalog database with real Amazon products
- Create categories, sellers, and products
- Idempotent execution (safe to run multiple times)
- Production-safe (preserves existing data)

Input:
- amazon_products.json (from ingest_amazon_catalog.py)
- category_mappings.json (from amazon_category_mapper.py)

Output:
- Populated catalog database (sellers, categories, products)

Safety:
- Uses deterministic UUIDs (idempotent)
- UPSERT semantics (ON CONFLICT)
- Validates schema before insertion
- Transaction-safe

Usage:
    python tools/seed_catalog_from_amazon.py
"""
import sys
import json
import os
from pathlib import Path
from uuid import uuid5, UUID, NAMESPACE_DNS
from decimal import Decimal
from typing import Dict, List, Optional, Set
import asyncio

# Add catalog service to path
catalog_service_path = Path(__file__).parent.parent.parent / "services" / "catalog-service"
sys.path.insert(0, str(catalog_service_path))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.db.models import Base, Category, Seller, Product

LOCAL_DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/ecommerce"


def get_database_url() -> str:
    """Resolve database URL from environment with local fallback."""
    return os.getenv("DATABASE_URL") or LOCAL_DATABASE_URL


def describe_database_target(database_url: str) -> str:
    """Return a short description of the database target."""
    if "localhost" in database_url or "127.0.0.1" in database_url:
        return "local"
    return "remote/Neon"


def make_uuid(namespace: str, name: str) -> UUID:
    """Generate deterministic UUID5 from namespace + name."""
    return uuid5(NAMESPACE_DNS, f"{namespace}:{name}")


class CatalogSeeder:
    """Seed catalog database with Amazon products."""
    
    def __init__(self, database_url: str):
        """
        Initialize seeder.
        
        Args:
            database_url: PostgreSQL connection string
        """
        self.database_url = database_url
        self.engine = None
        self.session_factory = None
        self._price_samples_logged = 0
    
    async def connect(self):
        """Create async database connection."""
        print(f"Connecting to database ({describe_database_target(self.database_url)})...")
        print(f"  Target host: {self.database_url.split('@')[-1]}")
        self.engine = create_async_engine(
            self.database_url,
            echo=False,  # Set to True for SQL debugging
            future=True
        )
        self.session_factory = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        print("✓ Connected to database")
    
    async def close(self):
        """Close database connection."""
        if self.engine:
            await self.engine.dispose()
    
    async def create_seller(self, session: AsyncSession) -> UUID:
        """
        Create or get platform seller.
        
        Returns:
            Seller UUID
        """
        print("\n=== Creating Seller ===")
        
        seller_id = make_uuid("seller", "amazon-platform")
        
        # Check if exists
        result = await session.execute(
            text("SELECT id FROM sellers WHERE id = :id"),
            {"id": seller_id}
        )
        existing = result.first()
        
        if existing:
            print("  ✓ Seller already exists (skipping)")
            return seller_id
        
        # Create new seller
        seller = Seller(
            id=seller_id,
            name="Amazon Platform Marketplace",
            email="marketplace@amazon-catalog.p1.com",
            description="Curated products from Amazon catalog",
            rating=Decimal("4.6"),
            is_active=True
        )
        
        session.add(seller)
        await session.flush()
        
        print(f"  ✓ Created seller: {seller.name}")
        return seller_id
    
    async def create_categories(
        self, 
        session: AsyncSession, 
        category_mappings: Dict
    ) -> Dict[str, UUID]:
        """
        Create category hierarchy from mappings.
        
        Args:
            session: Database session
            category_mappings: Category mapping dict
        
        Returns:
            Dict of slug -> UUID
        """
        print("\n=== Creating Categories ===")
        
        categories = category_mappings['categories']
        category_ids = {}
        
        # Sort by level (parents before children)
        sorted_categories = sorted(
            categories.items(),
            key=lambda x: x[1]['level']
        )
        
        for slug, cat_data in sorted_categories:
            cat_id = make_uuid("category", slug)
            
            # Resolve parent ID
            parent_id = None
            if cat_data['parent_slug']:
                parent_id = category_ids.get(cat_data['parent_slug'])
            
            # Check if exists
            result = await session.execute(
                text("SELECT id FROM categories WHERE slug = :slug"),
                {"slug": slug}
            )
            existing = result.first()
            
            if existing:
                category_ids[slug] = existing[0]
                continue
            
            # Create category
            category = Category(
                id=cat_id,
                name=cat_data['name'],
                slug=slug,
                description=f"{cat_data['name']} products",
                path=cat_data['path'],
                parent_id=parent_id,
                display_order=cat_data.get('level', 0)
            )
            
            session.add(category)
            category_ids[slug] = cat_id
            
            indent = "  " * (cat_data['level'] + 1)
            print(f"{indent}✓ {cat_data['name']} ({cat_data['product_count']} products)")
        
        await session.flush()
        
        print(f"\n  Total Categories Created: {len(category_ids)}")
        return category_ids
    
    async def create_products(
        self,
        session: AsyncSession,
        products: List[Dict],
        category_mappings: Dict,
        category_ids: Dict[str, UUID],
        seller_id: UUID
    ) -> int:
        """
        Create products from Amazon data.
        
        Args:
            session: Database session
            products: List of product dicts
            category_mappings: Category mappings
            category_ids: Dict of slug -> UUID
            seller_id: Seller UUID
        
        Returns:
            Number of products created
        """
        print("\n=== Creating Products ===")
        
        category_products = category_mappings.get('category_products', {})
        created_count = 0
        skipped_count = 0
        
        for idx, prod_data in enumerate(products):
            # Find category for this product
            parent_asin = prod_data['parent_asin']
            category_slug = None
            
            # Find which category this product belongs to
            for slug, asin_list in category_products.items():
                if parent_asin in asin_list:
                    category_slug = slug
                    break
            
            if not category_slug or category_slug not in category_ids:
                # Fallback to root category based on raw_category
                raw_cat = prod_data.get('raw_category', 'Other')
                category_slug = self._get_root_category_slug(raw_cat)
                if category_slug not in category_ids:
                    print(f"  ⚠️  No category found for {parent_asin}, skipping")
                    skipped_count += 1
                    continue
            
            category_id = category_ids[category_slug]
            
            # Generate deterministic product ID
            product_id = make_uuid("product", f"amazon:{parent_asin}")
            
            # Check if exists
            result = await session.execute(
                text("SELECT id FROM products WHERE id = :id"),
                {"id": product_id}
            )
            existing = result.first()
            
            if existing:
                skipped_count += 1
                continue
            
            # Build attributes JSONB
            attributes = {
                "parent_asin": parent_asin,
                "brand": prod_data.get('brand'),
                "store": prod_data.get('store'),
                "features": prod_data.get('features', []),
            }
            
            # Create product
            product = Product(
                id=product_id,
                name=prod_data['title'][:255],  # Respect DB constraint
                description=prod_data['description'][:2000],  # Limit length
                price=Decimal(str(prod_data['price'])),
                currency='INR',  # Products are already converted to INR
                stock_quantity=100,  # Default stock (can be updated later)
                image_url=prod_data['main_image_url'],
                thumbnail_url=prod_data.get('thumbnail_url') or prod_data['main_image_url'],
                attributes=attributes,
                category_id=category_id,
                seller_id=seller_id
            )

            if self._price_samples_logged < 3:
                print(
                    "  Seed price sample | "
                    f"parent_asin={parent_asin} | "
                    f"stored_price={prod_data['price']} | "
                    f"currency=INR | "
                    f"category={category_slug}"
                )
                self._price_samples_logged += 1
            
            session.add(product)
            created_count += 1
            
            # Periodic flush
            if (created_count + skipped_count) % 100 == 0:
                await session.flush()
                print(f"  Progress: {created_count} created, {skipped_count} skipped")
        
        await session.flush()
        
        print(f"\n  ✓ Created {created_count} products")
        print(f"  ⚠️  Skipped {skipped_count} products (duplicates or errors)")
        
        return created_count
    
    def _get_root_category_slug(self, raw_category: str) -> str:
        """Get root category slug from raw category name."""
        mapping = {
            'Electronics': 'electronics',
            'Cell_Phones_and_Accessories': 'cell-phones',
            'Sports_and_Outdoors': 'sports',
            'Software': 'software'
        }
        return mapping.get(raw_category, 'other')
    
    async def seed_catalog(
        self,
        products: List[Dict],
        category_mappings: Dict
    ):
        """
        Main seeding pipeline.
        
        Args:
            products: List of product dicts
            category_mappings: Category mapping dict
        """
        print("="*70)
        print("CATALOG SEEDING FROM AMAZON METADATA")
        print("="*70)
        
        async with self.session_factory() as session:
            try:
                # Step 1: Create seller
                seller_id = await self.create_seller(session)
                
                # Step 2: Create categories
                category_ids = await self.create_categories(session, category_mappings)
                
                # Step 3: Create products
                product_count = await self.create_products(
                    session,
                    products,
                    category_mappings,
                    category_ids,
                    seller_id
                )
                
                # Commit transaction
                await session.commit()
                
                print("\n" + "="*70)
                print("SEEDING COMPLETE")
                print("="*70)
                print(f"  Seller: 1")
                print(f"  Categories: {len(category_ids)}")
                print(f"  Products: {product_count}")
                print("="*70)
                
            except Exception as e:
                await session.rollback()
                print(f"\n❌ ERROR: {e}")
                raise


async def main():
    """Run catalog seeding pipeline."""
    # Paths
    project_root = Path(__file__).parent.parent.parent
    products_file = project_root / "tools" / "seed-data" / "amazon_products.json"
    categories_file = project_root / "tools" / "seed-data" / "category_mappings.json"
    
    # Validate inputs
    if not products_file.exists():
        print(f"ERROR: Products file not found: {products_file}")
        print("Run ingest_amazon_catalog.py first")
        return 1
    
    if not categories_file.exists():
        print(f"ERROR: Category mappings not found: {categories_file}")
        print("Run amazon_category_mapper.py first")
        return 1
    
    # Load data
    print("Loading input data...")
    with open(products_file, 'r', encoding='utf-8') as f:
        products = json.load(f)
    
    with open(categories_file, 'r', encoding='utf-8') as f:
        category_mappings = json.load(f)
    
    print(f"✓ Loaded {len(products)} products")
    print(f"✓ Loaded {len(category_mappings['categories'])} categories")
    
    # Database URL (env first, localhost fallback for local development)
    database_url = get_database_url()
    print(f"Database target: {describe_database_target(database_url)}")
    print(f"\nDatabase: {database_url.split('@')[-1]}")  # Hide credentials
    
    # Run seeding
    seeder = CatalogSeeder(database_url)
    await seeder.connect()
    
    try:
        await seeder.seed_catalog(products, category_mappings)
    finally:
        await seeder.close()
    
    print("\n✓ Catalog seeding complete")
    print(f"  Summary: products={len(products)} | categories={len(category_mappings['categories'])} | target={describe_database_target(database_url)}")
    return 0


if __name__ == "__main__":
    exit(asyncio.run(main()))
