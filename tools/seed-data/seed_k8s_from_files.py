#!/usr/bin/env python3
"""
K8s Database Seeding - Loads from local JSON files
Expects amazon_products.json and category_mappings.json in /tmp/
"""
import uuid
import json
from pathlib import Path
from sqlalchemy import create_engine, text

def seed_database():
    """Seed database with Amazon products from files"""
    db_url = "postgresql://postgres:postgres@postgres:5432/ecommerce"
    engine = create_engine(db_url, echo=False)
    
    # Load data files
    products_path = Path("/tmp/amazon_products.json")
    categories_path = Path("/tmp/category_mappings.json")
    
    if not products_path.exists():
        print(f"❌ ERROR: {products_path} not found")
        return
    
    if not categories_path.exists():
        print(f"❌ ERROR: {categories_path} not found")
        return
    
    print("📂 Loading product data...")
    with open(products_path, encoding='utf-8') as f:
        PRODUCTS = json.load(f)
    
    with open(categories_path, encoding='utf-8') as f:
        CATEGORIES = json.load(f)
    
    print(f"✓ Loaded {len(PRODUCTS)} products")
    
    print("🔗 Connecting to database...")
    with engine.begin() as conn:
        # Insert categories from mapping
        cat_list = list(CATEGORIES['categories'].items())
        cat_list.sort(key=lambda x: x[1].get('level', 0))
        
        print(f"📦 Seeding {len(cat_list)} categories...")
        category_id_map = {}
        
        for slug, cat_data in cat_list:
            cat_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"category_{slug}")
            parent_id = None
            if cat_data.get('parent_slug'):
                parent_id = category_id_map.get(cat_data['parent_slug'])
            
            conn.execute(text("""
                INSERT INTO categories (id, slug, name, description, path, parent_id, display_order, created_at, updated_at)
                VALUES (:id, :slug, :name, :desc, :path, :parent_id, :display_order, now(), now())
                ON CONFLICT (id) DO NOTHING
            """), {
                "id": str(cat_id),
                "slug": slug,
                "name": cat_data['name'],
                "desc": f"{cat_data['name']} products from Amazon catalog",
                "path": cat_data.get('path', slug),
                "parent_id": str(parent_id) if parent_id else None,
                "display_order": cat_data.get('level', 0)
            })
            category_id_map[slug] = cat_id
        
        # Insert products in batches
        print(f"🛒 Seeding {len(PRODUCTS)} products...")
        batch_size = 100
        for batch_num in range(0, len(PRODUCTS), batch_size):
            batch = PRODUCTS[batch_num:batch_num + batch_size]
            
            for p in batch:
                prod_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"amazon_{p['parent_asin']}")
                
                # Map to category
                category_slug = p.get('raw_category', 'other').lower().replace(' ', '-').replace('_', '-')
                if 'and' in category_slug:
                    category_slug = category_slug.replace('-and-', '-')
                
                cat_id = category_id_map.get(category_slug)
                if not cat_id:
                    for slug in category_id_map:
                        if category_slug in slug or slug in category_slug:
                            cat_id = category_id_map[slug]
                            break
                
                if not cat_id:
                    cat_id = list(category_id_map.values())[0]
                
                conn.execute(text("""
                    INSERT INTO products (id, category_id, name, description, price, image_url, stock_quantity, created_at, updated_at)
                    VALUES (:id, :cat, :name, :desc, :price, :img, :stock, now(), now())
                    ON CONFLICT (id) DO NOTHING
                """), {
                    "id": str(prod_id),
                    "cat": str(cat_id),
                    "name": p['title'][:200],
                    "desc": p['description'][:500],
                    "price": float(p['price']) / 90.0,  # Convert INR to USD
                    "img": p['main_image_url'],
                    "stock": 100
                })
            
            if (batch_num + batch_size) % 500 == 0 or batch_num + batch_size >= len(PRODUCTS):
                print(f"  ✓ Seeded {min(batch_num + batch_size, len(PRODUCTS))} / {len(PRODUCTS)} products...")
        
        # Insert latent mappings in batches
        print(f"🔗 Creating {len(PRODUCTS)} latent mappings...")
        retailrocket_start = 100000
        for batch_num in range(0, len(PRODUCTS), batch_size):
            batch = PRODUCTS[batch_num:batch_num + batch_size]
            
            for i, p in enumerate(batch):
                global_idx = batch_num + i
                prod_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"amazon_{p['parent_asin']}")
                mapping_id = uuid.uuid5(uuid.NAMESPACE_DNS, f"mapping_{retailrocket_start + global_idx}")
                
                conn.execute(text("""
                    INSERT INTO latent_item_mappings (id, latent_item_id, product_id, mapping_strategy, confidence_score)
                    VALUES (:id, :rr_id, :prod_id, :strategy, :conf)
                    ON CONFLICT (latent_item_id) DO NOTHING
                """), {
                    "id": str(mapping_id),
                    "rr_id": retailrocket_start + global_idx,
                    "prod_id": str(prod_id),
                    "strategy": "category_popularity",
                    "conf": 0.85
                })
            
            if (batch_num + batch_size) % 500 == 0 or batch_num + batch_size >= len(PRODUCTS):
                print(f"  ✓ Created {min(batch_num + batch_size, len(PRODUCTS))} / {len(PRODUCTS)} mappings...")
        
        # Verify seeding
        result = conn.execute(text("SELECT COUNT(*) FROM products")).scalar()
        mappings = conn.execute(text("SELECT COUNT(*) FROM latent_item_mappings")).scalar()
        print(f"\n✅ Seeding complete!")
        print(f"   Products: {result}")
        print(f"   Mappings: {mappings}")

if __name__ == "__main__":
    try:
        seed_database()
    except Exception as e:
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        raise
