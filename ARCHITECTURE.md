# Atlas Architecture

**System Design and Component Interaction**

> **Intended Audience**: This document is for engineers and technical interviewers seeking deep understanding of Atlas's system design, request flows, and architectural decisions.

---

## Table of Contents
1. [High-Level Architecture](#high-level-architecture)
2. [Request Flow](#request-flow)
3. [ML Inference Pipeline](#ml-inference-pipeline)
4. [Data Architecture](#data-architecture)
5. [Service Details](#service-details)
6. [Why Kubernetes](#why-kubernetes)
7. [Design Decisions](#design-decisions)

---

## High-Level Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                          USERS (Web Browser)                            │
│                   https://4-224-153-183.sslip.io                       │
└─────────────────────────────────┬──────────────────────────────────────┘
                                  │ HTTPS (TLS 1.3)
                                  │ Let's Encrypt Certificate
                                  ▼
                    ┌─────────────────────────────┐
                    │    NGINX Ingress Controller │
                    │    (TLS Termination)        │
                    │    Routes: / → frontend     │
                    │           /api/* → gateway  │
                    └──────────────┬──────────────┘
                                   │
            ┌──────────────────────┴─────────────────────┐
            │                                            │
            ▼                                            ▼
    ┌───────────────┐                          ┌─────────────────┐
    │   Frontend    │                          │   API Gateway   │
    │   (React)     │                          │   (FastAPI)     │
    │   Port 80     │◄─────────────────────────┤   Port 8000     │
    │   Nginx       │                          │   Proxy         │
    └───────────────┘                          └────────┬────────┘
                                                        │
                              ┌─────────────────────────┼─────────────────────────┐
                              │                         │                         │
                              ▼                         ▼                         ▼
                    ┌──────────────────┐    ┌──────────────────┐    ┌──────────────────┐
                    │  User Service    │    │ Catalog Service  │    │ Recommendation   │
                    │  (FastAPI)       │    │ (FastAPI)        │    │ Service          │
                    │  • Auth (JWT)    │    │ • Products       │    │ (FastAPI + ML)   │
                    │  • User CRUD     │    │ • Categories     │    │ • SVD            │
                    │  Port 5000       │    │ • Mappings       │    │ • LightGBM       │
                    └────────┬─────────┘    │ Port 5004        │    │ • Session        │
                             │              └────────┬─────────┘    │ Port 5005        │
                             │                       │              └────────┬─────────┘
                             │                       │                       │
                             └───────────────────────┼───────────────────────┘
                                                     ▼
                                          ┌────────────────────┐
                                          │   PostgreSQL 17    │
                                          │   Tables:          │
                                          │   • users          │
                                          │   • products       │
                                          │   • categories     │
                                          │   • latent_item_   │
                                          │     mappings       │
                                          │   Port 5432        │
                                          └────────────────────┘

                                          ┌────────────────────┐
                                          │      Redis 8       │
                                          │   • Sessions       │
                                          │   • View history   │
                                          │   Port 6379        │
                                          └────────────────────┘
```

---

## Request Flow

### 1. Frontend Page Load

```
User navigates to https://4-224-153-183.sslip.io/
    ↓
NGINX Ingress (TLS termination, decrypts HTTPS)
    ↓
Routes to frontend service (port 80)
    ↓
Nginx serves React SPA (static files: index.html, JS bundles, CSS)
    ↓
Browser executes React app
    ↓
Frontend makes API call: GET /api/v1/catalog/products?limit=48
    ↓
NGINX Ingress routes /api/* to API Gateway (port 8000)
    ↓
API Gateway proxies to catalog-service:5004
    ↓
Catalog Service queries PostgreSQL:
    SELECT p.*, c.name, c.slug FROM products p JOIN categories c ...
    ↓
Returns JSON: {products: [{id, name, price, currency, category, image_url}]}
    ↓
Frontend renders product grid
```

### 2. User Registration Flow

```
User fills form → POST /api/v1/auth/register
    ↓
Ingress → API Gateway → User Service
    ↓
User Service:
    • Validates email format, password strength
    • Hashes password (bcrypt, 12 rounds)
    • Generates UUID for user_id
    • INSERT INTO users (id, name, email, password_hash)
    ↓
Creates JWT token (HS256, 24h expiration):
    {
      "sub": "user_id",
      "email": "user@example.com",
      "exp": 1737062400
    }
    ↓
Returns: {token: "eyJ0eXAi...", user_id: "uuid"}
    ↓
Frontend stores token in localStorage
    ↓
Subsequent requests include header: Authorization: Bearer {token}
```

### 3. Recommendation Request Flow

```
GET /api/v1/recommendations?user_id=X&k=8
    ↓
Ingress → API Gateway → Recommendation Service
    ↓
┌─────────────────────────────────────────────────────────────┐
│ STAGE 1: Strategy Selection                                 │
│                                                              │
│ if product_id provided:                                     │
│     strategy = "item_similarity"                            │
│     candidates = item_similarity_model.get_similar(id, 100) │
│                                                              │
│ elif user has interaction history (check database):         │
│     strategy = "two_stage_personalized"                     │
│     candidates = svd_model.predict(user_id, top_k=100)      │
│     NOTE: Currently cold-start limited (see ML_SYSTEM.md)   │
│                                                              │
│ else:                                                        │
│     strategy = "popularity_fallback"                        │
│     candidates = get_top_products_by_views(100)             │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│ STAGE 2: Metadata Enrichment                                │
│                                                              │
│ For each candidate product ID:                              │
│     • Query database for product details (name, price, etc) │
│     • Compute features: price_log, category_id, popularity  │
│     • Build feature matrix (100 products × 16 features)     │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│ STAGE 3: LightGBM Ranking                                   │
│                                                              │
│ scores = lightgbm_ranker.predict(feature_matrix)            │
│ • Model: 100 trees, 31 leaves, learning_rate=0.05          │
│ • Objective: LambdaRank (NDCG optimization)                 │
│ • Performance: NDCG@10 = 0.999 (offline)                    │
│   Note: Offline metric on curated test data; production     │
│   performance expected to be lower                          │
│                                                              │
│ ranked_products = sort_by_score(candidates, scores)         │
│ top_20 = ranked_products[:20]                               │
└─────────────────────────────────────────────────────────────┘
    ↓
┌─────────────────────────────────────────────────────────────┐
│ STAGE 4: Session Reranking (if session exists)             │
│                                                              │
│ session_data = redis.get(f"session:{user_id}")              │
│ if session_data:                                             │
│     viewed_categories = session_data["viewed_categories"]   │
│     price_range = session_data["price_affinity"]            │
│                                                              │
│     for product in top_20:                                  │
│         if product.category in viewed_categories:           │
│             score += 0.1 * (view_count / total_views)       │
│         if product.price in price_range:                    │
│             score += 0.2                                    │
│                                                              │
│     re_sort(top_20, by=adjusted_score)                      │
└─────────────────────────────────────────────────────────────┘
    ↓
Return JSON: [
    {
        "id": "uuid",
        "name": "Product Name",
        "price": 1234.56,
        "currency": "INR",
        "image_url": "https://...",
        "category": {...},
        "score": 0.95
    },
    ...
]
    ↓
Frontend renders recommendation carousel
```

---

## ML Inference Pipeline

### Model Loading (Service Startup)

```python
# services/recommendation-service/app/core/models.py

class ModelRegistry:
    def __init__(self):
        self.artifacts_path = Path("/artifacts")  # Mounted volume
        
        # 1. Load Popularity Baseline (cold start)
        self.popularity = pd.read_csv(
            self.artifacts_path / "popularity_baseline.csv"
        )
        
        # 2. Load Item Similarity Matrix (item-item CF)
        self.item_similarity = pickle.load(
            open(self.artifacts_path / "item_similarity_matrix.pkl", "rb")
        )
        
        # 3. Load SVD Model (user-item CF)
        self.svd_model = pickle.load(
            open(self.artifacts_path / "svd_model.pkl", "rb")
        )
        self.item_factors = np.load(
            self.artifacts_path / "item_factors.npy"
        )
        
        # 4. Load LightGBM Ranker
        self.ranker = lgb.Booster(
            model_file=str(self.artifacts_path / "lightgbm_ranker.txt")
        )
        
        # 5. Load Feature Metadata
        self.feature_stats = json.load(
            open(self.artifacts_path / "feature_stats.json")
        )
```

### Feature Engineering

```python
def assemble_features(user_id: str, product_ids: List[str]) -> np.ndarray:
    """
    Build feature matrix for ranking.
    
    Features (15 total):
        • product_id (categorical, label-encoded)
        • category_id (categorical)
        • price (numerical, log-transformed)
        • price_normalized (0-1 scaled)
        • popularity_score (view count / max views)
        • avg_rating (if available, else 0)
        • num_reviews (if available, else 0)
        • stock_quantity (capped at 100)
        • is_in_stock (boolean)
        • price_rank_in_category (percentile)
        • category_popularity (category view count)
        • days_since_added (recency)
        • has_image (boolean)
        • has_description (boolean)
        • session_affinity (if session exists, else 0)
    
    Returns:
        np.ndarray of shape (len(product_ids), 15)
    """
    features = []
    
    for product_id in product_ids:
        # Query database
        product = db.query(Product).filter_by(id=product_id).first()
        category = db.query(Category).filter_by(id=product.category_id).first()
        
        # Compute features
        feature_vector = [
            encode_product_id(product_id),
            encode_category_id(product.category_id),
            np.log1p(product.price),
            normalize_price(product.price, category.price_stats),
            compute_popularity(product_id),
            product.avg_rating or 0,
            product.num_reviews or 0,
            min(product.stock_quantity, 100),
            int(product.stock_quantity > 0),
            compute_price_rank(product, category),
            category_popularity[category.id],
            (datetime.now() - product.created_at).days,
            int(bool(product.image_url)),
            int(len(product.description) > 50),
            get_session_affinity(user_id, product) if user_id else 0
        ]
        
        features.append(feature_vector)
    
    return np.array(features)
```

---

## Data Architecture

### Database Schema

```sql
-- Users Table
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(100) NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Categories Table
CREATE TABLE categories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug VARCHAR(100) UNIQUE NOT NULL,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    path VARCHAR(500),  -- For hierarchical categories
    parent_id UUID REFERENCES categories(id),
    display_order INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Products Table
CREATE TABLE products (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    category_id UUID REFERENCES categories(id) NOT NULL,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    price DECIMAL(10,2) NOT NULL,
    currency VARCHAR(3) DEFAULT 'USD',
    image_url TEXT,
    thumbnail_url TEXT,
    stock_quantity INTEGER DEFAULT 100,
    attributes JSONB,  -- Flexible metadata
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Latent Item Mappings (Training → Production Bridge)
CREATE TABLE latent_item_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    latent_item_id INTEGER UNIQUE NOT NULL,  -- RetailRocket ID
    product_id UUID REFERENCES products(id) NOT NULL,  -- Atlas UUID
    mapping_strategy VARCHAR(50),  -- 'category_popularity', 'random', etc
    confidence_score FLOAT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Indexes for Performance
CREATE INDEX idx_products_category ON products(category_id);
CREATE INDEX idx_products_price ON products(price);
CREATE INDEX idx_latent_mappings_latent_id ON latent_item_mappings(latent_item_id);
CREATE INDEX idx_latent_mappings_product_id ON latent_item_mappings(product_id);
```

### Redis Schema

```
# Session Tracking
Key: session:{user_id}
Type: Hash
TTL: 24 hours
Fields:
    - viewed_products: JSON list of product IDs
    - viewed_categories: JSON counter {category_id: count}
    - price_affinity_min: Float
    - price_affinity_max: Float
    - last_active: Timestamp

Example:
HGET session:user-123 viewed_categories
→ '{"electronics": 5, "books": 2}'

# Product View Counter
Key: product_views:{product_id}
Type: String (integer counter)
TTL: 7 days

INCR product_views:prod-456
→ 142
```

---

## Service Details

### 1. Frontend (React + Nginx)

**Purpose**: User interface and static asset serving

**Technology**:
- React 19 with TypeScript
- Vite (build tool)
- TailwindCSS (styling)
- Nginx (production server)

**Endpoints Served**:
- `/` - Home page (product grid)
- `/product/:id` - Product detail page
- `/category/:slug` - Category browsing
- `/login`, `/register` - Authentication pages

**API Communication**:
```typescript
// src/services/api.ts
const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || '/api',  // Environment-based
  headers: { 'Content-Type': 'application/json' },
});

// Local dev: http://localhost:8000/api
// Production: /api (Ingress routes to gateway)
```

**Production Dockerfile**: Uses multi-stage build (Node → Nginx)

---

### 2. API Gateway (FastAPI)

**Purpose**: Reverse proxy and routing layer

**Routes**:
```python
# app/main.py
app.include_router(auth_router, prefix="/api/v1/auth")
app.include_router(catalog_router, prefix="/api/v1/catalog")
app.include_router(recommendation_router, prefix="/api/v1/recommendations")

# Proxies to:
# /api/v1/auth/* → user-service:5000
# /api/v1/catalog/* → catalog-service:5004
# /api/v1/recommendations/* → recommendation-service:5005
```

**Why Gateway?**:
- **Single Entry Point**: Frontend only knows one URL
- **Cross-Cutting Concerns**: Can add rate limiting, logging, auth middleware
- **Service Isolation**: Backend services don't need public IPs
- **Future Flexibility**: Can add GraphQL, gRPC, WebSocket support

---

### 3. User Service (FastAPI)

**Purpose**: Authentication and user management

**Key Features**:
- JWT token generation (HS256 algorithm)
- Password hashing (bcrypt, 12 rounds)
- Token validation middleware
- User CRUD operations

**Endpoints**:
```
POST /register - Create new user
POST /login - Authenticate and get JWT
GET /me - Get current user info (requires token)
PUT /profile - Update user profile
```

**Database**: PostgreSQL `users` table

---

### 4. Catalog Service (FastAPI)

**Purpose**: Product and category management

**Key Features**:
- Product listing with pagination (cursor-based)
- Category hierarchy support
- Price conversion (USD → INR, rate: 83.0)
- Latent mapping lookup for ML integration

**Endpoints**:
```
GET /products - List products (with filters, pagination)
GET /products/:id - Get product details
GET /categories - List categories
GET /categories/:slug/products - Products by category
GET /mappings/:latent_id - Map RetailRocket ID → Atlas UUID
```

**Database**: PostgreSQL `products`, `categories`, `latent_item_mappings`

---

### 5. Recommendation Service (FastAPI + ML)

**Purpose**: ML-powered product recommendations

**Key Features**:
- Three-strategy candidate generation (SVD, similarity, popularity)
- LightGBM ranking for precision
- Session-aware reranking
- Model warm-up on startup (optional)

**Endpoints**:
```
GET /recommendations - Get personalized recommendations
    Query params: user_id, product_id, k (number of results)
    
POST /track_session - Update session data (view events)
    Body: {user_id, product_id, event_type, metadata}
```

**Dependencies**:
- PostgreSQL (product metadata)
- Redis (session data)
- `/artifacts` volume (model files)

**Model Files** (mounted at `/artifacts`):
```
/artifacts/
├── popularity_baseline.csv
├── item_similarity_matrix.pkl
├── svd_model.pkl
├── item_factors.npy
├── user_factors.npy
├── lightgbm_ranker.txt
├── feature_stats.json
└── category_encodings.json
```

---

## Why Kubernetes?

### Production Readiness

1. **Declarative Configuration**: All infrastructure defined in YAML
2. **Self-Healing**: Crashed pods automatically restart
3. **Service Discovery**: Internal DNS (e.g., `catalog-service.atlas.svc.cluster.local`)
4. **Load Balancing**: Built-in round-robin for multi-replica services
5. **Rolling Updates**: Zero-downtime deployments

### Example: Updating Frontend

```bash
# Build new image
docker build -f frontend/Dockerfile.prod -t atlasacrp1.azurecr.io/frontend:v6 frontend/

# Push to registry
docker push atlasacrp1.azurecr.io/frontend:v6

# Update deployment (Kubernetes handles rollout)
kubectl set image deployment/frontend frontend=atlasacrp1.azurecr.io/frontend:v6 -n atlas

# Watch rollout
kubectl rollout status deployment/frontend -n atlas

# If issues, rollback
kubectl rollout undo deployment/frontend -n atlas
```

Kubernetes will:
1. Create new pod with v6 image
2. Wait for health checks to pass
3. Shift traffic from old pod to new pod
4. Terminate old pod
5. All with zero downtime

### Scalability (Future)

```yaml
# Enable horizontal autoscaling
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: recommendation-service-hpa
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: recommendation-service
  minReplicas: 1
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
```

When CPU > 70%, Kubernetes automatically adds pods. When load decreases, scales down.

---

## Design Decisions

### 1. Microservices vs Monolith

**Choice**: Microservices

**Reasoning**:
- **Demonstrates Industry Practices**: Most companies use microservices at scale
- **Service Isolation**: Recommendation service can crash without affecting catalog
- **Independent Deployment**: Can update ML models without redeploying frontend
- **Technology Diversity**: Could use Go for high-throughput services, Python for ML

**Tradeoffs**:
- **Complexity**: More moving parts (service discovery, inter-service communication)
- **Debugging**: Distributed tracing needed to diagnose issues
- **Latency**: Network hops between services (mitigated by K8s internal networking)

### 2. Offline vs Online ML Training

**Choice**: Offline batch training

**Reasoning**:
- **Data Quality**: Train on 2.7M real events (RetailRocket) vs sparse production data
- **Model Complexity**: SVD matrix factorization is computationally expensive
- **Cost**: Avoid expensive online embedding updates
- **Scale**: At <2K products and <1K users, batch retraining is acceptable

**When to Switch to Online**:
- User base > 10K (need incremental updates)
- Real-time signals (e.g., "trending now")
- Embedding drift detected (model performance degrades)

### 3. Session Reranking vs Real-Time Personalization

**Choice**: Session-based reranking (hybrid approach)

**Reasoning**:
- **Immediate Value**: Works for new users (no history required)
- **Low Latency**: Redis lookup + score adjustment <10ms
- **Intent Capture**: Current session reveals short-term interests
- **Bridge Solution**: Provides personalization until collaborative filtering has enough data

**Why Not Full Real-Time**:
- **Cold Start**: New users have no interaction history
- **Signal Sparsity**: Need 5-10 interactions for meaningful embeddings
- **Infrastructure Cost**: Real-time embedding updates require streaming pipeline (Kafka + Flink)

### 4. Currency Conversion (USD → INR)

**Choice**: Convert at API response time with fixed rate (1 USD = 83 INR)

**Reasoning**:
- **Data Consistency**: Database stores prices in USD (source data format)
- **Flexibility**: Can add multi-currency support without schema changes
- **Simplicity**: Avoid complex currency conversion during feature engineering

**Production Consideration**:
- Use external API (e.g., Open Exchange Rates) for real-time rates
- Cache rates in Redis (TTL: 1 hour)
- Handle conversion errors gracefully (fallback to USD)

### 5. TLS Certificate (Staging vs Production)

**Choice**: Let's Encrypt Staging (currently)

**Reasoning**:
- **Rate Limit**: Production Let's Encrypt rate-limited for `nip.io` and `sslip.io` (25,000 certs/week)
- **Proof of Concept**: Staging certificate proves TLS infrastructure works
- **Interview Context**: Can explain rate limiting and demonstrate cert-manager setup

**Production Plan**:
- Wait 7 days for rate limit reset OR
- Use custom domain (e.g., atlas-demo.com) with production certificate

---

## Security Considerations

### 1. Authentication
- **JWT Tokens**: Signed with HS256 (shared secret)
- **Token Expiration**: 24 hours (configurable)
- **Password Hashing**: bcrypt with 12 rounds (slow by design to prevent brute force)

### 2. Database
- **Connection Pooling**: SQLAlchemy manages connection lifecycle
- **SQL Injection Prevention**: Parameterized queries (ORM layer)
- **Sensitive Data**: Passwords never stored in plain text

### 3. Network
- **TLS Encryption**: All external traffic encrypted (HTTPS)
- **Internal Communication**: Kubernetes network policies (future improvement)
- **Secret Management**: Kubernetes Secrets for DB passwords, JWT secret

### 4. Input Validation
- **Pydantic Models**: Automatic validation and type coercion
- **Request Size Limits**: Nginx proxy_body_size: 10MB
- **Rate Limiting**: (Future) Token bucket algorithm via API Gateway

---

## Performance Characteristics

### Latency Targets (P95)

| Endpoint | Target | Actual | Notes |
|----------|--------|--------|-------|
| GET /products | <200ms | ~150ms | Database query + pagination |
| GET /recommendations | <500ms | ~300ms | ML inference + ranking |
| POST /register | <300ms | ~250ms | bcrypt hashing (CPU-bound) |
| POST /login | <300ms | ~200ms | Database lookup + JWT creation |

### Throughput

| Service | RPS (1 pod) | Bottleneck | Scaling Strategy |
|---------|-------------|------------|------------------|
| Catalog | ~500 | PostgreSQL connection pool | Read replicas |
| Recommendations | ~100 | ML inference (CPU) | Horizontal pod autoscaling |
| User | ~200 | bcrypt hashing (CPU) | Async workers |

### Resource Usage

| Service | CPU (idle) | CPU (load) | Memory | Disk |
|---------|------------|------------|--------|------|
| Frontend | 10m | 50m | 64MB | - |
| API Gateway | 20m | 100m | 128MB | - |
| Catalog | 30m | 200m | 256MB | - |
| Recommendations | 100m | 500m | 512MB | 500MB (models) |
| User | 20m | 100m | 128MB | - |
| PostgreSQL | 50m | 300m | 512MB | 5GB (data) |
| Redis | 10m | 50m | 128MB | 256MB (sessions) |

**Total Cluster**: ~1 vCPU, 2GB RAM (B2s_v2 node sufficient)

---

## Monitoring & Observability (Planned)

### Metrics
- **Prometheus**: Scrape `/metrics` endpoints
- **Grafana**: Dashboards for request rates, latency, error rates
- **Custom Metrics**: Recommendation click-through rate, model inference time

### Logging
- **Structured Logs**: JSON format with correlation IDs
- **Loki**: Centralized log aggregation
- **Query**: `{namespace="atlas", service="recommendation"} |= "error"`

### Tracing
- **Jaeger**: Distributed tracing for request flows
- **Spans**: Frontend → Gateway → Service → Database
- **Use Case**: Debug slow recommendations (identify bottleneck: DB query vs ML inference)

---

## Future Architecture Enhancements

### 1. Event-Driven Real-Time Updates
```
User Event → Kafka → Stream Processor (Flink) → Update Redis Embeddings
```

### 2. Caching Layer
```
GET /products → Check Redis → If miss, query PostgreSQL → Cache result (TTL: 5 min)
```

### 3. Search Service
```
Elasticsearch cluster → Full-text search on product names/descriptions
```

### 4. Analytics Pipeline
```
User Events → Kafka → Spark Streaming → Parquet files → Train models nightly
```

### 5. Multi-Region Deployment
```
Azure Traffic Manager → Region selector → AKS clusters (US, EU, Asia)
```

---

**Next**: See [ML_SYSTEM.md](ML_SYSTEM.md) for detailed ML pipeline explanation.
