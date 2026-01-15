# Data Card: Multi-Dataset E-commerce Platform

**Dataset Name:** P1 Hybrid Dataset (RetailRocket + Amazon Product Metadata)  
**Version:** 2.0  
**Sources:**
- **Behavior Data:** [Kaggle - RetailRocket Dataset](https://www.kaggle.com/datasets/retailrocket/ecommerce-dataset)
- **Catalog Data:** [Amazon Product Metadata 2023](https://amazon-reviews-2023.github.io/) (Hou et al., 2024)

**Acquired:** November 2025 (RetailRocket), December 2025 (Amazon)  
**Document Purpose:** Dataset transparency and reproducibility (inspired by Datasheets for Datasets, Gebru et al. 2018)

---

## Dataset Overview

### Purpose
This platform uses a **hybrid approach** combining two complementary datasets:

1. **RetailRocket (Behavior Learning)**
   - Real-world user behavior events (2.7M events)
   - Train recommendation models (SVD, LightGBM)
   - Learn interaction patterns and ranking signals
   - **NEVER exposed to end users**

2. **Amazon Product Metadata 2023 (Catalog Realism)**
   - Real product information (titles, images, prices, descriptions)
   - Production-facing catalog (~2,000 products)
   - Realistic e-commerce frontend experience
   - Linked to ML models via latent item mappings

### Architecture: Why Two Datasets?

**Problem:** Using RetailRocket products directly would expose synthetic/Russian product names to users.

**Solution:** Train on RetailRocket behaviors, serve Amazon products.

```
┌─────────────────┐        ┌──────────────────┐        ┌─────────────────┐
│  RetailRocket   │        │  Latent Item     │        │  Amazon         │
│  Behavior Data  │ ──────>│  Mappings        │ ──────>│  Catalog        │
│  (Training)     │        │  (Bridge)        │        │  (Production)   │
└─────────────────┘        └──────────────────┘        └─────────────────┘
```

**Key Innovation:** `latent_item_mappings` table bridges RetailRocket item IDs (1-235061) to Amazon product UUIDs, allowing trained models to recommend real products.

### Citations

**Amazon Product Metadata 2023:**
```bibtex
@article{hou2024bridging,
  title={Bridging Language and Items for Retrieval and Recommendation},
  author={Hou, Yupeng and Li, Jiacheng and He, Zhankui and Yan, An and Chen, Xiusi and McAuley, Julian},
  journal={arXiv preprint arXiv:2403.03952},
  year={2024}
}
```

**Usage:** Amazon metadata used ONLY for catalog realism. No Amazon behavior data used for training.

---

## Dataset Statistics

### RetailRocket Behavior Data
**File:** `artifacts/external/retailrocket/events.csv.gz` (33 MB compressed)

| Metric | Value |
|--------|-------|
| Total events | 2,756,101 |
| Unique users | 1,407,580 |
| Unique products | 235,061 |
| Unique sessions | 1,666,974 |
| Time range | May 3, 2015 - September 18, 2015 (137 days) |

### Amazon Catalog Data
**Files:** `data/raw/amazon/meta_*.jsonl.gz` (3 GB compressed)

| Category | Raw Products | Filtered Products | Target |
|----------|-------------|------------------|--------|
| Electronics | ~100,000 | 700 | 700 |
| Cell Phones & Accessories | ~80,000 | 600 | 600 |
| Sports & Outdoors | ~60,000 | 500 | 500 |
| Software | ~40,000 | 200 | 200 |
| **Total** | **~280,000** | **~2,000** | **2,000** |

**Filtering Criteria:**
- Price > $5
- Valid image URL (hi_res or large format)
- Non-empty title and description
- Valid parent_asin identifier

### Latent Item Mappings
| Metric | Value |
|--------|-------|
| Total mappings | ~2,000 |
| Confidence ≥ 0.9 | ~30% |
| Confidence ≥ 0.7 | ~60% |
| Confidence ≥ 0.5 | ~100% |

**Mapping Strategy:**
1. Popular RetailRocket items → Popular Amazon products (high confidence)
2. Category-based matching → Medium confidence
3. Random assignment → Low confidence (fallback)

---

## Schema

### Original Schema (RetailRocket CSV)
```csv
timestamp,visitorid,event,itemid,transactionid
1430745600000,1,view,172,
1430745600001,1,view,185,
1430745600002,2,addtocart,287,100500
1430745600003,2,transaction,287,100500
```

| Column | Type | Description | Nullable |
|--------|------|-------------|----------|
| `timestamp` | Integer (ms) | Unix timestamp in milliseconds | No |
| `visitorid` | Integer | User identifier | No |
| `event` | String | Event type (view, addtocart, transaction) | No |
| `itemid` | Integer | Product identifier | No |
| `transactionid` | Integer | Transaction/session ID (only for purchases) | Yes |

---

### Transformed Schema (P1 Internal Format)
After processing in [01_retailrocket_eda.ipynb](../01_retailrocket_eda.ipynb):

```json
{
  "event_id": "uuid-v4-random",
  "event_type": "view | add_to_cart | purchase",
  "user_id": "string (visitorid converted to string)",
  "session_id": "string (transactionid if present, else user_id + date)",
  "product_id": "string (itemid converted to string)",
  "ts": "ISO 8601 timestamp (e.g., 2015-05-04T12:00:00+00:00)",
  "properties": {
    "source": "retailrocket",
    "original_timestamp": 1430745600000
  }
}
```

**Transformations:**
1. **event_id:** Generated UUID v4 (RetailRocket data has no event IDs)
2. **event_type:** Mapped `view→view`, `addtocart→add_to_cart`, `transaction→purchase`
3. **user_id:** Converted integer to string (e.g., `1` → `"1"`)
4. **session_id:** Use `transactionid` if present, else generate as `f"{user_id}_{date}"`
5. **product_id:** Converted integer to string (e.g., `172` → `"172"`)
6. **ts:** Converted Unix milliseconds to ISO 8601 UTC (e.g., `1430745600000` → `"2015-05-04T12:00:00+00:00"`)
7. **properties:** Added `source="retailrocket"` for traceability

---

## Data Quality

### Completeness
| Column | Null Count | Null % |
|--------|------------|--------|
| `timestamp` | 0 | 0% |
| `visitorid` | 0 | 0% |
| `event` | 0 | 0% |
| `itemid` | 0 | 0% |
| `transactionid` | 2,686,769 | 97.5% (expected, only purchases have transaction IDs) |

**Verdict:** ✅ No unexpected nulls. Missing `transactionid` is normal (only purchases have transactions).

### Duplicates
- **Duplicate rows:** 0 (verified in EDA notebook)
- **Duplicate event_ids:** N/A (generated after deduplication)

### Outliers
**Session Duration:**
- Median: 2 minutes
- 95th percentile: 45 minutes
- **Outlier:** Some sessions >24 hours (likely bots/crawlers)

**Session Size:**
- Median: 1 event per session (68% of users have only 1 event)
- 95th percentile: 12 events per session
- **Outlier:** Some sessions >100 events (handled with `MAX_SESSION_SIZE=50` in model training)

**Product Popularity:**
- Top 1% of products: 23% of views (power law distribution)
- Long tail: 44% of products have <10 views

---

## Feature Tables

After feature engineering in [03_feature_engineering.ipynb](../03_feature_engineering.ipynb), the dataset is transformed into 3 tables:

### 1. User Features
**File:** `artifacts/features/retailrocket/user_features.parquet` (15 MB)

**Schema:**
| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `user_id` | String | Unique user identifier | "1" |
| `total_events` | Integer | Total events by user | 42 |
| `unique_products_interacted` | Integer | Distinct products viewed | 15 |
| `unique_sessions` | Integer | Number of sessions | 8 |
| `views_count` | Integer | View events | 38 |
| `add_to_cart_count` | Integer | Cart additions | 3 |
| `purchase_count` | Integer | Completed purchases | 1 |
| `recency_days` | Float | Days since last event (from reference time) | 2.5 |
| `last_event_ts` | Timestamp | Most recent event timestamp | 2015-09-16 14:23:00 |

**Rows:** 1,407,580 users

**Reference Time:** September 18, 2015 02:59:47 UTC (last event in dataset)

---

### 2. Item Features
**File:** `artifacts/features/retailrocket/item_features.parquet` (18 MB)

**Schema:**
| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `product_id` | String | Unique product identifier | "172" |
| `total_views` | Integer | View count | 1,234 |
| `total_add_to_cart` | Integer | Cart additions | 45 |
| `total_purchases` | Integer | Purchase count | 23 |
| `popularity_score` | Float | log1p(total_views + total_add_to_cart + total_purchases) | 7.12 |
| `conversion_rate` | Float | total_purchases / total_views | 0.019 |
| `recency_days` | Float | Days since last interaction | 5.3 |
| `last_interaction_ts` | Timestamp | Most recent interaction | 2015-09-15 08:12:00 |

**Rows:** 235,061 products

---

### 3. Interaction Features
**File:** `artifacts/features/retailrocket/interaction_features.parquet` (120 MB)

**Schema:**
| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `user_id` | String | User identifier | "1" |
| `product_id` | String | Product identifier | "172" |
| `interaction_count` | Integer | User-product event count | 5 |
| `has_purchased` | Binary | User purchased this product? (0/1) | 1 |
| `recency_days` | Float | Days since last interaction | 1.2 |
| `last_interaction_ts` | Timestamp | Most recent interaction | 2015-09-17 19:45:00 |

**Rows:** 2,145,179 unique user-product pairs

---

## Conversion Funnel

### E-commerce Funnel Analysis
| Stage | Count | Conversion Rate |
|-------|-------|-----------------|
| **Views** | 2,664,312 | - |
| **Add to Cart** | 69,332 | 2.6% of views |
| **Purchases** | 22,457 | 0.84% of views |

**Purchase from Cart:** 32.4% of add-to-cart events convert to purchase

**Industry Benchmark:** Typical e-commerce conversion rate is 2-3% (RetailRocket is below average at 0.84%)

**Interpretation:** Low conversion rate reflects realistic e-commerce behavior (most users browse without buying).

---

## Temporal Patterns

### Time Range
- **Start date:** May 3, 2015 00:00:00 UTC
- **End date:** September 18, 2015 02:59:47 UTC
- **Duration:** 137 days (4.5 months)

### Daily Event Volume
- **Median:** 18,000 events/day
- **Peak:** 25,000 events/day (likely promotional campaign)
- **Weekend effect:** Slight increase on Saturdays (+10% vs weekdays)

### Hourly Patterns
- **Peak hours:** 10 AM - 8 PM (local time, likely Moscow timezone UTC+3)
- **Low activity:** 2 AM - 6 AM

---

## Biases & Limitations

### 1. Geographic Bias
**Issue:** Dataset is from Russian e-commerce platform (RetailRocket)

**Impact:**
- User behavior may differ from US/EU markets
- Product categories may reflect regional preferences (e.g., more cold-weather products)
- Language/cultural factors not generalizable

**Evidence:** Not directly observable in data, but inferred from source

---

### 2. Temporal Drift
**Issue:** Data from 2015 (10 years old as of 2025)

**Impact:**
- User expectations changed (mobile shopping, social commerce)
- Product categories evolved (e.g., smartwatches, VR headsets didn't exist)
- Conversion rates may be outdated

**Mitigation:** Fine-tune models on P1 production data after launch

---

### 3. Selection Bias (Logged Data)
**Issue:** Only captures events from users who visited the site

**Missing:**
- Users who never visited (unobserved population)
- Users who abandoned cart before checkout (partial funnel)
- Product impressions without clicks (no "view" event for products scrolled past)

**Impact:** Model learns from engaged users only (not representative of all potential customers)

---

### 4. Position Bias
**Issue:** Users more likely to click top-ranked products in search results

**Impact:** Popular products have inflated view counts (self-reinforcing loop)

**Evidence:** Power law distribution (top 1% of products = 23% of views)

**Mitigation:** Apply inverse propensity scoring (future work)

---

### 5. Cold-Start Bias
**Issue:** 68% of users have only 1 event (high churn)

**Impact:**
- Model trained mostly on engaged users (1-event users contribute minimal signal)
- Cold-start performance overestimated in offline evaluation

**Evidence:** Median events per user = 1

---

### 6. Class Imbalance
**Issue:** Only 0.8% of events are purchases (99.2% negative examples)

**Impact:** Model may struggle to learn purchase signals from rare positive examples

**Mitigation:** LambdaRank objective handles imbalance naturally (optimizes ranking, not classification)

---

### 7. Bot/Crawler Traffic
**Issue:** Some sessions have >100 events (likely automated crawlers)

**Impact:** Skews popularity metrics, inflates event counts

**Mitigation:** Filter sessions with >50 events (`MAX_SESSION_SIZE=50` in training)

---

## Privacy & Ethics

### Anonymization
**Status:** ✅ Data is anonymized

**Evidence:**
- User IDs are integers (no PII: names, emails, addresses)
- Product IDs are integers (no product names/descriptions in raw data)
- Timestamps include date/time but no geolocation

**GDPR Compliance:** Data is pseudonymized (user IDs are consistent but not reversible to real identities)

---

### Consent
**Unknown:** No information on user consent for data collection

**Assumption:** Data collected under RetailRocket's privacy policy (pre-GDPR, 2015)

**Risk:** If dataset included EU users, consent may not meet GDPR standards (but data is public on Kaggle, likely cleared)

---

### Sensitive Attributes
**Missing:** No demographic data (age, gender, income, location)

**Impact:** Cannot study fairness metrics (e.g., gender bias in recommendations)

**Future Work:** Collect demographics in P1 production (with explicit consent)

---

## Data Provenance

### Source
- **Platform:** RetailRocket (Russian e-commerce platform)
- **Published:** Kaggle (public dataset)
- **License:** CC0 (Public Domain) - no restrictions on use
- **Download:** `kaggle datasets download -d retailrocket/ecommerce-dataset`

### Preprocessing Pipeline
1. **Download:** Kaggle API (`events.csv` 33 MB compressed)
2. **Load:** Pandas (2.7M rows, 5 columns)
3. **Transform:** Schema mapping (RetailRocket → P1 internal format)
4. **Save:** Parquet format (`events.parquet` 184 MB uncompressed)
5. **Feature Engineering:** Generate 3 feature tables (user, item, interaction)

**Notebook:** [01_retailrocket_eda.ipynb](../01_retailrocket_eda.ipynb)

---

## Use Cases

### ✅ Approved Use Cases
1. **ML Model Training:** Pretrain recommender models on realistic behavior
2. **Feature Engineering:** Validate feature tables produce useful signals
3. **Offline Evaluation:** Establish baseline metrics (NDCG, Recall, Precision)
4. **Algorithm Prototyping:** Test collaborative filtering, ranking, cold-start strategies

### ❌ Prohibited Use Cases
1. **Production Exposure:** Never show RetailRocket product IDs to end users
2. **Direct Recommendation:** Do not recommend RetailRocket products to P1 users
3. **Re-identification:** Do not attempt to reverse-engineer user identities
4. **Discriminatory Purposes:** Do not use for biased targeting (no demographic data anyway)

---

## Maintenance & Updates

### Data Versioning
**Current Version:** 1.0 (May-Sep 2015 events)

**Future Versions:**
- **1.1 (planned):** Add P1 production events (hybrid dataset)
- **2.0 (planned):** Full P1 dataset (retire RetailRocket)

### Reprocessing
**Frequency:** On-demand (if feature engineering logic changes)

**Trigger Conditions:**
- New feature added to feature schema
- Bug fix in feature engineering code
- Model retraining requires updated features

### Deprecation
**Expected:** January 2026 (after 6 months of P1 production data collected)

**Reason:** RetailRocket is pretraining data only. P1 production data will be more representative.

---

## Events Table Schema

### Purpose
The `events` table stores user behavior events (view, click, add_to_cart, purchase) for **future analytics and retraining** when production reaches sufficient scale (>10K MAU).

**Current Usage:**
- ✅ **Written by:** catalog-service (direct PostgreSQL inserts)
- ❌ **NOT used by training:** Training reads static RetailRocket parquet files
- ❌ **NOT used by recommendations:** Recommendations use pre-trained models

**Design Decision:** At demonstration scale (<1K users), event collection serves as infrastructure readiness. Training on production data becomes valuable at 50K+ events/day.

### Runtime Schema (Auto-created)

**Authority:** `services/catalog-service/app/api/routes/events.py:ensure_events_table()`

| Column | Type | Constraints | Description |
|--------|------|-------------|-------------|
| `event_id` | `VARCHAR(255)` | PRIMARY KEY | Unique event identifier (UUID format) |
| `event_type` | `VARCHAR(50)` | NOT NULL | Event type: `view`, `click`, `add_to_cart`, `purchase` |
| `user_id` | `VARCHAR(255)` | NULL | User identifier (nullable for anonymous sessions) |
| `session_id` | `VARCHAR(255)` | NOT NULL | Browser session identifier for tracking |
| `product_id` | `VARCHAR(255)` | NULL | Product UUID (nullable for non-product events) |
| `properties` | `JSONB` | DEFAULT '{}' | Additional event metadata (extensible schema) |
| `ts` | `TIMESTAMPTZ` | NOT NULL | Event timestamp in UTC |

**Table Creation:** Idempotent `CREATE TABLE IF NOT EXISTS` on first event write.

**Write Semantics:** Idempotent inserts with `ON CONFLICT (event_id) DO NOTHING` (duplicate events silently ignored).

### Current Indexes

**Status:** ❌ No indexes currently implemented.

**Rationale:** At demonstration scale (<1K events), full table scans are acceptable. Indexes add write overhead without query benefit.

### Recommended Future Indexes

**Trigger:** Add indexes when analytics queries become slow (typically >100K events).

```sql
-- Query pattern: Filter by event type
CREATE INDEX idx_events_event_type ON events(event_type);

-- Query pattern: User behavior analysis
CREATE INDEX idx_events_user_id ON events(user_id) WHERE user_id IS NOT NULL;

-- Query pattern: Session reconstruction
CREATE INDEX idx_events_session_id ON events(session_id);

-- Query pattern: Time-range queries (e.g., last 7 days)
CREATE INDEX idx_events_ts ON events(ts);

-- Query pattern: Product engagement analysis
CREATE INDEX idx_events_product_id ON events(product_id) WHERE product_id IS NOT NULL;

-- Query pattern: JSONB property queries
CREATE INDEX idx_events_properties ON events USING GIN (properties);
```

**Implementation Path:**
1. Monitor query latency with production load
2. Identify slow queries via `EXPLAIN ANALYZE`
3. Add indexes incrementally (start with `event_type` and `ts`)
4. Consider migrating to Alembic migrations if schema changes become frequent

### Migration History

- **Pre-Phase D3:** Table created by `event-consumer` service (Kafka-based pipeline)
- **Phase D3.2:** Ownership transferred to `catalog-service` (direct PostgreSQL writes)
- **Phase D3.3:** Schema documented, orphaned SQL file removed

**Source of Truth:** This document (DATA_CARD.md) and runtime implementation (catalog-service).

---

## References

- **Model Card:** [MODEL_CARD.md](MODEL_CARD.md)
- **Phase 1 Documentation:** [PHASE_1_OFFLINE_ML_SYSTEM.md](PHASE_1_OFFLINE_ML_SYSTEM.md)
- **Feature Schema:** [../notebooks/artifacts/features/retailrocket/feature_schema.json](../notebooks/artifacts/features/retailrocket/feature_schema.json)
- **EDA Notebook:** [../notebooks/01_retailrocket_eda.ipynb](../notebooks/01_retailrocket_eda.ipynb)
- **Feature Engineering Notebook:** [../notebooks/03_feature_engineering.ipynb](../notebooks/03_feature_engineering.ipynb)

---

## Contact

**Data Owner:** P1 ML Team  
**Last Updated:** December 28, 2025  
**Dataset Version:** 1.0  
**Next Review Date:** January 28, 2026

---

**Document Status:** Complete  
**Intended Audience:** ML engineers, data scientists, compliance/audit teams  
**Inspired By:** Datasheets for Datasets (Gebru et al., 2018)
