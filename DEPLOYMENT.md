# Atlas Deployment Guide

**From Local Development to Azure Kubernetes Service**

> **Important Notes**:  
> - Azure CLI commands assume a Unix-like shell (bash/zsh). Windows users should use Git Bash, WSL, or adapt commands for PowerShell.  
> - Current deployment is intentionally manual to demonstrate infrastructure knowledge. CI/CD automation is planned as a future enhancement.

---

## Table of Contents
1. [Local Development](#local-development)
2. [Docker Compose Setup](#docker-compose-setup)
3. [Kubernetes Local Testing](#kubernetes-local-testing)
4. [Azure AKS Deployment](#azure-aks-deployment)
5. [HTTPS with Let's Encrypt](#https-with-lets-encrypt)
6. [Monitoring and Maintenance](#monitoring-and-maintenance)

---

## Local Development

### Prerequisites

- **Docker Desktop** 4.25+ with Kubernetes enabled
- **Node.js** 20+ (frontend development)
- **Python** 3.11+ (backend development)
- **kubectl** 1.28+ (Kubernetes CLI)
- **Azure CLI** 2.50+ (for AKS deployment)

### Environment Variables

Create `.env.local` files for local development:

```bash
# frontend/.env.local
VITE_API_URL=http://localhost:8000/api
```

**Note**: `.env.local` is git-ignored and only used for local builds. Production uses relative `/api` path (Ingress routing).

---

## Docker Compose Setup

### Quick Start

```bash
# 1. Start all services
cd infra
docker-compose up -d

# 2. Check status
docker-compose ps

# Expected output:
# NAME                             STATUS
# infra-db-1                       Up (healthy)
# infra-redis-1                    Up (healthy)
# infra-user-service-1             Up (healthy)
# infra-catalog-service-1          Up (healthy)
# infra-recommendation-service-1   Up (healthy)
# infra-api-gateway-1              Up (healthy)
# infra-frontend-1                 Up

# 3. Run migrations
docker exec infra-user-service-1 alembic upgrade head
docker exec infra-catalog-service-1 alembic upgrade head

# 4. Seed database
docker cp ../tools/seed-data/amazon_products.json infra-db-1:/tmp/
docker cp ../tools/seed-data/category_mappings.json infra-db-1:/tmp/
docker cp ../tools/seed-data/seed_k8s_from_files.py infra-db-1:/tmp/

docker exec infra-db-1 bash -c "apt-get update && apt-get install -y python3 python3-pip && \
  pip3 install --break-system-packages sqlalchemy psycopg2-binary && \
  sed -i 's/postgresql:\/\/postgres:postgres@postgres/postgresql:\/\/postgres:postgres@localhost/g' /tmp/seed_k8s_from_files.py && \
  python3 /tmp/seed_k8s_from_files.py"

# 5. Access application
# Frontend: http://localhost:5174
# API Docs: http://localhost:8000/docs
```

### Docker Compose Configuration

```yaml
# infra/docker-compose.yml (simplified)

services:
  user-service:
    build: ../services/user-service
    ports: ["5000:5000"]
    environment:
      - POSTGRES_URI=postgresql://postgres:postgres@db:5432/ecommerce
      - JWT_SECRET=devsecret
      - REDIS_URL=redis://redis:6379
    depends_on: [db, redis]

  catalog-service:
    build: ../services/catalog-service
    ports: ["5004:5004"]
    environment:
      - DATABASE_URL=postgresql://postgres:postgres@db:5432/ecommerce
    depends_on: [db]

  recommendation-service:
    build:
      context: ..
      dockerfile: services/recommendation-service/Dockerfile
    ports: ["5005:5005"]
    volumes:
      - ../notebooks/artifacts:/artifacts:ro  # ML models
    depends_on: [db, redis]

  api-gateway:
    build: ../services/api-gateway
    ports: ["8000:8000"]
    depends_on: [user-service, catalog-service, recommendation-service]

  frontend:
    build: ../frontend
    ports: ["5174:5174"]
    environment:
      - VITE_API_URL=http://localhost:8000/api  # Local only
    depends_on: [api-gateway]

  db:
    image: postgres:17
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: ecommerce
    ports: ["5432:5432"]
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:8
    ports: ["6379:6379"]

volumes:
  postgres_data:
```

### Key Design Decisions

1. **Why `context: ..` for recommendation-service?**
   - Dockerfile needs to copy from both `services/recommendation-service/` and `notebooks/artifacts/`
   - Docker build context must be project root
   - Configured in docker-compose with `context: ..` and `dockerfile: services/recommendation-service/Dockerfile`

2. **Why environment variable for frontend API URL?**
   - **Local**: Browser needs `http://localhost:8000/api` (absolute URL)
   - **Production**: Browser uses `/api` (Ingress routes to gateway)
   - Vite bakes env var into build (`import.meta.env.VITE_API_URL`)

3. **Why sed command for seeding script?**
   - Seeding script expects `postgres` hostname (Docker network)
   - When running inside `db` container, hostname is `localhost`
   - `sed` replaces hostname dynamically

---

## Kubernetes Local Testing

### Enable Kubernetes in Docker Desktop

1. Open Docker Desktop → Settings → Kubernetes
2. Check "Enable Kubernetes"
3. Click "Apply & Restart"
4. Verify: `kubectl cluster-info`

### Deploy to Local Kubernetes

```bash
# 1. Build images (use same tags as production)
docker build -f frontend/Dockerfile.prod -t atlas-frontend:local frontend/
docker build -t atlas-user-service:local services/user-service/
docker build -t atlas-catalog-service:local services/catalog-service/
docker build -t atlas-api-gateway:local services/api-gateway/
docker build -f services/recommendation-service/Dockerfile -t atlas-recommendation-service:local .

# 2. Create namespace
kubectl create namespace atlas-local

# 3. Create secrets
kubectl create secret generic postgres-secret \
  --from-literal=password=postgres \
  -n atlas-local

# 4. Deploy services (modify k8s/*.yaml to use local images)
kubectl apply -f k8s/ -n atlas-local

# 5. Port-forward to access locally
kubectl port-forward -n atlas-local svc/frontend 8080:80

# Access: http://localhost:8080
```

**Note**: Local K8s useful for testing manifests before Azure deployment.

---

## Azure AKS Deployment

### Step 1: Azure Resources Setup

```bash
# 1. Login to Azure
az login

# 2. Set subscription (if multiple)
az account set --subscription "your-subscription-id"

# 3. Create resource group
az group create \
  --name atlas-rg \
  --location eastus

# 4. Create container registry (Standard tier, free for students)
az acr create \
  --resource-group atlas-rg \
  --name atlasacrp1 \
  --sku Standard

# 5. Enable admin access (for docker push)
az acr update --name atlasacrp1 --admin-enabled true

# 6. Get ACR credentials
az acr credential show --name atlasacrp1

# 7. Login to ACR
az acr login --name atlasacrp1
```

### Step 2: Create AKS Cluster

```bash
# Create AKS cluster
az aks create \
  --resource-group atlas-rg \
  --name atlas-aks \
  --node-count 1 \
  --node-vm-size Standard_B2s_v2 \
  --location eastus \
  --generate-ssh-keys \
  --attach-acr atlasacrp1 \
  --enable-managed-identity

# Get credentials for kubectl
az aks get-credentials --resource-group atlas-rg --name atlas-aks

# Verify connection
kubectl get nodes
```

### Step 3: Build and Push Images

```bash
# Set ACR name as variable
ACR=atlasacrp1.azurecr.io

# Build and tag images (multi-architecture if needed)
docker build -f frontend/Dockerfile.prod -t $ACR/frontend:v1 frontend/
docker build -t $ACR/user-service:v1 services/user-service/
docker build -t $ACR/catalog-service:v1 services/catalog-service/
docker build -t $ACR/api-gateway:v1 services/api-gateway/
docker build -f services/recommendation-service/Dockerfile -t $ACR/recommendation-service:v1 .

# Push to ACR
docker push $ACR/frontend:v1
docker push $ACR/user-service:v1
docker push $ACR/catalog-service:v1
docker push $ACR/api-gateway:v1
docker push $ACR/recommendation-service:v1

# Verify images
az acr repository list --name atlasacrp1 --output table
```

**Build Time**: ~5-7 minutes for all services

### Step 4: Deploy to AKS

```bash
# 1. Create namespace
kubectl create namespace atlas

# 2. Create secrets (database password, JWT secret)
kubectl create secret generic postgres-secret \
  --from-literal=password=your-secure-password \
  -n atlas

kubectl create secret generic jwt-secret \
  --from-literal=secret=your-jwt-secret-key \
  -n atlas

# 3. Deploy all services
kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/postgres.yaml
kubectl apply -f k8s/redis.yaml
kubectl apply -f k8s/user-service.yaml
kubectl apply -f k8s/catalog-service.yaml
kubectl apply -f k8s/recommendation-service.yaml
kubectl apply -f k8s/api-gateway.yaml
kubectl apply -f k8s/frontend.yaml

# 4. Check pod status
kubectl get pods -n atlas

# Wait until all pods are Running and healthy
```

### Step 5: Install NGINX Ingress

```bash
# Install NGINX Ingress Controller
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.10.0/deploy/static/provider/cloud/deploy.yaml

# Wait for load balancer IP
kubectl get svc -n ingress-nginx

# Get public IP
kubectl get svc ingress-nginx-controller -n ingress-nginx -o jsonpath='{.status.loadBalancer.ingress[0].ip}'

# Example output: 4.224.153.183
```

### Step 6: Configure Ingress

```yaml
# k8s/ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: atlas-ingress
  namespace: atlas
  annotations:
    nginx.ingress.kubernetes.io/ssl-redirect: "false"  # Will enable after HTTPS setup
spec:
  ingressClassName: nginx
  rules:
  - http:
      paths:
      - path: /api
        pathType: Prefix
        backend:
          service:
            name: api-gateway
            port:
              number: 8000
      - path: /
        pathType: Prefix
        backend:
          service:
            name: frontend
            port:
              number: 80
```

```bash
# Apply ingress
kubectl apply -f k8s/ingress.yaml

# Access application (HTTP for now)
# http://4.224.153.183/
```

### Step 7: Database Migrations and Seeding

```bash
# Run migrations
kubectl exec -n atlas deployment/user-service -- alembic upgrade head
kubectl exec -n atlas deployment/catalog-service -- alembic upgrade head

# Seed database (use seed script or copy from local)
# Option 1: Copy seed script to pod
kubectl cp tools/seed-data/amazon_products.json atlas/postgres-pod:/tmp/
kubectl cp tools/seed-data/seed_k8s_from_files.py atlas/postgres-pod:/tmp/

# Option 2: Run seed script directly
kubectl exec -n atlas deployment/catalog-service -- python /app/scripts/seed_data.py
```

---

## HTTPS with Let's Encrypt

### Step 1: Install cert-manager

```bash
# Install cert-manager (automated certificate management)
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml

# Verify installation
kubectl get pods -n cert-manager
```

### Step 2: Configure Let's Encrypt Issuer

```yaml
# k8s/letsencrypt-issuer.yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-staging  # Use staging first (no rate limits)
spec:
  acme:
    email: your-email@example.com
    server: https://acme-staging-v02.api.letsencrypt.org/directory
    privateKeySecretRef:
      name: letsencrypt-staging
    solvers:
    - http01:
        ingress:
          class: nginx
```

```bash
kubectl apply -f k8s/letsencrypt-issuer.yaml
```

### Step 3: Update Ingress for HTTPS

```yaml
# k8s/ingress.yaml (updated)
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: atlas-ingress
  namespace: atlas
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-staging
    nginx.ingress.kubernetes.io/ssl-redirect: "true"  # Force HTTPS
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - 4-224-153-183.sslip.io  # Free wildcard DNS
    secretName: atlas-tls
  rules:
  - host: 4-224-153-183.sslip.io
    http:
      paths:
      - path: /api
        pathType: Prefix
        backend:
          service:
            name: api-gateway
            port:
              number: 8000
      - path: /
        pathType: Prefix
        backend:
          service:
            name: frontend
            port:
              number: 80
```

```bash
# Apply updated ingress
kubectl apply -f k8s/ingress.yaml

# Watch certificate creation
kubectl get certificate -n atlas -w

# Wait for "Ready=True"
```

### Step 4: Verify HTTPS

```bash
# Check certificate status
kubectl describe certificate atlas-tls -n atlas

# Access application over HTTPS
# https://4-224-153-183.sslip.io/
```

### Staging vs Production Certificates

**Let's Encrypt Staging** (current):
- [!] Browser shows "Not Secure" warning (staging CA not trusted)
- [✓] No rate limits (unlimited certificate issuance)
- [✓] Proves TLS infrastructure works
- [✓] Safe for testing

**Let's Encrypt Production**:
- [✓] Trusted by browsers (no warnings)
- [!] Rate limited: 50 certificates per registered domain per week
- [!] Free wildcard DNS services (`nip.io`, `sslip.io`) often hit rate limits

**Why Staging Certificate?**

Both `nip.io` and `sslip.io` hit Let's Encrypt production rate limits (25,000 certificates issued in last 7 days). To switch to production:

1. **Option A**: Wait 7 days for rate limit reset
2. **Option B**: Use custom domain

**To Switch to Production**:
```yaml
# Change issuer in ingress.yaml
cert-manager.io/cluster-issuer: letsencrypt-prod

# Delete old certificate
kubectl delete certificate atlas-tls -n atlas

# Reapply ingress (triggers new certificate)
kubectl apply -f k8s/ingress.yaml
```

---

## Monitoring and Maintenance

### Health Checks

```bash
# Check pod health
kubectl get pods -n atlas

# View pod logs
kubectl logs -n atlas deployment/recommendation-service --tail=100

# Describe pod (for troubleshooting)
kubectl describe pod -n atlas <pod-name>

# Check resource usage
kubectl top pods -n atlas
kubectl top nodes
```

### Scaling

```bash
# Scale deployment manually
kubectl scale deployment recommendation-service --replicas=3 -n atlas

# Enable horizontal pod autoscaling
kubectl autoscale deployment recommendation-service \
  --cpu-percent=70 \
  --min=1 \
  --max=5 \
  -n atlas
```

### Rolling Updates

```bash
# Update image (zero-downtime deployment)
docker build -f frontend/Dockerfile.prod -t atlasacrp1.azurecr.io/frontend:v2 frontend/
docker push atlasacrp1.azurecr.io/frontend:v2

kubectl set image deployment/frontend frontend=atlasacrp1.azurecr.io/frontend:v2 -n atlas

# Watch rollout
kubectl rollout status deployment/frontend -n atlas

# Rollback if issues
kubectl rollout undo deployment/frontend -n atlas
```

### Database Backups

```bash
# Export database dump
kubectl exec -n atlas deployment/postgres -- pg_dump -U postgres ecommerce > backup.sql

# Copy to Azure Blob Storage (future)
az storage blob upload \
  --account-name atlasstorage \
  --container-name backups \
  --name backup-$(date +%Y%m%d).sql \
  --file backup.sql
```

---

## Troubleshooting

### Common Issues

**1. Pod CrashLoopBackOff**
```bash
# Check logs
kubectl logs -n atlas <pod-name> --previous

# Common causes:
# - Missing environment variables
# - Database connection failure
# - Port conflicts
```

**2. Ingress 404 Not Found**
```bash
# Verify ingress rules
kubectl describe ingress atlas-ingress -n atlas

# Check service endpoints
kubectl get endpoints -n atlas

# Test service directly (bypass ingress)
kubectl port-forward -n atlas svc/api-gateway 8000:8000
curl http://localhost:8000/health
```

**3. Database Migration Fails**
```bash
# Check database connectivity
kubectl exec -n atlas deployment/catalog-service -- env | grep DATABASE_URL

# Run migration manually
kubectl exec -n atlas deployment/catalog-service -- alembic upgrade head

# Check migration history
kubectl exec -n atlas deployment/catalog-service -- alembic current
```

**4. Let's Encrypt Rate Limit**
```bash
# Check certificate status
kubectl describe certificate atlas-tls -n atlas

# Look for: "too many certificates already issued"

# Solution: Use staging issuer or wait 7 days
```

**5. Image Pull Errors**
```bash
# Verify ACR authentication
az acr login --name atlasacrp1

# Check AKS has ACR pull permissions
az aks check-acr --resource-group atlas-rg --name atlas-aks --acr atlasacrp1
```

---

## Deployment Checklist

### Pre-Deployment
- [ ] All services build successfully locally
- [ ] Database migrations tested
- [ ] ML models exported to `notebooks/artifacts/`
- [ ] Environment variables configured
- [ ] Secrets created in Kubernetes

### Deployment
- [ ] Images pushed to ACR
- [ ] Kubernetes manifests applied
- [ ] All pods Running and healthy
- [ ] Database migrations executed
- [ ] Database seeded with products
- [ ] Ingress configured and accessible

### Post-Deployment
- [ ] HTTPS certificate issued
- [ ] Frontend loads correctly
- [ ] API endpoints respond (test with `/docs`)
- [ ] Recommendations endpoint works
- [ ] User registration and login functional
- [ ] Session tracking operational (Redis)

### Monitoring
- [ ] Set up log aggregation (future)
- [ ] Configure alerts (future)
- [ ] Monitor resource usage
- [ ] Track recommendation CTR
- [ ] Schedule database backups

---

## Production Best Practices (Future)

1. **CI/CD Pipeline**
   ```yaml
   # .github/workflows/deploy.yml
   - Build images on push to main
   - Run tests
   - Push to ACR
   - Update Kubernetes deployments
   - Run smoke tests
   ```

2. **Environment Separation**
   ```
   - Development: Local K8s
   - Staging: AKS cluster (small node pool)
   - Production: AKS cluster (auto-scaling)
   ```

3. **Secret Management**
   ```bash
   # Use Azure Key Vault
   az keyvault create --name atlas-kv --resource-group atlas-rg
   kubectl create secret generic db-password --from-literal=password=$(az keyvault secret show --name db-password --vault-name atlas-kv --query value -o tsv)
   ```

4. **Monitoring Stack**
   ```
   - Prometheus (metrics)
   - Grafana (dashboards)
   - Loki (logs)
   - Jaeger (distributed tracing)
   ```

5. **Database High Availability**
   ```
   - Use Azure Database for PostgreSQL (managed)
   - Read replicas for scaling
   - Automated backups
   - Point-in-time restore
   ```

---

## Summary

**Deployment Path**:
1. Local Docker Compose → Test all services
2. Local Kubernetes → Validate manifests
3. Azure AKS → Production deployment
4. NGINX Ingress → Traffic routing
5. Let's Encrypt → HTTPS encryption

**Current State**:
- [✓] Deployed to Azure AKS
- [✓] Public IP: `4.224.153.183`
- [✓] HTTPS: `https://4-224-153-183.sslip.io/`
- [✓] All services healthy
- [!] Staging certificate (browser warning)

**Production-Ready Improvements**:
- [ ] Switch to production TLS certificate (custom domain or wait for rate limit reset)
- [ ] Implement CI/CD pipeline
- [ ] Set up monitoring and alerting
- [ ] Configure auto-scaling
- [ ] Add database backups

---

**Next Steps**: Test application at https://4-224-153-183.sslip.io/, then iterate based on user feedback and performance metrics.

---

## Render, Vercel, Neon, and Upstash Deployment Blueprint

### Render Blueprint Scope

The repository now includes [render.yaml](render.yaml), which defines four Docker-based Render services on the free tier. PostgreSQL is provided by Neon, and Redis is provided by Upstash.

| Service | Root directory | Dockerfile | Health check | Notes |
|---|---|---|---|---|
| api-gateway | `services/api-gateway` | `services/api-gateway/Dockerfile` | `/health` | Public web service |
| user-service | `services/user-service` | `services/user-service/Dockerfile` | `/api/auth/ping` | Public web service |
| catalog-service | `services/catalog-service` | `services/catalog-service/Dockerfile` | `/api/v1/catalog/health` | Public web service |
| recommendation-service | `.` | `services/recommendation-service/Dockerfile` | `/health` | Repo root build context so ML artifacts can be copied in |

### Service Environment Variables

#### api-gateway

Required:
- `USER_SERVICE_URL`
- `CATALOG_SERVICE_URL`
- `RECOMMENDATION_SERVICE_URL`

Optional:
- None used by the current code

Example production values:
- `https://user-service.onrender.com`
- `https://catalog-service.onrender.com`
- `https://recommendation-service.onrender.com`

Dependencies:
- User service
- Catalog service
- Recommendation service

#### user-service

Required:
- `POSTGRES_URI`
- `JWT_SECRET`

Optional:
- `SERVICE_NAME`
- `SERVICE_PORT`
- `JWT_ALGORITHM`
- `JWT_EXPIRATION_HOURS`
- `BCRYPT_ROUNDS`

Example production values:
- `POSTGRES_URI` copied from Neon
- `JWT_SECRET` set manually in Render

Dependencies:
- Neon PostgreSQL

#### catalog-service

Required:
- `DATABASE_URL`

Optional:
- `SERVICE_NAME`
- `SERVICE_PORT`
- `LOG_LEVEL`
- `API_V1_PREFIX`
- `DEFAULT_PAGE_SIZE`
- `MAX_PAGE_SIZE`
- `USD_TO_INR_RATE`

Example production values:
- `DATABASE_URL` copied from Neon

Dependencies:
- Neon PostgreSQL
- Seed data for `categories`, `products`, `sellers`, and `latent_item_mappings`

#### recommendation-service

Required:
- `DATABASE_URL`
- `CATALOG_SERVICE_URL`
- `REDIS_URL` if `REDIS_ENABLED=true`

Optional:
- `SERVICE_NAME`
- `SERVICE_PORT`
- `LOG_LEVEL`
- `REDIS_ENABLED`
- `REDIS_TTL_SECONDS`
- `ARTIFACTS_PATH`
- `MODEL_VERSION`
- `CANDIDATE_POOL_SIZE`
- `MAX_RECOMMENDATIONS`
- `DEFAULT_RECOMMENDATIONS`
- `CONFIDENCE_THRESHOLD`
- `MAX_ITEMS_PER_CATEGORY`
- `POPULARITY_FALLBACK_SIZE`
- `ENABLE_SVD`
- `ENABLE_ITEM_SIMILARITY`
- `ENABLE_LIGHTGBM_RANKING`

Example production values:
- `DATABASE_URL` copied from Neon
- `CATALOG_SERVICE_URL=https://catalog-service.onrender.com`
- `REDIS_URL=rediss://...` from Upstash
- `MODEL_VERSION=production_v1`

Dependencies:
- Neon PostgreSQL
- Catalog service
- Upstash Redis when session tracking is enabled

### Health Check Verification

Correct endpoints:
- api-gateway: `/health`
- user-service: `/api/auth/ping`
- catalog-service: `/api/v1/catalog/health`
- recommendation-service: `/health`

Expected startup behavior:
- api-gateway starts immediately and proxies downstream traffic on demand
- user-service initializes SQLAlchemy tables on startup via `create_all()`
- catalog-service verifies PostgreSQL connectivity during lifespan startup
- recommendation-service loads ML models and feature tables during lifespan startup, then defers database connection until first request

### Deployment Order

1. Create Neon PostgreSQL
2. Create Upstash Redis
3. Deploy user-service
4. Deploy catalog-service
5. Run manual migrations
6. Seed database
7. Deploy recommendation-service
8. Deploy api-gateway
9. Deploy frontend on Vercel

### Required Manual Dashboard Steps

Neon:
- Create a Neon project and PostgreSQL database
- Copy the Neon connection string into `POSTGRES_URI` for user-service
- Copy the same Neon connection string into `DATABASE_URL` for catalog-service and recommendation-service

Render:
- Create the Render Blueprint from `render.yaml`
- Enter `USER_SERVICE_URL`, `CATALOG_SERVICE_URL`, and `RECOMMENDATION_SERVICE_URL` values for the gateway
- Enter `CATALOG_SERVICE_URL` for recommendation-service
- Enter `REDIS_URL` for recommendation-service
- Set `JWT_SECRET` manually in Render
- Run manual migrations after deployment
- Seed catalog data after the database is live

Vercel:
- Set `VITE_API_URL` to the Render gateway base URL, including `/api`
- Use `frontend` as the project root
- Build command: `npm run build`
- Output directory: `dist`

Upstash:
- Create a Redis database
- Copy the secure `rediss://` connection string into `REDIS_URL`

### Manual Migration Commands

Run these after the corresponding services are up and the Neon connection string is configured:

```bash
cd services/user-service
alembic upgrade head

cd ../catalog-service
alembic upgrade head
```

If you run them from Render shell, use the same commands inside each service directory after the service is deployed.

### Render Free-Tier Limitations

- Free instances are not suitable for the recommendation service's startup cost and memory footprint.
- Private services are not available on the free plan, so the backend services must be reachable by public Render URLs.
- The recommendation service loads ML artifacts at startup, so cold starts and memory ceilings are the main operational risk.
- Free-tier services can sleep when idle, which increases first-request latency.
- The recommendation service may need extra startup time because it loads models, Parquet features, and a database connection pool initialization path.
- Neon and Upstash are external managed services, so network latency becomes part of end-to-end request time.

### Notes on Unused Deployment Artifacts

- `frontend/Dockerfile` and `frontend/nginx.conf` remain useful for Docker-based local workflows, but Vercel does not use them.
- The frontend Vite dev proxy still targets the Docker Compose gateway hostname for local development.
- Docker support is preserved throughout the repository.
- This deployment blueprint does not simplify the architecture; it only swaps infrastructure providers and delivery settings.
