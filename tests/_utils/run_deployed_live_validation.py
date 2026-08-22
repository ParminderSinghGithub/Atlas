"""
Deployed Live Validation Script for Atlas Production Infrastructure.
Tests all deployed service endpoints, auth, cart, catalog, recommendations, and OCI inference.
"""
import httpx
import json
import uuid
import time
import sys

GATEWAY_URL = 'https://api-gateway-mmoc.onrender.com'
CATALOG_URL = 'https://catalog-service-uo46.onrender.com'
REC_URL = 'https://recommendation-service-8ag0.onrender.com'
USER_URL = 'https://user-service-rzbt.onrender.com'
OCI_URL = 'http://150.230.143.133:8001'
FRONTEND_URL = 'https://atlas-six-roan.vercel.app'

REAL_PRODUCT_ID = '00378575-74d5-5f9a-9724-0b4333a419dd'
INVALID_PRODUCT_ID = '00000000-0000-0000-0000-000000000000'

results = []

def run_test(name, fn):
    t0 = time.time()
    try:
        status, details = fn()
        duration = round((time.time() - t0) * 1000, 1)
        results.append({'name': name, 'status': status, 'latency_ms': duration, 'details': details})
        print(f"[{status}] {name} ({duration}ms) - {details}")
    except Exception as e:
        duration = round((time.time() - t0) * 1000, 1)
        results.append({'name': name, 'status': 'FAIL', 'latency_ms': duration, 'details': str(e)})
        print(f"[FAIL] {name} ({duration}ms) - Error: {e}")

print("================================================================================")
print("  ATLAS LIVE DEPLOYED INFRASTRUCTURE & END-TO-END VALIDATION")
print("================================================================================")

with httpx.Client(timeout=35.0) as client:
    # 1. Vercel Frontend
    r1 = client.get(FRONTEND_URL)
    run_test('1. Vercel Frontend HTTP Availability', lambda: (
        'PASS' if r1.status_code == 200 else 'FAIL',
        f'HTTP {r1.status_code}'
    ))

    # 2. Direct Catalog Service Health
    r2 = client.get(f"{CATALOG_URL}/health")
    run_test('2. Direct Catalog Service Health', lambda: (
        'PASS' if r2.status_code == 200 else 'FAIL',
        r2.json().get('status', 'unknown')
    ))

    # 3. Direct Recommendation Service Health
    r3 = client.get(f"{REC_URL}/health")
    run_test('3. Direct Recommendation Service Health', lambda: (
        'PASS' if r3.status_code == 200 else 'FAIL',
        r3.json().get('status', 'unknown')
    ))

    # 4. Direct User Service Auth Ping
    r4 = client.get(f"{USER_URL}/api/auth/ping")
    run_test('4. Direct User Service Auth Ping', lambda: (
        'PASS' if r4.status_code == 200 else 'FAIL',
        r4.json().get('status', 'unknown')
    ))

    # 5. Direct OCI ML Health
    r5 = client.get(f"{OCI_URL}/health")
    run_test('5. Direct OCI ML Inference Health', lambda: (
        'PASS' if r5.status_code == 200 else 'FAIL',
        r5.json().get('service', 'unknown')
    ))

    # 6. Direct OCI ML Item Similarity Inference (RetailRocket item 359491)
    r6 = client.post(f"{OCI_URL}/api/v1/infer", json={'user_id': '100', 'item_id': 359491, 'k': 5, 'strategy': 'item_similarity'})
    run_test('6. Direct OCI ML Item Similarity (RetailRocket ID 359491)', lambda: (
        'PASS' if r6.status_code == 200 and r6.json().get('status') == 'success' else 'FAIL',
        f"strategy={r6.json().get('strategy_used')}, items={len(r6.json().get('items', []))}"
    ))

    # 7. Direct OCI ML LightGBM Ranking Inference
    r7 = client.post(f"{OCI_URL}/api/v1/infer", json={'user_id': '100', 'item_ids': [1000, 100002, 100004], 'strategy': 'ranker'})
    run_test('7. Direct OCI ML Ranker (LightGBM)', lambda: (
        'PASS' if r7.status_code == 200 and r7.json().get('status') == 'success' else 'FAIL',
        f"strategy={r7.json().get('strategy_used')}, items={len(r7.json().get('items', []))}"
    ))

    # 8. Direct OCI ML Unknown Item Graceful Fallback
    r8 = client.post(f"{OCI_URL}/api/v1/infer", json={'user_id': '100', 'item_id': 999999999, 'k': 5, 'strategy': 'item_similarity'})
    run_test('8. Direct OCI ML Unknown Item Fallback', lambda: (
        'PASS' if r8.status_code == 200 and r8.json().get('status') == 'cold_start' else 'FAIL',
        f"strategy={r8.json().get('strategy_used')}"
    ))

    # 9. Gateway System Readiness
    r9 = client.get(f"{GATEWAY_URL}/api/v1/ready")
    run_test('9. Gateway Coordinated Readiness (/api/v1/ready)', lambda: (
        'PASS' if r9.status_code == 200 else 'FAIL',
        f"status={r9.json().get('status')}, ready={r9.json().get('summary', {}).get('ready')}/{r9.json().get('summary', {}).get('total')}"
    ))

    # 10. Gateway Catalog Products
    r10 = client.get(f"{GATEWAY_URL}/api/v1/catalog/products?limit=10")
    run_test('10. Gateway Catalog Products Query', lambda: (
        'PASS' if r10.status_code == 200 else 'FAIL',
        f"returned={len(r10.json().get('products', []))} products"
    ))

    # 11. Gateway Catalog Categories
    r11 = client.get(f"{GATEWAY_URL}/api/v1/catalog/categories")
    run_test('11. Gateway Catalog Categories Query', lambda: (
        'PASS' if r11.status_code == 200 else 'FAIL',
        f"returned={len(r11.json().get('categories', []))} categories"
    ))

    # 12. Gateway Valid Product Detail
    r12 = client.get(f"{GATEWAY_URL}/api/v1/catalog/products/{REAL_PRODUCT_ID}")
    run_test('12. Gateway Product Detail (Valid UUID)', lambda: (
        'PASS' if r12.status_code == 200 else 'FAIL',
        r12.json().get('name', '')[:35]
    ))

    # 13. Gateway Invalid Product Detail
    r13 = client.get(f"{GATEWAY_URL}/api/v1/catalog/products/{INVALID_PRODUCT_ID}")
    run_test('13. Gateway Product Detail (Invalid UUID -> 404)', lambda: (
        'PASS' if r13.status_code == 404 else 'FAIL',
        f"HTTP {r13.status_code}"
    ))

    # 14. Gateway Guest Recommendations
    guest_id = str(uuid.uuid4())
    r14 = client.get(f"{GATEWAY_URL}/api/v1/recommendations?user_id={guest_id}&k=8")
    run_test('14. Gateway Guest Recommendations', lambda: (
        'PASS' if r14.status_code == 200 else 'FAIL',
        f"strategy={r14.json().get('strategy_used')}, count={len(r14.json().get('recommendations', []))}"
    ))

    # 15. Gateway Similar Products Recommendations
    r15 = client.get(f"{GATEWAY_URL}/api/v1/recommendations?product_id={REAL_PRODUCT_ID}&k=4")
    run_test('15. Gateway Similar Products Recommendations', lambda: (
        'PASS' if r15.status_code == 200 else 'FAIL',
        f"strategy={r15.json().get('strategy_used')}, count={len(r15.json().get('recommendations', []))}"
    ))

    # 16. Gateway Event Ingestion
    event_payload = {
        'user_id': guest_id,
        'product_id': REAL_PRODUCT_ID,
        'event_type': 'view',
        'session_id': str(uuid.uuid4())
    }
    r16 = client.post(f"{GATEWAY_URL}/api/events", json=event_payload)
    run_test('16. Gateway Event Ingestion (POST /api/events)', lambda: (
        'PASS' if r16.status_code in [200, 201] else 'FAIL',
        f"HTTP {r16.status_code}"
    ))

    # 17. User Auth Lifecycle (Register -> Login -> /me)
    test_user_email = f"val_{int(time.time())}@atlas-validation.dev"
    test_user_pass = "StrongPass123!"

    r17 = client.post(f"{GATEWAY_URL}/api/auth/register", json={'name': 'Atlas Validator', 'email': test_user_email, 'password': test_user_pass})
    run_test('17. Gateway Auth Registration', lambda: (
        'PASS' if r17.status_code in [200, 201] else 'FAIL',
        f"HTTP {r17.status_code}"
    ))

    r18 = client.post(f"{GATEWAY_URL}/api/auth/login", json={'email': test_user_email, 'password': test_user_pass})
    token = r18.json().get('token') or r18.json().get('access_token')
    run_test('18. Gateway Auth Login', lambda: (
        'PASS' if r18.status_code == 200 and token else 'FAIL',
        f"Token present: {bool(token)}"
    ))

    if token:
        r19 = client.get(f"{GATEWAY_URL}/api/auth/me", headers={'Authorization': f'Bearer {token}'})
        run_test('19. Gateway Authenticated Profile (/api/auth/me)', lambda: (
            'PASS' if r19.status_code == 200 else 'FAIL',
            f"user={r19.json().get('email')}"
        ))

    # 20. Password Reset Request Flow
    r20 = client.post(f"{GATEWAY_URL}/api/auth/forgot-password", json={'email': test_user_email})
    run_test('20. Gateway Password Reset Request (/api/auth/forgot-password)', lambda: (
        'PASS' if r20.status_code == 200 else 'FAIL',
        r20.json().get('message', '')[:45]
    ))

print("================================================================================")
passed = sum(1 for r in results if r['status'] == 'PASS')
print(f"DEPLOYED TEST SUMMARY: {passed}/{len(results)} PASSED")
print("================================================================================")
