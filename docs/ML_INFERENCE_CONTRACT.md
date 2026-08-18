# Atlas External ML Inference Boundary & API Contract

## 1. Architectural Motivation

Atlas is deployed as a microservices architecture on Render, where the `recommendation-service` operates under strict resource constraints (512 MB memory limit on basic tiers). The full recommendation pipeline combines:
1. **Recall Layer**: SVD Collaborative Filtering (165 MB pickle, ~125 MB RAM resident) and Item-Item Similarity (10 MB pickle, ~30 MB RAM resident).
2. **Feature Store / Precision Layer**: User & Item parquet feature tables (35 MB on disk, ~80 MB RAM resident) and LightGBM Ranker (350 KB).

To avoid out-of-memory (OOM) failures on Render while restoring the full two-stage ML pipeline (SVD/Similarity → LightGBM), Atlas establishes a clean, decoupled software boundary for external ML inference (e.g. Hugging Face Spaces).

---

## 2. Responsibility Boundary

The platform cleanly separates domain/business orchestration from compute-heavy ML inference:

```
┌────────────────────────────────────────────────────────┐
│             Render (Recommendation Service)            │
│  - API Routing & HTTP Serialization                   │
│  - Query Validation & Candidate Routing                │
│  - Popularity Baseline & Cold-Start Fallback           │
│  - Latent-to-Catalog ID Mapping (PostgreSQL asyncpg)   │
│  - Product Catalog Metadata Hydration                  │
│  - Decisioning Rules (Diversity, Deduplication, Stock) │
│  - Intent-Aware Session Re-ranking (Upstash Redis)     │
│  - Fail-Safe Local Pipeline Fallback                   │
└──────────────────────────┬─────────────────────────────┘
                           │ POST /infer (Single HTTP Request)
                           ▼
┌────────────────────────────────────────────────────────┐
│           External ML Service (e.g. HF Space)          │
│  - SVD Model Factor Multiplications (User Vectors)     │
│  - Item-Item Sparse Similarity Matrix Lookups          │
│  - Feature Extraction (User & Item Parquet Tables)     │
│  - LightGBM LambdaRank Precision Scoring               │
└────────────────────────────────────────────────────────┘
```

---

## 3. API Contract Specification

### 3.1 Inference Endpoint

- **Method**: `POST`
- **Path**: `/infer`
- **Content-Type**: `application/json`

### 3.2 Request Schema (`InferenceRequest`)

| Field | Type | Required | Description |
|---|---|---|---|
| `user_id` | `string` | Optional | User identifier (app UUID or RetailRocket ID string) |
| `item_id` | `int \| string` | Optional | RetailRocket item integer ID for similarity queries |
| `candidate_ids` | `array[int]` | Optional | Pre-selected candidate item IDs to re-rank |
| `k` | `integer` | Optional (default: 100) | Number of candidate items to produce (1–500) |
| `model_version` | `string` | Optional | Model artifact version tag (e.g. `production_v1`) |

#### Example Request:
```json
{
  "user_id": "12345",
  "item_id": 67890,
  "k": 100,
  "model_version": "production_v1"
}
```

### 3.3 Response Schema (`InferenceResponse`)

| Field | Type | Required | Description |
|---|---|---|---|
| `status` | `string` | Yes | `"success"`, `"cold_start"`, or `"error"` |
| `items` | `array[InferredItem]` | Yes | List of candidate items with scores |
| `items[].item_id` | `integer` | Yes | RetailRocket latent item integer ID |
| `items[].score` | `float` | Yes | Model score (higher = better) |
| `strategy_used` | `string` | Yes | Strategy tag (e.g. `"two_stage_svd_lgbm"`, `"two_stage_item_sim_lgbm"`) |
| `model_version` | `string` | Optional | Model artifact version used |
| `error` | `string` | Optional | Error description if `status == "error"` |
| `execution_time_ms`| `float` | Optional | Server execution duration in ms |

#### Example Response:
```json
{
  "status": "success",
  "items": [
    {"item_id": 10423, "score": 0.9421},
    {"item_id": 8592, "score": 0.8834},
    {"item_id": 12004, "score": 0.8120}
  ],
  "strategy_used": "two_stage_svd_lgbm",
  "model_version": "production_v1",
  "execution_time_ms": 14.5
}
```

---

## 4. Failure Modes & Fallback Guarantees

The external inference boundary is strictly **non-blocking and fail-safe**:

1. **Disabled by Default**: When `ML_INFERENCE_ENABLED=false` or `ML_INFERENCE_URL` is unset, the client executes zero network requests and the service uses the local pipeline.
2. **Timeout Protection**: The client enforces `ML_INFERENCE_TIMEOUT` (default: 2.0s). If the external service hangs, the client times out fast, logs a structured warning (`log_fallback`), and falls back to the local candidate generation pipeline.
3. **Connection / HTTP 5xx Failures**: Any network disconnection, DNS failure, or non-200 HTTP status returns `None` and triggers local fallback.
4. **Cold Start**: When the external ML service encounters an unknown user, it returns `status: "cold_start"`, enabling Render to serve the local popularity baseline.

---

## 5. Configuration

| Environment Variable | Type | Default | Description |
|---|---|---|---|
| `ML_INFERENCE_ENABLED` | `boolean` | `false` | Enable or disable external ML inference boundary |
| `ML_INFERENCE_URL` | `string` | `null` | Base URL of external ML service (e.g. `https://my-space.hf.space`) |
| `ML_INFERENCE_TIMEOUT` | `float` | `2.0` | Client request timeout in seconds |

---

## 6. Local Testing & Reference Implementation

A complete reference/mock implementation is included in `app/inference/mock_server.py`.

Run the mock server independently:
```bash
uvicorn app.inference.mock_server:mock_ml_app --port 8001
```

Run test suite:
```bash
pytest tests/recommendation/test_ml_inference_boundary.py
```
