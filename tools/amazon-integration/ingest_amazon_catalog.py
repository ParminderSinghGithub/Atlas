"""
Amazon Metadata Ingestion Tool

Purpose:
- Stream and filter Amazon Product Metadata 2023 JSONL files
- Extract ~2,000-3,000 products for realistic catalog
- Apply quality filters before loading into memory
- Normalize attributes for catalog compatibility

Input: meta_*.jsonl.gz files (already downloaded locally)
Output: Intermediate JSON file with processed products

Category Targets:
- Electronics: 700
- Cell Phones & Accessories: 600
- Sports & Outdoors: 500
- Software: 200
- Total: ~2,000

Quality Filters:
- price > $5
- valid image URL (prefer hi_res)
- non-empty title
- valid parent_asin (stable identifier)

Usage:
    python tools/ingest_amazon_catalog.py
"""
import gzip
import json
from pathlib import Path
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, asdict
from decimal import Decimal
import re

@dataclass
class AmazonProduct:
    """Normalized Amazon product for catalog ingestion."""
    parent_asin: str  # Stable Amazon identifier
    title: str
    description: str  # Joined from list
    features: List[str]
    price: float
    main_image_url: str
    thumbnail_url: Optional[str]
    brand: Optional[str]
    store: Optional[str]
    category_path: List[str]  # Raw category hierarchy
    raw_category: str  # Main category for grouping
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


class AmazonIngester:
    """Stream and filter Amazon metadata files."""
    
    # Category caps (stop when reached)
    CATEGORY_CAPS = {
        "Electronics": 700,
        "Cell_Phones_and_Accessories": 600,
        "Sports_and_Outdoors": 500,
        "Software": 200
    }
    
    # Minimum price threshold and conversion rate
    MIN_PRICE = 5.0
    USD_TO_INR = 90.0  # 1 USD = 90 INR
    
    def __init__(self, data_dir: Path):
        """
        Initialize ingester.
        
        Args:
            data_dir: Path to data/raw/amazon directory
        """
        self.data_dir = data_dir
        self.products: List[AmazonProduct] = []
        self.seen_asins: Set[str] = set()
        self.category_counts: Dict[str, int] = {cat: 0 for cat in self.CATEGORY_CAPS}
        self._price_samples_logged: int = 0

    def _detect_price_currency(self, item: Dict) -> str:
        """Best-effort currency guess for diagnostic logging."""
        for key in ("price", "list_price"):
            raw_value = item.get(key)
            if raw_value is None:
                continue
            raw_text = str(raw_value)
            if "$" in raw_text or "usd" in raw_text.lower():
                return "USD"
            if "inr" in raw_text.lower() or "₹" in raw_text:
                return "INR"
        return "unknown"
    
    def _extract_price(self, item: Dict) -> Optional[float]:
        """
        Extract price from various Amazon price fields.
        
        Amazon has inconsistent pricing:
        - price (string like "$99.99")
        - price_float (float)
        - list_price (sometimes present)
        
        Returns:
            Price as float, or None if invalid
        """
        # Try price field (string format)
        if 'price' in item and item['price']:
            price_str = str(item['price'])
            # Remove currency symbols and commas
            price_str = re.sub(r'[^\d.]', '', price_str)
            try:
                price = float(price_str)
                if price > self.MIN_PRICE:
                    return price
            except (ValueError, TypeError):
                pass
        
        # Try details field (nested dict)
        if 'details' in item and isinstance(item['details'], dict):
            if 'Price' in item['details']:
                price_str = str(item['details']['Price'])
                price_str = re.sub(r'[^\d.]', '', price_str)
                try:
                    price = float(price_str)
                    if price > self.MIN_PRICE:
                        return price
                except (ValueError, TypeError):
                    pass
        
        return None
    
    def _extract_images(self, item: Dict) -> tuple[Optional[str], Optional[str]]:
        """
        Extract best available image URLs.
        
        Priority:
        1. hi_res (highest quality)
        2. large (good quality)
        3. main_image_id from images dict
        
        Returns:
            (main_image_url, thumbnail_url)
        """
        main_url = None
        thumb_url = None
        
        # Try images array with hi_res
        if 'images' in item and isinstance(item['images'], list) and item['images']:
            first_image = item['images'][0]
            if isinstance(first_image, dict):
                # Prefer hi_res, fallback to large
                main_url = first_image.get('hi_res') or first_image.get('large')
                thumb_url = first_image.get('thumb') or first_image.get('large')
        
        # Fallback to main_image_id
        if not main_url and 'main_image_id' in item:
            # Construct Amazon image URL
            image_id = item['main_image_id']
            main_url = f"https://m.media-amazon.com/images/I/{image_id}._SL1500_.jpg"
            thumb_url = f"https://m.media-amazon.com/images/I/{image_id}._SL300_.jpg"
        
        return main_url, thumb_url
    
    def _extract_categories(self, item: Dict) -> tuple[List[str], str]:
        """
        Extract category hierarchy from Amazon metadata.
        
        Amazon category fields (inconsistent):
        - categories: list of category paths
        - category: list or string
        - main_category: string
        
        Returns:
            (category_path, main_category)
        """
        category_path = []
        main_category = "Other"
        
        # Try categories field (list of lists)
        if 'categories' in item and isinstance(item['categories'], list):
            if item['categories'] and isinstance(item['categories'][0], list):
                category_path = item['categories'][0]
        
        # Try category field
        if not category_path and 'category' in item:
            if isinstance(item['category'], list):
                category_path = item['category']
            else:
                category_path = [str(item['category'])]
        
        # Extract main category
        if 'main_category' in item:
            main_category = str(item['main_category'])
        elif category_path:
            main_category = category_path[0]
        
        return category_path, main_category
    
    def _normalize_description(self, item: Dict) -> str:
        """
        Extract and normalize product description.
        
        Amazon description fields:
        - description: list of strings (most common)
        - feature_bullets: list of strings
        - product_description: string
        
        Returns:
            Joined description text
        """
        descriptions = []
        
        # Try description list
        if 'description' in item and isinstance(item['description'], list):
            descriptions.extend([str(d) for d in item['description'] if d])
        
        # Try feature bullets
        if 'feature_bullets' in item and isinstance(item['feature_bullets'], list):
            descriptions.extend([str(f) for f in item['feature_bullets'] if f])
        
        # Try product_description
        if 'product_description' in item and item['product_description']:
            descriptions.append(str(item['product_description']))
        
        # Join and limit length
        full_description = " ".join(descriptions)
        return full_description[:2000] if full_description else "No description available"
    
    def _extract_features(self, item: Dict) -> List[str]:
        """Extract feature bullets/highlights."""
        features = []
        
        if 'features' in item and isinstance(item['features'], list):
            features.extend([str(f) for f in item['features'] if f])
        
        if 'feature_bullets' in item and isinstance(item['feature_bullets'], list):
            features.extend([str(f) for f in item['feature_bullets'] if f])
        
        return features[:10]  # Limit to 10 features
    
    def _passes_quality_filters(self, item: Dict) -> bool:
        """
        Check if product meets quality filters.
        
        Filters:
        - Has valid parent_asin
        - Has title
        - Has price > $5
        - Has image
        - Has description (not just "No description available")
        """
        # Check parent_asin
        if 'parent_asin' not in item or not item['parent_asin']:
            return False
        
        # Check title
        if 'title' not in item or not item['title']:
            return False
        
        # Check price
        price = self._extract_price(item)
        if not price or price <= self.MIN_PRICE:
            return False
        
        # Check images
        main_img, _ = self._extract_images(item)
        if not main_img:
            return False
        
        # Check description - must have real content
        has_real_description = False
        if 'description' in item and isinstance(item['description'], list) and item['description']:
            has_real_description = True
        elif 'feature_bullets' in item and isinstance(item['feature_bullets'], list) and item['feature_bullets']:
            has_real_description = True
        elif 'product_description' in item and item['product_description']:
            has_real_description = True
        
        if not has_real_description:
            return False
        
        return True
    
    def process_file(self, filepath: Path, dataset_category: str) -> int:
        """
        Stream and process a single Amazon metadata file.
        
        Args:
            filepath: Path to .jsonl.gz file
            dataset_category: Category name (e.g., "Electronics")
        
        Returns:
            Number of products ingested from this file
        """
        cap = self.CATEGORY_CAPS.get(dataset_category, 0)
        if self.category_counts[dataset_category] >= cap:
            print(f"  ⚠️  {dataset_category} already at cap ({cap}), skipping file")
            return 0
        
        count = 0
        filtered_count = 0
        
        print(f"  Processing {filepath.name}...")
        
        with gzip.open(filepath, 'rt', encoding='utf-8') as f:
            for line_num, line in enumerate(f, 1):
                # Check if category cap reached
                if self.category_counts[dataset_category] >= cap:
                    print(f"    Cap reached at line {line_num}")
                    break
                
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                
                # Apply quality filters
                if not self._passes_quality_filters(item):
                    filtered_count += 1
                    continue
                
                # Check for duplicates (by parent_asin)
                parent_asin = item['parent_asin']
                if parent_asin in self.seen_asins:
                    continue
                
                # Extract data
                price_usd = self._extract_price(item)
                price_inr = round(price_usd * self.USD_TO_INR, 2)  # Convert to INR
                main_img, thumb_img = self._extract_images(item)
                category_path, main_category = self._extract_categories(item)
                description = self._normalize_description(item)
                features = self._extract_features(item)

                if self._price_samples_logged < 3:
                    print(
                        "    Price sample | "
                        f"parent_asin={parent_asin} | "
                        f"raw_price={item.get('price') or item.get('details', {}).get('Price')} | "
                        f"detected_currency={self._detect_price_currency(item)} | "
                        f"normalized_usd={price_usd:.2f} | "
                        f"stored_inr={price_inr:.2f}"
                    )
                    self._price_samples_logged += 1
                
                # Create normalized product
                product = AmazonProduct(
                    parent_asin=parent_asin,
                    title=item['title'][:255],  # Limit title length
                    description=description,
                    features=features,
                    price=price_inr,  # Store in INR
                    main_image_url=main_img,
                    thumbnail_url=thumb_img,
                    brand=item.get('brand'),
                    store=item.get('store'),
                    category_path=category_path,
                    raw_category=dataset_category
                )
                
                self.products.append(product)
                self.seen_asins.add(parent_asin)
                self.category_counts[dataset_category] += 1
                count += 1
                
                if count % 100 == 0:
                    print(f"    Ingested {count} products (filtered {filtered_count})")
        
        print(f"  ✓ Ingested {count} products from {filepath.name} (filtered {filtered_count})")
        return count
    
    def ingest_all(self) -> List[AmazonProduct]:
        """
        Process all Amazon metadata files.
        
        Returns:
            List of normalized products
        """
        print("="*70)
        print("AMAZON METADATA INGESTION")
        print("="*70)
        
        # Process each category
        for category, cap in self.CATEGORY_CAPS.items():
            filepath = self.data_dir / f"meta_{category}.jsonl.gz"
            
            if not filepath.exists():
                print(f"  ⚠️  File not found: {filepath}")
                continue
            
            print(f"\n[{category}] Target: {cap} products")
            self.process_file(filepath, category)
        
        # Summary
        print("\n" + "="*70)
        print("INGESTION SUMMARY")
        print("="*70)
        for category, count in self.category_counts.items():
            cap = self.CATEGORY_CAPS[category]
            print(f"  {category:30s}: {count:4d} / {cap} ({count/cap*100:.1f}%)")
        
        total = sum(self.category_counts.values())
        print(f"\n  Total Products Ingested: {total}")
        print(f"  Unique ASINs: {len(self.seen_asins)}")
        print("="*70)
        
        return self.products
    
    def save_to_json(self, output_path: Path):
        """Save ingested products to JSON file."""
        print(f"\nSaving to {output_path}...")
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(
                [p.to_dict() for p in self.products],
                f,
                indent=2,
                ensure_ascii=False
            )
        
        print(f"✓ Saved {len(self.products)} products to {output_path}")


def main():
    """Run ingestion pipeline."""
    # Paths - adjust for new location
    project_root = Path(__file__).parent.parent.parent
    data_dir = project_root / "data" / "raw" / "amazon"
    output_dir = project_root / "tools" / "seed-data"
    output_file = output_dir / "amazon_products.json"
    
    # Validate input
    if not data_dir.exists():
        print(f"ERROR: Data directory not found: {data_dir}")
        return 1
    
    # Run ingestion
    ingester = AmazonIngester(data_dir)
    products = ingester.ingest_all()
    
    if not products:
        print("ERROR: No products ingested")
        return 1
    
    # Save output
    ingester.save_to_json(output_file)
    
    print("\n✓ Amazon metadata ingestion complete")
    return 0


if __name__ == "__main__":
    exit(main())
