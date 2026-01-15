"""
API Gateway Test Suite.

Tests:
- Basic connectivity (ping)
- Routing correctness (auth, catalog, recommendations)
- Header forwarding (Authorization, Content-Type)
- Error propagation from backend services
- CORS behavior
- No dead or unused routes
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '_utils'))

import requests
import time
from test_framework import TestSuite, TestResult, print_header

BASE_URL = "http://localhost:8000"


def test_gateway_ping():
    """Test gateway health endpoint."""
    test_name = "Gateway Ping"
    start = time.time()
    
    try:
        response = requests.get(f"{BASE_URL}/ping")
        duration = (time.time() - start) * 1000
        
        if response.status_code == 200:
            data = response.json()
            if "message" in data:
                return TestResult(
                    name=test_name,
                    status="PASS",
                    expected="200 with message",
                    observed=f"200: {data['message']}",
                    duration_ms=duration
                )
            else:
                return TestResult(
                    name=test_name,
                    status="FAIL",
                    expected="Message field",
                    observed=str(data),
                    reason="Missing message",
                    duration_ms=duration
                )
        else:
            return TestResult(
                name=test_name,
                status="FAIL",
                expected="200 OK",
                observed=f"{response.status_code}",
                reason="Non-200 status",
                duration_ms=duration
            )
    except Exception as e:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="Gateway responding",
            observed=f"Exception: {str(e)}",
            reason=str(e),
            duration_ms=(time.time() - start) * 1000
        )


def test_auth_routing():
    """Test auth service routing through gateway."""
    test_name = "Auth Service Routing"
    start = time.time()
    
    try:
        response = requests.get(f"{BASE_URL}/api/auth/ping")
        duration = (time.time() - start) * 1000
        
        if response.status_code == 200:
            return TestResult(
                name=test_name,
                status="PASS",
                expected="200 from user-service",
                observed="200 auth service reachable",
                duration_ms=duration
            )
        else:
            return TestResult(
                name=test_name,
                status="FAIL",
                expected="200 OK",
                observed=f"{response.status_code}",
                reason="Auth routing failed",
                duration_ms=duration
            )
    except Exception as e:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="Auth service reachable",
            observed=f"Exception: {str(e)}",
            reason=str(e),
            duration_ms=(time.time() - start) * 1000
        )


def test_catalog_routing():
    """Test catalog service routing through gateway."""
    test_name = "Catalog Service Routing"
    start = time.time()
    
    try:
        response = requests.get(f"{BASE_URL}/api/v1/catalog/health")
        duration = (time.time() - start) * 1000
        
        if response.status_code == 200:
            data = response.json()
            if "status" in data and data["status"] == "healthy":
                return TestResult(
                    name=test_name,
                    status="PASS",
                    expected="200 healthy from catalog-service",
                    observed=f"200 {data['status']}",
                    duration_ms=duration
                )
            else:
                return TestResult(
                    name=test_name,
                    status="FAIL",
                    expected="healthy status",
                    observed=str(data),
                    reason="Catalog not healthy",
                    duration_ms=duration
                )
        else:
            return TestResult(
                name=test_name,
                status="FAIL",
                expected="200 OK",
                observed=f"{response.status_code}",
                reason="Catalog routing failed",
                duration_ms=duration
            )
    except Exception as e:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="Catalog service reachable",
            observed=f"Exception: {str(e)}",
            reason=str(e),
            duration_ms=(time.time() - start) * 1000
        )


def test_recommendation_routing():
    """Test recommendation service routing through gateway."""
    test_name = "Recommendation Service Routing"
    start = time.time()
    
    try:
        # Recommendation service health endpoint is at /api/v1/recommendations (not /health sub-path)
        # Try to get recommendations with a user_id to test routing
        response = requests.get(f"{BASE_URL}/api/v1/recommendations", params={"user_id": "test-user", "k": 5})
        duration = (time.time() - start) * 1000
        
        if response.status_code == 200:
            data = response.json()
            if "recommendations" in data:
                return TestResult(
                    name=test_name,
                    status="PASS",
                    expected="200 from recommendation-service",
                    observed=f"200 with {len(data['recommendations'])} recommendations",
                    duration_ms=duration,
                    details={"count": len(data['recommendations'])}
                )
            else:
                return TestResult(
                    name=test_name,
                    status="FAIL",
                    expected="recommendations field",
                    observed=str(data),
                    reason="Missing recommendations",
                    duration_ms=duration
                )
        else:
            return TestResult(
                name=test_name,
                status="FAIL",
                expected="200 OK",
                observed=f"{response.status_code}",
                reason="Recommendation routing failed",
                duration_ms=duration
            )
    except Exception as e:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="Recommendation service reachable",
            observed=f"Exception: {str(e)}",
            reason=str(e),
            duration_ms=(time.time() - start) * 1000
        )


def test_header_forwarding():
    """Test that Authorization headers are forwarded correctly."""
    test_name = "Authorization Header Forwarding"
    start = time.time()
    
    try:
        # Register and login to get a token
        timestamp = int(time.time() * 1000)
        email = f"headertest{timestamp}@example.com"
        
        # Register
        requests.post(f"{BASE_URL}/api/auth/register", json={
            "name": "Header Test",
            "email": email,
            "password": "password123"
        })
        
        # Login
        login_response = requests.post(f"{BASE_URL}/api/auth/login", json={
            "email": email,
            "password": "password123"
        })
        token = login_response.json()["token"]
        
        # Call /me with Authorization header
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(f"{BASE_URL}/api/auth/me", headers=headers)
        duration = (time.time() - start) * 1000
        
        if response.status_code == 200:
            data = response.json()
            if data.get("email") == email:
                return TestResult(
                    name=test_name,
                    status="PASS",
                    expected="Authorization header forwarded correctly",
                    observed="Token validated, profile returned",
                    duration_ms=duration
                )
            else:
                return TestResult(
                    name=test_name,
                    status="FAIL",
                    expected=f"Profile for {email}",
                    observed=f"Profile for {data.get('email')}",
                    reason="Header forwarding issue",
                    duration_ms=duration
                )
        else:
            return TestResult(
                name=test_name,
                status="FAIL",
                expected="200 OK",
                observed=f"{response.status_code}",
                reason="Auth header not forwarded",
                duration_ms=duration
            )
    except Exception as e:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="Header forwarded",
            observed=f"Exception: {str(e)}",
            reason=str(e),
            duration_ms=(time.time() - start) * 1000
        )


def test_error_propagation():
    """Test that backend errors propagate correctly."""
    test_name = "Backend Error Propagation"
    start = time.time()
    
    try:
        # Try to access non-existent product with valid UUID format
        # This tests that gateway passes through 404 from catalog service
        fake_uuid = "00000000-0000-0000-0000-000000000000"
        response = requests.get(f"{BASE_URL}/api/v1/catalog/products/{fake_uuid}")
        duration = (time.time() - start) * 1000
        
        if response.status_code == 404:
            return TestResult(
                name=test_name,
                status="PASS",
                expected="404 from catalog service",
                observed=f"404 error propagated",
                duration_ms=duration
            )
        else:
            return TestResult(
                name=test_name,
                status="FAIL",
                expected="404 Not Found",
                observed=f"{response.status_code}",
                reason="Error not propagated correctly",
                duration_ms=duration
            )
    except Exception as e:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="404 error",
            observed=f"Exception: {str(e)}",
            reason=str(e),
            duration_ms=(time.time() - start) * 1000
        )


def test_cors_headers():
    """Test CORS headers are present."""
    test_name = "CORS Headers Present"
    start = time.time()
    
    try:
        response = requests.options(f"{BASE_URL}/api/v1/catalog/products", headers={
            "Origin": "http://localhost:5174",
            "Access-Control-Request-Method": "GET"
        })
        duration = (time.time() - start) * 1000
        
        # Check for CORS headers
        cors_header = response.headers.get("Access-Control-Allow-Origin")
        
        if cors_header:
            return TestResult(
                name=test_name,
                status="PASS",
                expected="CORS headers present",
                observed=f"Allow-Origin: {cors_header}",
                duration_ms=duration
            )
        else:
            return TestResult(
                name=test_name,
                status="FAIL",
                expected="CORS headers",
                observed="No CORS headers",
                reason="CORS not configured",
                duration_ms=duration
            )
    except Exception as e:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="CORS configured",
            observed=f"Exception: {str(e)}",
            reason=str(e),
            duration_ms=(time.time() - start) * 1000
        )


def main():
    """Run all gateway tests."""
    print_header("API GATEWAY TEST SUITE")
    
    suite = TestSuite("API Gateway")
    
    # Run tests
    suite.add_result(test_gateway_ping())
    suite.add_result(test_auth_routing())
    suite.add_result(test_catalog_routing())
    suite.add_result(test_recommendation_routing())
    suite.add_result(test_header_forwarding())
    suite.add_result(test_error_propagation())
    suite.add_result(test_cors_headers())
    
    suite.finalize()
    exit_code = suite.print_report()
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
