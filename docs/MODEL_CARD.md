# Model Card: LightGBM Ranker

**Model Name:** LightGBM Learning-to-Rank (LambdaRank)  
**Model Version:** 1.0  
**Trained:** December 27, 2025  
**Framework:** LightGBM 4.6.0  
**Document Purpose:** ML model transparency and reproducibility (inspired by Model Cards for Model Reporting, Mitchell et al. 2019)

---

## Model Overview

### Purpose
Rank candidate products for personalized e-commerce recommendations. Given a user and a set of products, predict purchase likelihood and sort by relevance.

### Intended Use
- **Production use case:** Re-rank top-50 candidate products for real-time recommendations
- **Input:** User ID + 50 candidate product IDs
- **Output:** Sorted list of 10 products (highest predicted purchase probability first)

### Out-of-Scope Use
- ❌ Candidate generation (use SVD/Item-Item for retrieval)
- ❌ Cold-start users with 0 events (fallback to popularity baseline)
- ❌ Explainable AI (requires SHAP values post-processing, not built-in)

---

## Training Data

### Dataset: RetailRocket E-commerce Events
**Source:** [Kaggle - RetailRocket Dataset](https://www.kaggle.com/datasets/retailrocket/ecommerce-dataset)

**Statistics:**
- **Total events:** 2,756,101 events
- **Unique users:** 1,407,580 users
- **Unique products:** 235,061 products
- **Time range:** May 3, 2015 - September 18, 2015 (137 days)

**Event types:**
- Views: 2,664,312 (96.7%)
- Add to cart: 69,332 (2.5%)
- Purchase: 22,457 (0.8%)

**Train/Val Split:**
- **Method:** Time-based split (80% train, 20% validation)
- **Training samples:** 1,716,144 events
- **Validation samples:** 429,035 events
- **Rationale:** Prevents data leakage (validation is future behavior)

**Preprocessing:**
- Schema mapping: RetailRocket → Internal event schema
- Feature engineering: 3 feature tables (user_features, item_features, interaction_features)
- See: [DATA_CARD.md](DATA_CARD.md)

---

## Features

### Feature Schema (16 Features Total)

#### User Features (8 features)
| Feature | Type | Description | Example Value |
|---------|------|-------------|---------------|
| `user_total_events` | Integer | Total events by user | 42 |
| `user_unique_products_interacted` | Integer | Distinct products viewed | 15 |
| `user_unique_sessions` | Integer | Number of sessions | 8 |
| `user_add_to_cart_count` | Integer | Cart additions | 3 |
| `user_purchase_count` | Integer | Total purchases | 1 |
| `user_views_count` | Integer | View events | 38 |
| `user_recency_days` | Float | Days since last event | 2.5 |

**Unused user feature:** `last_event_ts` (timestamp not used, only recency_days)

#### Item Features (7 features)
| Feature | Type | Description | Example Value |
|---------|------|-------------|---------------|
| `item_total_views` | Integer | Total views for product | 1,234 |
| `item_total_add_to_cart` | Integer | Cart additions | 45 |
| `item_total_purchases` | Integer | Total purchases | 23 |
| `item_popularity_score` | Float | log1p(total_interactions) | 7.12 |
| `item_conversion_rate` | Float | purchases / views | 0.019 |
| `item_recency_days` | Float | Days since last interaction | 5.3 |

**Unused item feature:** `last_interaction_ts` (timestamp not used)

#### Interaction Features (3 features)
| Feature | Type | Description | Example Value |
|---------|------|-------------|---------------|
| `interaction_count` | Integer | User-product event count | 5 |
| `has_purchased` | Binary | User purchased this product? | 1 |
| `recency_days` | Float | Days since last interaction | 1.2 |

**Unused interaction feature:** `last_interaction_ts`

---

## Feature Importance

**Top 10 Features (LightGBM gain-based importance):**

| Rank | Feature | Importance | % of Total | Interpretation |
|------|---------|------------|------------|----------------|
| 1 | `interaction_count` | 87,789 | 44.3% | Users who interacted multiple times are far more likely to purchase |
| 2 | `has_purchased` | 38,330 | 19.3% | **Strongest binary signal** - past purchase predicts future |
| 3 | `item_total_add_to_cart` | 25,806 | 13.0% | Popular "add to cart" products have higher conversion |
| 4 | `user_purchase_count` | 18,223 | 9.2% | Frequent buyers purchase again (repeat customer signal) |
| 5 | `user_views_count` | 8,146 | 4.1% | High browser engagement correlates with eventual purchase |
| 6 | `item_total_purchases` | 6,342 | 3.2% | Products with many purchases are high quality |
| 7 | `user_add_to_cart_count` | 5,234 | 2.6% | Users who use cart feature have higher intent |
| 8 | `item_popularity_score` | 4,123 | 2.1% | Log-scaled popularity prevents blockbuster dominance |
| 9 | `user_total_events` | 3,567 | 1.8% | Engaged users are valuable customers |
| 10 | `user_unique_products_interacted` | 2,891 | 1.5% | Exploration breadth indicates shopping intent |

**Lowest Importance Features:**
- `recency_days` features (user, item, interaction) - Less predictive than expected
- `item_conversion_rate` - Raw counts dominate over rates

**Key Insight:** Interaction history (features 1-2) accounts for 63.6% of model decisions. Cold-start scenarios (new users/products) must rely on fallback strategies.

---

## Hyperparameters

```python
params = {
    'objective': 'lambdarank',        # Learning-to-rank objective
    'metric': 'ndcg',                 # Optimize NDCG
    'ndcg_eval_at': [10],             # NDCG@10 specifically
    'learning_rate': 0.05,            # Conservative learning rate
    'num_leaves': 31,                 # Tree complexity (default)
    'feature_fraction': 0.8,          # 80% feature sampling (prevents overfitting)
    'bagging_fraction': 0.8,          # 80% data sampling (row subsampling)
    'bagging_freq': 5,                # Bagging every 5 iterations
    'verbose': -1,                    # Suppress training logs
    'seed': 42                        # Reproducibility
}
num_boost_round = 100                 # 100 boosting iterations
```

**Tuning Notes:**
- Default hyperparameters used (no grid search)
- Future improvement: Optuna hyperparameter optimization
- `feature_fraction=0.8` prevents overfitting to noisy features
- `learning_rate=0.05` is conservative (could increase to 0.1 for faster training)

---

## Performance Metrics

### Offline Evaluation (Validation Set)

| Metric | Value | Interpretation |
|--------|-------|----------------|
| **NDCG@10** | **0.9992** | Near-perfect ranking of top-10 items |
| **Recall@10** | **0.9908** | 99.1% of relevant items appear in top-10 |
| **Precision@10** | **0.4728** | 47.3% of top-10 recommendations are relevant |

---

### ⚠️ Offline Metric Caveats

**CRITICAL WARNING:** NDCG@10 = 0.9992 is **suspiciously high** and comes with important caveats:

1. **Strong Label Bias**
   - Validation set includes items users DID purchase (not unseen items)
   - Model ranks known purchases, not discovers new products
   - This inflates NDCG (easier task than production)

2. **Historical Replay**
   - Offline evaluation measures "Can we predict the past?"
   - Production measures "Can we influence the future?"
   - Very different questions

3. **No Position Bias Correction**
   - Model trained on organic user behavior (users click top results)
   - Position bias not corrected (top-ranked items in training data stay top-ranked)

4. **No Novelty/Diversity Metrics**
   - NDCG optimizes accuracy, not serendipity
   - Users may want surprising recommendations, not just "obvious" ones

5. **Offline-Online Gap**
   - **Expected online performance:** 50-70% of offline NDCG
   - **Expected online CTR:** 2-4% (industry benchmark)
   - **Recommendation:** Always A/B test before claiming success

**Metadata Flag:** `offline_metric_caveat: true` in `model_metadata.json`

---

### Comparison to Baselines

| Model | NDCG@10 | Improvement vs Baseline |
|-------|---------|-------------------------|
| Popularity Baseline | 0.4234 | - |
| SVD (10 components) | 0.6835 | +61.5% |
| **LightGBM Ranker** | **0.9992** | **+136.0%** |
| Two-Stage Pipeline | 0.9932 | +134.6% |

**Key Takeaway:** LightGBM vastly outperforms simpler methods due to rich feature engineering (16 features vs SVD's interaction matrix only).

---

## Model Architecture

### LightGBM Ranker Details
**Objective:** LambdaRank (pairwise ranking loss with NDCG gradient)

**Algorithm:**
1. For each user, create pairs of (relevant_item, irrelevant_item)
2. Compute pairwise loss: `loss = max(0, margin - (score_relevant - score_irrelevant))`
3. Weight loss by NDCG gradient (higher weight for top-ranked mistakes)
4. Gradient boosting: iteratively add trees to minimize loss

**Tree Structure:**
- **Boost rounds:** 100 trees
- **Leaves per tree:** 31 leaves
- **Max depth:** Not specified (LightGBM grows leaf-wise, not depth-wise)
- **Total parameters:** ~3,100 split points across 100 trees

**Inference:**
```python
import lightgbm as lgb

model = lgb.Booster(model_file='lightgbm_ranker.txt')
scores = model.predict(feature_matrix)  # [50 candidates → 50 scores]
ranked_indices = scores.argsort()[::-1]
top_10 = candidates[ranked_indices[:10]]
```

**Latency:** ~8ms for 50 candidates (local machine, Intel i7)

---

## Training Procedure

### Data Preparation
1. Load events from Parquet file (2.7M rows)
2. Time-based split: 80% train (events before Aug 1), 20% val (Aug 1 - Sep 18)
3. Load feature tables (user_features, item_features, interaction_features)
4. Merge events with features (left join on user_id, product_id)
5. Create LightGBM Dataset with group information (one group per user)

### Training Configuration
```python
train_data = lgb.Dataset(
    X_train,
    label=y_train,
    group=train_groups,  # Group by user (critical for ranking)
    feature_name=feature_names
)

model = lgb.train(
    params,
    train_data,
    num_boost_round=100,
    valid_sets=[val_data],
    valid_names=['validation']
)
```

**Training Time:** ~2 minutes (1.7M samples, 16 features, 100 boost rounds)

**Hardware:** Intel i7, 16GB RAM, no GPU

---

## Limitations & Biases

### 1. Cold-Start Problem
**Issue:** Model requires user and item features. New users/products have incomplete features.

**Impact:** NDCG degrades for users with <5 events

**Mitigation:** Fallback to popularity baseline or category-based recommendations

---

### 2. Popularity Bias
**Issue:** Model learns that popular products have higher purchase rates

**Impact:** Long-tail products (niche items) are under-recommended

**Evidence:** Feature importance shows `item_popularity_score` is rank 8 (2.1% of decisions)

**Mitigation:** Add diversity constraints in decisioning layer

---

### 3. Temporal Drift
**Issue:** Model trained on May-Sep 2015 data. User behavior may change over time (seasonality, trends)

**Impact:** Model may not generalize to 2026 behavior

**Mitigation:** Retrain model monthly on recent data

---

### 4. Single-Domain Training
**Issue:** Model trained only on RetailRocket dataset (Russian e-commerce platform)

**Impact:** May not generalize to US/EU markets with different behavior patterns

**Mitigation:** Fine-tune on P1 production data after launch

---

### 5. Position Bias
**Issue:** Training data reflects organic clicks (users click top results). Model learns position bias.

**Impact:** Items ranked high in training data stay high (self-reinforcing loop)

**Mitigation:** Apply inverse propensity scoring (future work)

---

### 6. Conversion Rate Paradox
**Issue:** Low conversion rate in data (0.8% purchase rate)

**Impact:** Model trained on 99.2% negative examples (class imbalance)

**Evidence:** `has_purchased` is top-2 feature (19.3% importance) despite only 0.8% positive labels

**Mitigation:** LambdaRank handles class imbalance naturally (optimizes ranking, not classification)

---

## Ethical Considerations

### Filter Bubble Risk
**Concern:** Model recommends products similar to past purchases, limiting user exploration

**Evidence:** Top-2 features are interaction-based (44% + 19% = 63% of decisions)

**Mitigation:** Add epsilon-greedy exploration (10% random recommendations)

---

### Price Discrimination
**Concern:** Model could learn user price sensitivity and recommend more expensive items to high-spending users

**Evidence:** Price feature not included in model (mitigates risk)

**Future Risk:** If user income/demographic features added, monitor for discriminatory pricing

---

### Diversity & Inclusion
**Concern:** Model trained on 2015 data may reflect outdated biases (e.g., gendered product categories)

**Evidence:** Category hierarchy in RetailRocket may have implicit gender stereotypes

**Mitigation:** Audit product categories, ensure inclusive language in catalog

---

## Model Artifacts

### Saved Files
**Location:** `notebooks/artifacts/models/`

| File | Size | Description |
|------|------|-------------|
| `lightgbm_ranker.txt` | 3.2 MB | Booster text file (loadable with lgb.Booster) |
| `model_metadata.json` | 2 KB | Hyperparameters, features, metrics, training date |
| `feature_importance.csv` | 1 KB | Feature importance scores (sorted) |
| `model_comparison.csv` | 0.5 KB | NDCG comparison across all models |

### Model Loading
```python
import lightgbm as lgb

model = lgb.Booster(model_file='artifacts/models/lightgbm_ranker.txt')
```

### Feature Engineering Dependencies
- `user_features.parquet` (1.4M rows, 9 columns)
- `item_features.parquet` (235K rows, 8 columns)
- `interaction_features.parquet` (2.1M rows, 6 columns)

**Total artifact size:** ~2.5 GB (model + features)

---

## Maintenance & Updates

### Retraining Cadence
**Recommended:** Monthly retraining on most recent 90 days of data

**Triggers for retraining:**
- NDCG drops >10% from baseline
- CTR drops >15% from baseline
- New product categories added (model needs to learn new patterns)

### Monitoring
**Key Metrics:**
- **Online NDCG:** Track ranking quality on production traffic
- **CTR:** Click-through rate (target: >3%)
- **Conversion Rate:** Purchase rate (target: >0.5%)
- **Feature Drift:** Monitor feature distributions (e.g., has `item_popularity_score` shifted?)

**Alert Conditions:**
- CTR drops >20% week-over-week
- Error rate >1% (model serving failures)
- Latency p99 >50ms

---

## References

- **Data Card:** [DATA_CARD.md](DATA_CARD.md)
- **Phase 1 Documentation:** [PHASE_1_OFFLINE_ML_SYSTEM.md](PHASE_1_OFFLINE_ML_SYSTEM.md)
- **Recommendation System:** [RECOMMENDATION_SYSTEM_OVERVIEW.md](RECOMMENDATION_SYSTEM_OVERVIEW.md)
- **Training Notebook:** [../notebooks/04_model_training.ipynb](../notebooks/04_model_training.ipynb)
- **Feature Schema:** [../notebooks/artifacts/features/retailrocket/feature_schema.json](../notebooks/artifacts/features/retailrocket/feature_schema.json)

---

## Contact

**Model Owner:** P1 ML Team  
**Last Updated:** December 28, 2025  
**Model Version:** 1.0  
**Next Review Date:** January 28, 2026 (monthly retraining)

---

**Document Status:** Complete  
**Intended Audience:** ML engineers, data scientists, compliance/audit teams  
**Inspired By:** Model Cards for Model Reporting (Mitchell et al., 2019)
