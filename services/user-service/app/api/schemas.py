"""
Pydantic schemas for request/response validation.

CRITICAL: These schemas define the API contract and must match frontend expectations.
"""
from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    """
    Registration request payload.
    
    CRITICAL: name field is REQUIRED.
    """
    name: str = Field(..., min_length=1, max_length=255, description="User's full name")
    email: EmailStr = Field(..., description="User's email address")
    password: str = Field(..., min_length=6, description="User's password (min 6 chars)")


class RegisterResponse(BaseModel):
    """
    Registration response payload.
    
    CRITICAL: Must return user ID as UUID string.
    """
    id: str = Field(..., description="User UUID")


class LoginRequest(BaseModel):
    """
    Login request payload.
    
    CRITICAL: Must match Node.js service (email + password only).
    """
    email: EmailStr = Field(..., description="User's email address")
    password: str = Field(..., description="User's password")


class LoginResponse(BaseModel):
    """
    Login response payload.
    
    CRITICAL: Must return both token and id (matches Node.js + frontend expectation).
    """
    token: str = Field(..., description="JWT authentication token")
    id: str = Field(..., description="User UUID")


class MeResponse(BaseModel):
    """
    /me endpoint response payload.
    
    Returns user profile information.
    """
    id: str = Field(..., description="User UUID")
    email: str = Field(..., description="User's email address")
    name: str = Field(..., description="User's full name")
