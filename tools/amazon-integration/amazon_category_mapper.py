"""
Amazon Category Normalization and Mapping

Purpose:
- Normalize category hierarchies across Amazon datasets
- Create consistent, slug-safe category paths
- Map to 3-level hierarchy (max depth)
- Deduplicate equivalent categories

Input: amazon_products.json (from ingest_amazon_catalog.py)
Output: category_mappings.json with normalized hierarchy

Category Strategy:
- Preserve dataset grouping (Electronics, Cell Phones, etc.)
- Normalize subcategories within each dataset
- Create materialized paths for database storage
- Handle inconsistent Amazon category naming

Usage:
    python tools/amazon_category_mapper.py
"""
import json
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass, asdict
import re
from collections import defaultdict


@dataclass
class NormalizedCategory:
    """Normalized category with hierarchy."""
    name: str  # Display name
    slug: str  # URL-safe slug
    path: str  # Materialized path (/electronics/audio/headphones)
    parent_slug: Optional[str]  # Parent category slug
    level: int  # Depth in hierarchy (0 = root)
    product_count: int  # Number of products
    
    def to_dict(self) -> Dict:
        return asdict(self)


class CategoryMapper:
    """Normalize and map Amazon categories to flat hierarchy."""
    
    # Maximum category depth
    MAX_DEPTH = 3
    
    # Category normalization rules (clean up Amazon inconsistencies)
    NORMALIZATION_RULES = {
        # Remove noise words
        r'\s*\([^)]*\)': '',  # Remove parentheticals
        r'\s*\[[^\]]*\]': '',  # Remove brackets
        r'\s+': ' ',  # Normalize whitespace
        
        # Standard replacements
        'Cell Phones & Accessories': 'Cell Phones and Accessories',
        'Sports & Outdoors': 'Sports and Outdoors',
        '&amp;': 'and',
    }
    
    # Root categories (from dataset names)
    ROOT_CATEGORIES = {
        'Electronics': 'electronics',
        'Cell_Phones_and_Accessories': 'cell-phones',
        'Sports_and_Outdoors': 'sports',
        'Software': 'software'
    }
    
    def __init__(self):
        """Initialize category mapper."""
        self.categories: Dict[str, NormalizedCategory] = {}
        self.category_products: Dict[str, List[str]] = defaultdict(list)  # slug -> asin list
        self.slug_counter: Dict[str, int] = defaultdict(int)
    
    def _normalize_name(self, name: str) -> str:
        """
        Normalize category name.
        
        Rules:
        - Remove parentheticals and brackets
        - Replace & with 'and'
        - Trim whitespace
        - Title case
        """
        name = str(name).strip()
        
        # Apply normalization rules
        for pattern, replacement in self.NORMALIZATION_RULES.items():
            if '->' in pattern:
                # Direct string replacement
                old, new = pattern.split('->')
                name = name.replace(old.strip(), new.strip())
            else:
                # Regex replacement
                name = re.sub(pattern, replacement, name)
        
        name = name.strip()
        
        # Title case
        if name:
            name = ' '.join(word.capitalize() for word in name.split())
        
        return name or "Other"
    
    def _create_slug(self, name: str, ensure_unique: bool = False) -> str:
        """
        Create URL-safe slug from category name.
        
        Rules:
        - Lowercase
        - Replace spaces with hyphens
        - Remove special characters
        - Ensure uniqueness if requested
        """
        slug = name.lower()
        
        # Replace spaces and underscores with hyphens
        slug = re.sub(r'[\s_]+', '-', slug)
        
        # Remove special characters (keep alphanumeric and hyphens)
        slug = re.sub(r'[^a-z0-9-]', '', slug)
        
        # Remove multiple consecutive hyphens
        slug = re.sub(r'-+', '-', slug)
        
        # Remove leading/trailing hyphens
        slug = slug.strip('-')
        
        # Ensure uniqueness if requested
        if ensure_unique and slug in self.slug_counter:
            self.slug_counter[slug] += 1
            slug = f"{slug}-{self.slug_counter[slug]}"
        else:
            self.slug_counter[slug] = 0
        
        return slug or "other"
    
    def _extract_category_hierarchy(
        self, 
        category_path: List[str], 
        raw_category: str
    ) -> List[Tuple[str, str]]:
        """
        Extract normalized category hierarchy.
        
        Args:
            category_path: Raw Amazon category path
            raw_category: Dataset category (Electronics, etc.)
        
        Returns:
            List of (name, slug) tuples, limited to MAX_DEPTH
        """
        hierarchy = []
        
        # Root category from dataset
        root_name = raw_category.replace('_', ' ')
        root_slug = self.ROOT_CATEGORIES.get(raw_category, self._create_slug(root_name))
        hierarchy.append((self._normalize_name(root_name), root_slug))
        
        # Process Amazon category path
        if category_path and isinstance(category_path, list):
            # Skip first element if it matches root
            start_idx = 0
            if category_path and self._normalize_name(category_path[0]) == root_name:
                start_idx = 1
            
            # Add subcategories (limit depth)
            for cat_name in category_path[start_idx:self.MAX_DEPTH-1]:
                if cat_name:
                    normalized = self._normalize_name(cat_name)
                    if normalized and normalized not in [h[0] for h in hierarchy]:
                        slug = self._create_slug(normalized)
                        hierarchy.append((normalized, slug))
        
        # Ensure at least 1 level (root)
        if not hierarchy:
            hierarchy.append(("Other", "other"))
        
        return hierarchy[:self.MAX_DEPTH]
    
    def process_products(self, products: List[Dict]) -> Dict[str, NormalizedCategory]:
        """
        Process products and build category hierarchy.
        
        Args:
            products: List of product dicts from ingestion
        
        Returns:
            Dict of slug -> NormalizedCategory
        """
        print("="*70)
        print("CATEGORY NORMALIZATION")
        print("="*70)
        
        category_counts: Dict[str, int] = defaultdict(int)
        
        for product in products:
            # Extract hierarchy
            hierarchy = self._extract_category_hierarchy(
                product.get('category_path', []),
                product.get('raw_category', 'Other')
            )
            
            # Build path incrementally
            path_parts = []
            parent_slug = None
            
            for level, (name, slug) in enumerate(hierarchy):
                path_parts.append(slug)
                path = '/' + '/'.join(path_parts)
                
                # Create or update category
                if slug not in self.categories:
                    self.categories[slug] = NormalizedCategory(
                        name=name,
                        slug=slug,
                        path=path,
                        parent_slug=parent_slug,
                        level=level,
                        product_count=0
                    )
                
                # Track product association (use leaf category only)
                if level == len(hierarchy) - 1:
                    self.category_products[slug].append(product['parent_asin'])
                    category_counts[slug] += 1
                
                parent_slug = slug
        
        # Update product counts
        for slug, count in category_counts.items():
            if slug in self.categories:
                self.categories[slug].product_count = count
        
        # Summary
        print(f"\n  Total Categories: {len(self.categories)}")
        print(f"  Root Categories: {len([c for c in self.categories.values() if c.level == 0])}")
        print(f"  Level 1: {len([c for c in self.categories.values() if c.level == 1])}")
        print(f"  Level 2: {len([c for c in self.categories.values() if c.level == 2])}")
        
        print("\n  Top Categories by Product Count:")
        sorted_categories = sorted(
            self.categories.values(),
            key=lambda c: c.product_count,
            reverse=True
        )[:10]
        
        for cat in sorted_categories:
            indent = "  " * (cat.level + 1)
            print(f"{indent}{cat.name:30s} ({cat.product_count} products)")
        
        print("="*70)
        
        return self.categories
    
    def save_mappings(self, output_path: Path):
        """Save category mappings to JSON."""
        print(f"\nSaving category mappings to {output_path}...")
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Convert to serializable format
        output = {
            'categories': {
                slug: cat.to_dict() 
                for slug, cat in self.categories.items()
            },
            'category_products': dict(self.category_products),
            'stats': {
                'total_categories': len(self.categories),
                'root_categories': len([c for c in self.categories.values() if c.level == 0]),
                'max_depth': max((c.level for c in self.categories.values()), default=0) + 1
            }
        }
        
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)
        
        print(f"✓ Saved {len(self.categories)} categories")


from typing import Optional  # Add missing import


def main():
    """Run category normalization pipeline."""
    # Paths - adjust for new location
    project_root = Path(__file__).parent.parent.parent
    input_file = project_root / "tools" / "seed-data" / "amazon_products.json"
    output_file = project_root / "tools" / "seed-data" / "category_mappings.json"
    
    # Validate input
    if not input_file.exists():
        print(f"ERROR: Input file not found: {input_file}")
        print("Run ingest_amazon_catalog.py first")
        return 1
    
    # Load products
    print(f"Loading products from {input_file}...")
    with open(input_file, 'r', encoding='utf-8') as f:
        products = json.load(f)
    
    print(f"✓ Loaded {len(products)} products")
    
    # Normalize categories
    mapper = CategoryMapper()
    categories = mapper.process_products(products)
    
    # Save mappings
    mapper.save_mappings(output_file)
    
    print("\n✓ Category normalization complete")
    return 0


if __name__ == "__main__":
    exit(main())
