"""
Quick script to generate missing popularity_model.pkl artifact.
This uses the same logic as the recommendation service fallback.
"""
import pickle
import pandas as pd
from pathlib import Path

def create_popularity_artifact():
    """Generate popularity_baseline.pkl from item_features.parquet"""
    
    # Paths
    features_path = Path("notebooks/artifacts/features/retailrocket/item_features.parquet")
    output_path = Path("notebooks/artifacts/models/popularity_baseline.pkl")
    
    if not features_path.exists():
        print(f"ERROR: {features_path} not found")
        return False
    
    # Load item features
    print(f"Loading item features from {features_path}...")
    item_features = pd.read_parquet(features_path)
    print(f"Loaded {len(item_features)} items")
    
    # Determine popularity column
    popularity_col = None
    for col in ['total_views', 'view_count', 'interaction_count', 'purchase_count', 'popularity_score']:
        if col in item_features.columns:
            popularity_col = col
            break
    
    if not popularity_col:
        print("ERROR: No popularity column found in item_features")
        return False
    
    print(f"Using column: {popularity_col}")
    
    # Use product_id as index (converted to int)
    if 'product_id' in item_features.columns:
        item_features['product_id_int'] = item_features['product_id'].astype(int)
        item_features = item_features.set_index('product_id_int')
    
    # Create popularity series
    popularity_scores = item_features[popularity_col].sort_values(ascending=False)
    
    print(f"Generated popularity scores for {len(popularity_scores)} items")
    print(f"Top 5 items: {popularity_scores.head().to_dict()}")
    
    # Save artifact
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'wb') as f:
        pickle.dump(popularity_scores, f)
    
    print(f"✓ Saved to {output_path}")
    print(f"  File size: {output_path.stat().st_size / 1024:.1f} KB")
    
    return True

if __name__ == "__main__":
    success = create_popularity_artifact()
    exit(0 if success else 1)
