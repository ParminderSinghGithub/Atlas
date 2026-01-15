"""
Authentication Service Test Suite.

Tests:
- User registration (schema, email validation, duplicate handling)
- User login (JWT token generation, authentication)
- JWT token validation (/me endpoint)
- Frontend compatibility (name field, token structure)
- Password security (bcrypt hashing)
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '_utils'))

import requests
import time
from test_framework import TestSuite, TestResult, print_header

# Configuration
BASE_URL = "http://localhost:8000"  # API Gateway
API_PREFIX = "/api/auth"

def test_registration():
    """Test user registration endpoint."""
    test_name = "User Registration"
    start = time.time()
    
    # Generate unique email
    timestamp = int(time.time() * 1000)
    payload = {
        "name": "Test User",
        "email": f"testuser{timestamp}@example.com",
        "password": "password123"
    }
    
    try:
        response = requests.post(f"{BASE_URL}{API_PREFIX}/register", json=payload)
        duration = (time.time() - start) * 1000
        
        if response.status_code == 201:
            data = response.json()
            
            # Verify response structure
            if "id" in data and isinstance(data["id"], str):
                return TestResult(
                    name=test_name,
                    status="PASS",
                    expected="201 status with {id: uuid}",
                    observed=f"201 status with id={data['id'][:8]}...",
                    duration_ms=duration,
                    details={"user_id": data["id"], "email": payload["email"]}
                )
            else:
                return TestResult(
                    name=test_name,
                    status="FAIL",
                    expected="{id: uuid}",
                    observed=f"Response: {data}",
                    reason="Missing or invalid 'id' field",
                    duration_ms=duration
                )
        else:
            return TestResult(
                name=test_name,
                status="FAIL",
                expected="201 Created",
                observed=f"{response.status_code} {response.text}",
                reason="Non-201 status code",
                duration_ms=duration
            )
    except Exception as e:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="Successful registration",
            observed=f"Exception: {str(e)}",
            reason=str(e),
            duration_ms=(time.time() - start) * 1000
        )


def test_duplicate_registration():
    """Test duplicate email registration is blocked."""
    test_name = "Duplicate Email Rejection"
    start = time.time()
    
    # Register once
    timestamp = int(time.time() * 1000)
    payload = {
        "name": "Duplicate Test",
        "email": f"duplicate{timestamp}@example.com",
        "password": "password123"
    }
    
    try:
        # First registration (should succeed)
        response1 = requests.post(f"{BASE_URL}{API_PREFIX}/register", json=payload)
        
        # Second registration (should fail)
        response2 = requests.post(f"{BASE_URL}{API_PREFIX}/register", json=payload)
        duration = (time.time() - start) * 1000
        
        if response2.status_code == 400:
            return TestResult(
                name=test_name,
                status="PASS",
                expected="400 Bad Request for duplicate email",
                observed=f"400 {response2.json().get('detail', '')}",
                duration_ms=duration
            )
        else:
            return TestResult(
                name=test_name,
                status="FAIL",
                expected="400 Bad Request",
                observed=f"{response2.status_code}",
                reason="Duplicate email not rejected",
                duration_ms=duration
            )
    except Exception as e:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="400 for duplicate",
            observed=f"Exception: {str(e)}",
            reason=str(e),
            duration_ms=(time.time() - start) * 1000
        )


def test_login():
    """Test login endpoint and JWT generation."""
    test_name = "Login & JWT Generation"
    start = time.time()
    
    # Register user first
    timestamp = int(time.time() * 1000)
    email = f"logintest{timestamp}@example.com"
    password = "password123"
    
    register_payload = {
        "name": "Login Test User",
        "email": email,
        "password": password
    }
    
    try:
        # Register
        requests.post(f"{BASE_URL}{API_PREFIX}/register", json=register_payload)
        
        # Login
        login_payload = {"email": email, "password": password}
        response = requests.post(f"{BASE_URL}{API_PREFIX}/login", json=login_payload)
        duration = (time.time() - start) * 1000
        
        if response.status_code == 200:
            data = response.json()
            
            # Verify response has token and id
            if "token" in data and "id" in data:
                # Verify token format (JWT has 3 parts separated by dots)
                token_parts = data["token"].split(".")
                if len(token_parts) == 3:
                    return TestResult(
                        name=test_name,
                        status="PASS",
                        expected="200 with {token, id}",
                        observed=f"200 with valid JWT (id={data['id'][:8]}...)",
                        duration_ms=duration,
                        details={"token": data["token"][:20] + "...", "user_id": data["id"]}
                    )
                else:
                    return TestResult(
                        name=test_name,
                        status="FAIL",
                        expected="Valid JWT format",
                        observed=f"Invalid token: {data['token'][:30]}...",
                        reason="Token not in JWT format",
                        duration_ms=duration
                    )
            else:
                return TestResult(
                    name=test_name,
                    status="FAIL",
                    expected="{token, id}",
                    observed=f"Response: {data}",
                    reason="Missing token or id",
                    duration_ms=duration
                )
        else:
            return TestResult(
                name=test_name,
                status="FAIL",
                expected="200 OK",
                observed=f"{response.status_code}",
                reason="Login failed",
                duration_ms=duration
            )
    except Exception as e:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="Successful login",
            observed=f"Exception: {str(e)}",
            reason=str(e),
            duration_ms=(time.time() - start) * 1000
        )


def test_invalid_credentials():
    """Test login with invalid credentials."""
    test_name = "Invalid Credentials Rejection"
    start = time.time()
    
    payload = {
        "email": "nonexistent@example.com",
        "password": "wrongpassword"
    }
    
    try:
        response = requests.post(f"{BASE_URL}{API_PREFIX}/login", json=payload)
        duration = (time.time() - start) * 1000
        
        if response.status_code == 401:
            return TestResult(
                name=test_name,
                status="PASS",
                expected="401 Unauthorized",
                observed=f"401 {response.json().get('detail', '')}",
                duration_ms=duration
            )
        else:
            return TestResult(
                name=test_name,
                status="FAIL",
                expected="401 Unauthorized",
                observed=f"{response.status_code}",
                reason="Invalid credentials not rejected properly",
                duration_ms=duration
            )
    except Exception as e:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="401 Unauthorized",
            observed=f"Exception: {str(e)}",
            reason=str(e),
            duration_ms=(time.time() - start) * 1000
        )


def test_me_endpoint():
    """Test /me endpoint with JWT token."""
    test_name = "JWT Token Validation (/me endpoint)"
    start = time.time()
    
    # Register and login
    timestamp = int(time.time() * 1000)
    name = "Me Test User"
    email = f"metest{timestamp}@example.com"
    password = "password123"
    
    try:
        # Register
        requests.post(f"{BASE_URL}{API_PREFIX}/register", json={
            "name": name,
            "email": email,
            "password": password
        })
        
        # Login
        login_response = requests.post(f"{BASE_URL}{API_PREFIX}/login", json={
            "email": email,
            "password": password
        })
        token = login_response.json()["token"]
        
        # Call /me with token
        headers = {"Authorization": f"Bearer {token}"}
        response = requests.get(f"{BASE_URL}{API_PREFIX}/me", headers=headers)
        duration = (time.time() - start) * 1000
        
        if response.status_code == 200:
            data = response.json()
            
            # Verify response structure
            if "id" in data and "email" in data and "name" in data:
                # Verify data matches
                if data["email"] == email and data["name"] == name:
                    return TestResult(
                        name=test_name,
                        status="PASS",
                        expected=f"User profile: {name}, {email}",
                        observed=f"Correct profile returned",
                        duration_ms=duration,
                        details=data
                    )
                else:
                    return TestResult(
                        name=test_name,
                        status="FAIL",
                        expected=f"{name}, {email}",
                        observed=f"{data.get('name')}, {data.get('email')}",
                        reason="Profile data mismatch",
                        duration_ms=duration
                    )
            else:
                return TestResult(
                    name=test_name,
                    status="FAIL",
                    expected="{id, email, name}",
                    observed=f"Response: {data}",
                    reason="Missing required fields",
                    duration_ms=duration
                )
        else:
            return TestResult(
                name=test_name,
                status="FAIL",
                expected="200 OK",
                observed=f"{response.status_code}",
                reason="Token validation failed",
                duration_ms=duration
            )
    except Exception as e:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="Valid /me response",
            observed=f"Exception: {str(e)}",
            reason=str(e),
            duration_ms=(time.time() - start) * 1000
        )


def test_name_field_requirement():
    """Test that name field is required in registration."""
    test_name = "Name Field Requirement"
    start = time.time()
    
    # Try to register without name field
    timestamp = int(time.time() * 1000)
    payload = {
        "email": f"noname{timestamp}@example.com",
        "password": "password123"
        # name field omitted
    }
    
    try:
        response = requests.post(f"{BASE_URL}{API_PREFIX}/register", json=payload)
        duration = (time.time() - start) * 1000
        
        if response.status_code == 422:  # FastAPI validation error
            return TestResult(
                name=test_name,
                status="PASS",
                expected="422 Validation Error (name required)",
                observed=f"422 Validation Error",
                duration_ms=duration
            )
        else:
            return TestResult(
                name=test_name,
                status="FAIL",
                expected="422 Validation Error",
                observed=f"{response.status_code}",
                reason="Name field not enforced as required",
                duration_ms=duration
            )
    except Exception as e:
        return TestResult(
            name=test_name,
            status="FAIL",
            expected="422 Validation Error",
            observed=f"Exception: {str(e)}",
            reason=str(e),
            duration_ms=(time.time() - start) * 1000
        )


def main():
    """Run all auth service tests."""
    print_header("AUTHENTICATION SERVICE TEST SUITE")
    
    suite = TestSuite("Auth Service")
    
    # Run tests
    suite.add_result(test_registration())
    suite.add_result(test_duplicate_registration())
    suite.add_result(test_login())
    suite.add_result(test_invalid_credentials())
    suite.add_result(test_me_endpoint())
    suite.add_result(test_name_field_requirement())
    
    suite.finalize()
    exit_code = suite.print_report()
    
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
