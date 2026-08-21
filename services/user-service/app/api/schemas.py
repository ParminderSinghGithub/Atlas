"""
Pydantic schemas for request/response validation.

CRITICAL: These schemas define the API contract and must match frontend expectations.
"""
from typing import Union
from pydantic import BaseModel, Field, field_validator
import re

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_email_format(v: str) -> str:
    cleaned = v.strip().lower()
    if not EMAIL_REGEX.match(cleaned):
        raise ValueError("Invalid email address format")
    return cleaned


class RegisterRequest(BaseModel):
    """
    Registration request payload.
    
    CRITICAL: name field is REQUIRED.
    """
    name: str = Field(..., min_length=1, max_length=255, description="User's full name")
    email: str = Field(..., min_length=3, max_length=255, description="User's email address")
    password: str = Field(..., min_length=6, description="User's password (min 6 chars)")

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str) -> str:
        return validate_email_format(v)


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
    email: str = Field(..., min_length=3, max_length=255, description="User's email address")
    password: str = Field(..., description="User's password")

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str) -> str:
        return validate_email_format(v)


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


# ==========================================
# Password Reset & Account Recovery Schemas
# ==========================================

class ForgotPasswordRequest(BaseModel):
    """
    Request to trigger forgotten-password OTP / reset instructions.
    """
    email: str = Field(..., min_length=3, max_length=255, description="User's registered email address")

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str) -> str:
        return validate_email_format(v)


class ForgotPasswordResponse(BaseModel):
    """
    Response confirming password reset request received.
    """
    message: str = Field(..., description="Status message")
    success: bool = Field(True, description="Indicates request was processed")


class VerifyResetTokenRequest(BaseModel):
    """
    Request to verify whether an OTP / reset token is valid and unexpired.
    """
    email: str = Field(..., min_length=3, max_length=255, description="User's registered email address")
    token: str = Field(..., min_length=4, max_length=128, description="OTP or reset token")

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str) -> str:
        return validate_email_format(v)


class VerifyResetTokenResponse(BaseModel):
    """
    Response indicating whether the token/OTP is valid.
    """
    valid: bool = Field(..., description="True if token is valid and unexpired")
    message: str = Field(..., description="Validation detail message")


class ResetPasswordRequest(BaseModel):
    """
    Request to complete password reset with verified token.
    """
    email: str = Field(..., min_length=3, max_length=255, description="User's registered email address")
    token: str = Field(..., min_length=4, max_length=128, description="OTP or reset token")
    new_password: str = Field(..., min_length=6, description="New password (min 6 chars)")

    @field_validator("email")
    @classmethod
    def check_email(cls, v: str) -> str:
        return validate_email_format(v)


class ResetPasswordResponse(BaseModel):
    """
    Response confirming password update.
    """
    message: str = Field(..., description="Status message")
    success: bool = Field(True, description="Indicates password was updated successfully")
