"""
Decisioning rules for post-ranking filtering.

Why post-ranking rules:
- ML model optimizes for relevance
- Business rules ensure user experience quality
- Diversity prevents filter bubble

Rules applied (in order):
1. Deduplication (no repeated items)
2. Stock filtering (exclude out-of-stock)
3. Category diversity (max N per category)
4. Recency (prefer newer products)
"""
from typing import List, Dict, Any
from collections import defaultdict
from uuid import UUID

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def deduplicate(product_ids: List[UUID]) -> List[UUID]:
    """
    Remove duplicate product IDs while preserving order.
    
    Why preserve order:
    - Order reflects ML ranking
    - First occurrence is highest-ranked
    """
    seen = set()
    unique = []
    for pid in product_ids:
        if pid not in seen:
            seen.add(pid)
            unique.append(pid)
    
    if len(unique) < len(product_ids):
        logger.debug(f"Deduplication: {len(product_ids)} → {len(unique)}")
    
    return unique


def apply_diversity_constraint(
    product_ids: List[UUID],
    product_metadata: Dict[UUID, Dict[str, Any]],
    max_per_category: int = None
) -> List[UUID]:
    """
    Enforce category diversity.
    
    Args:
        product_ids: Ranked list of product UUIDs
        product_metadata: Dict of product_id → {category_id, ...}
        max_per_category: Maximum items from same category (default from config)
    
    Returns:
        Filtered list with diversity constraint applied
    
    Why diversity:
    - Prevents "headphones, headphones, headphones" recommendations
    - Improves perceived relevance
    - Encourages exploration
    """
    max_per_category = max_per_category or settings.max_items_per_category
    
    category_counts = defaultdict(int)
    diverse_products = []
    
    for pid in product_ids:
        metadata = product_metadata.get(pid, {})
        category_id = metadata.get('category_id')
        
        # If no category metadata, allow (safer than rejecting)
        if category_id is None:
            diverse_products.append(pid)
            continue
        
        # Check category limit
        if category_counts[category_id] < max_per_category:
            diverse_products.append(pid)
            category_counts[category_id] += 1
    
    if len(diverse_products) < len(product_ids):
        logger.debug(
            f"Diversity constraint: {len(product_ids)} → {len(diverse_products)} | "
            f"max_per_category={max_per_category}"
        )
    
    return diverse_products


def filter_out_of_stock(
    product_ids: List[UUID],
    product_metadata: Dict[UUID, Dict[str, Any]]
) -> List[UUID]:
    """
    Remove out-of-stock products.
    
    Args:
        product_ids: List of product UUIDs
        product_metadata: Dict of product_id → {stock_quantity, ...}
    
    Returns:
        Filtered list with only in-stock products
    
    Why filter:
    - Can't buy out-of-stock items
    - Frustrating user experience
    - Better to show fewer high-quality recs than many unusable ones
    """
    in_stock = []
    
    for pid in product_ids:
        metadata = product_metadata.get(pid, {})
        stock_quantity = metadata.get('stock_quantity', 0)
        
        # Include if stock > 0
        if stock_quantity > 0:
            in_stock.append(pid)
    
    if len(in_stock) < len(product_ids):
        logger.debug(f"Stock filter: {len(product_ids)} → {len(in_stock)}")
    
    return in_stock


def filter_inactive(
    product_ids: List[UUID],
    product_metadata: Dict[UUID, Dict[str, Any]]
) -> List[UUID]:
    """
    Remove soft-deleted or inactive products.
    
    Args:
        product_ids: List of product UUIDs
        product_metadata: Dict of product_id → {is_deleted, ...}
    
    Returns:
        Filtered list with only active products
    """
    active = []
    
    for pid in product_ids:
        metadata = product_metadata.get(pid, {})
        is_deleted = metadata.get('is_deleted', False)
        
        if not is_deleted:
            active.append(pid)
    
    if len(active) < len(product_ids):
        logger.debug(f"Active filter: {len(product_ids)} → {len(active)}")
    
    return active


async def apply_all_rules(
    product_ids: List[UUID],
    product_metadata: Dict[UUID, Dict[str, Any]]
) -> List[UUID]:
    """
    Apply all decisioning rules in sequence.
    
    Order matters:
    1. Deduplicate (cheap, reduces downstream work)
    2. Filter inactive (safety)
    3. Filter stock (business rule)
    4. Diversity (quality)
    
    Returns:
        Final filtered and ordered list
    """
    logger.debug(f"Applying decisioning rules | input={len(product_ids)} products")
    
    # Step 1: Deduplication
    products = deduplicate(product_ids)
    
    # Step 2: Remove inactive
    products = filter_inactive(products, product_metadata)
    
    # Step 3: Remove out-of-stock
    products = filter_out_of_stock(products, product_metadata)
    
    # Step 4: Apply diversity
    products = apply_diversity_constraint(products, product_metadata)
    
    logger.debug(f"Decisioning complete | output={len(products)} products")
    return products
