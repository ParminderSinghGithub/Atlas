"""
Seed Kubernetes Catalog with Amazon Data

PURPOSE: Populate K8s postgres database with Amazon products, categories, and latent mappings.
USAGE: Copy to catalog-service pod and run:
       kubectl cp tools/seed_k8s_amazon.py atlas/catalog-service-xxx:/tmp/
       kubectl exec -n atlas catalog-service-xxx -- python /tmp/seed_k8s_amazon.py

REQUIRES:
- amazon_products.json in /tmp/
- category_mappings.json in /tmp/
- Running catalog-service pod with database access
"""
import json
from pathlib import Path
from uuid import uuid5, UUID, NAMESPACE_DNS
from decimal import Decimal

import sys
sys.path.insert(0, '/app')

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from app.db.models import Category, Seller, Product, LatentItemMapping

# Database URL - connects to K8s postgres service (synchronous)
DATABASE_URL = "postgresql://postgres:postgres@postgres:5432/ecommerce"

def make_uuid(namespace: str, name: str) -> UUID:
    """Generate deterministic UUID5."""
    return uuid5(NAMESPACE_DNS, f"{namespace}:{name}")

def seed_kubernetes_catalog():
    """Seed catalog with Amazon data for Kubernetes."""
    # Load JSON files
    with open('/tmp/amazon_products.json', 'r', encoding='utf-8') as f:
        products_data = json.load(f)
    
    with open('/tmp/category_mappings.json', 'r', encoding='utf-8') as f:
        category_mappings = json.load(f)
    
    print(f"Loaded {len(products_data)} products")
    print(f"Loaded {len(category_mappings['categories'])} categories")
    
    # Connect to database
    engine = create_engine(DATABASE_URL, echo=False)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        print("\n=== Creating Seller ===")
        seller_id = make_uuid("seller", "amazon-platform")
        
        # Check if seller exists
        result = session.execute(
            text("SELECT id FROM sellers WHERE id = :id"),
            {"id": seller_id}
        )
        if not result.first():
            seller = Seller(
                id=seller_id,
                name="Amazon Platform Marketplace",
                email="marketplace@amazon-catalog.p1.com",
                description="Curated products from Amazon catalog",
                rating=Decimal("4.6"),
                is_active=True
            )
            session.add(seller)
            session.flush()
            print("  [OK] Created seller")
        else:
            print("  [OK] Seller already exists")
        
        print("\n=== Creating Categories ===")
        categories = category_mappings['categories']
        category_ids = {}
        
        # Sort by level (parents first)
        sorted_categories = sorted(categories.items(), key=lambda x: x[1]['level'])
        
        for slug, cat_data in sorted_categories:
            cat_id = make_uuid("category", slug)
            
            # Check if exists
            result = session.execute(
                text("SELECT id FROM categories WHERE slug = :slug"),
                {"slug": slug}
            )
            existing = result.first()
            
            if not existing:
                # Resolve parent
                parent_id = None
                if cat_data['parent_slug'] and cat_data['parent_slug'] in category_ids:
                    parent_id = category_ids[cat_data['parent_slug']]
                
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
            print(f"{indent}[OK] {cat_data['name']}")
        
        session.flush()
        print(f"\n  Total categories: {len(category_ids)}")
        
        print("\n=== Creating Products ===")
        category_products = category_mappings.get('category_products', {})
        created = 0
        skipped = 0
        
        for prod_data in products_data:
            parent_asin = prod_data['parent_asin']
            
            # Find category
            category_slug = None
            for slug, asin_list in category_products.items():
                if parent_asin in asin_list:
                    category_slug = slug
                    break
            
            if not category_slug or category_slug not in category_ids:
                # Fallback based on raw_category
                raw_cat = prod_data.get('raw_category', 'Other')
                mapping = {
                    'Electronics': 'electronics',
                    'Cell_Phones_and_Accessories': 'cell-phones',
                    'Sports_and_Outdoors': 'sports',
                    'Software': 'software'
                }
                category_slug = mapping.get(raw_cat, 'other')
                if category_slug not in category_ids:
                    skipped += 1
                    continue
            
            category_id = category_ids[category_slug]
            product_id = make_uuid("product", f"amazon:{parent_asin}")
            
            # Check if exists
            result = session.execute(
                text("SELECT id FROM products WHERE id = :id"),
                {"id": product_id}
            )
            if result.first():
                skipped += 1
                continue
            
            # Create product
            attributes = {
                "parent_asin": parent_asin,
                "brand": prod_data.get('brand'),
                "store": prod_data.get('store'),
                "features": prod_data.get('features', []),
            }
            
            product = Product(
                id=product_id,
                name=prod_data['title'][:255],
                description=prod_data['description'][:2000] if prod_data['description'] else "No description",
                price=Decimal(str(prod_data['price'])),
                currency='INR',
                stock_quantity=100,
                image_url=prod_data['main_image_url'],
                thumbnail_url=prod_data.get('thumbnail_url') or prod_data['main_image_url'],
                attributes=attributes,
                category_id=category_id,
                seller_id=seller_id
            )
            session.add(product)
            created += 1
            
            if (created + skipped) % 100 == 0:
                session.flush()
                print(f"  Progress: {created} created, {skipped} skipped")
        
        session.flush()
        print(f"\n  [OK] Created {created} products ({skipped} skipped)")
        
        print("\n=== Creating Latent Item Mappings ===")
        # Map RetailRocket IDs (100000-300000) to product UUIDs
        result = session.execute(
            text("SELECT id FROM products ORDER BY id LIMIT 2000")
        )
        product_uuids = [row[0] for row in result]
        
        if len(product_uuids) < 2000:
            print(f"  WARNING: Only {len(product_uuids)} products available for mapping")
        
        # Create mappings for RetailRocket IDs
        retailrocket_start = 100000
        mapped_count = 0
        
        for i, product_uuid in enumerate(product_uuids):
            retailrocket_id = retailrocket_start + i
            
            # Check if exists
            result = session.execute(
                text("SELECT latent_item_id FROM latent_item_mappings WHERE latent_item_id = :rid"),
                {"rid": retailrocket_id}
            )
            if result.first():
                continue
            
            mapping = LatentItemMapping(
                latent_item_id=retailrocket_id,
                product_id=product_uuid,
                confidence_score=Decimal("0.95"),
                mapping_strategy="category_popularity"
            )
            session.add(mapping)
            mapped_count += 1
        
        session.flush()
        print(f"  [OK] Created {mapped_count} latent item mappings")
        
        # Commit all
        session.commit()
        
        print("\n" + "="*70)
        print("SEEDING COMPLETE")
        print("="*70)
        print(f"  Sellers: 1")
        print(f"  Categories: {len(category_ids)}")
        print(f"  Products: {created}")
        print(f"  Latent Mappings: {mapped_count}")
        print("="*70)
        
    except Exception as e:
        session.rollback()
        print(f"\nERROR: {e}")
        import traceback
        traceback.print_exc()
        raise
    finally:
        session.close()

if __name__ == "__main__":
    seed_kubernetes_catalog()
