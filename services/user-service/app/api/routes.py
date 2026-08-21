"""
Authentication routes for Atlas user-service.

Endpoints:
- GET  /api/auth/ping                → Health check
- POST /api/auth/register            → Register new user ({name, email, password} → {id})
- POST /api/auth/signup              → Backward compatibility alias
- POST /api/auth/login               → Authenticate ({email, password} → {token, id})
- GET  /api/auth/me                  → Profile from Bearer JWT ({id, email, name})
- POST /api/auth/forgot-password     → Initiate password recovery / OTP
- POST /api/auth/verify-reset-token  → Validate reset token / OTP
- POST /api/auth/reset-password      → Complete password reset
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, HTTPException, Depends, Header
from sqlalchemy.orm import Session
from sqlalchemy.sql import func
from app.core.auth import jwt, JWTError

from app.api.schemas import (
    RegisterRequest,
    RegisterResponse,
    LoginRequest,
    LoginResponse,
    MeResponse,
    ForgotPasswordRequest,
    ForgotPasswordResponse,
    VerifyResetTokenRequest,
    VerifyResetTokenResponse,
    ResetPasswordRequest,
    ResetPasswordResponse,
)
from app.models import User, PasswordResetToken
from app.core import (
    get_db,
    hash_password,
    verify_password,
    create_jwt_token,
    generate_reset_token,
    hash_reset_token,
    verify_reset_token as verify_token_hash,
    send_password_reset_email,
)
from app.core.config import settings

router = APIRouter(tags=["auth"])


@router.get("/ping")
def ping():
    """Health check endpoint."""
    return {"message": "User service alive"}


@router.post("/register", response_model=RegisterResponse, status_code=201)
def register(
    request: RegisterRequest,
    db: Session = Depends(get_db)
):
    """
    Register a new user.
    """
    normalized_email = request.email.strip().lower()
    
    # Check if user already exists
    existing_user = db.query(User).filter(func.lower(User.email) == normalized_email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Hash password
    hashed_password = hash_password(request.password)
    
    # Create user
    user = User(
        name=request.name.strip(),
        email=normalized_email,
        password=hashed_password
    )
    
    db.add(user)
    
    try:
        db.commit()
        db.refresh(user)
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    
    return RegisterResponse(id=str(user.id))


@router.post("/signup", response_model=RegisterResponse, status_code=201)
def signup(
    request: RegisterRequest,
    db: Session = Depends(get_db)
):
    """Alias for /register endpoint for backward compatibility."""
    return register(request, db)


@router.post("/login", response_model=LoginResponse)
def login(
    request: LoginRequest,
    db: Session = Depends(get_db)
):
    """
    Authenticate user and return JWT token + User ID.
    """
    normalized_email = request.email.strip().lower()
    user = db.query(User).filter(func.lower(User.email) == normalized_email).first()
    
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Verify password
    if not verify_password(request.password, user.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Generate JWT token
    token = create_jwt_token(str(user.id))
    
    return LoginResponse(
        token=token,
        id=str(user.id)
    )


@router.get("/me", response_model=MeResponse)
def get_current_user(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    """
    Get current user profile from JWT token.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")
    
    # Extract token from "Bearer <token>"
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Invalid authentication scheme")
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid authorization header format")
    
    # Decode JWT token
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm]
        )
        user_id = payload.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid token payload")
        try:
            lookup_id = UUID(str(user_id))
        except Exception:
            lookup_id = user_id
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    # Get user from database
    user = db.query(User).filter(User.id == lookup_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return MeResponse(
        id=str(user.id),
        email=user.email,
        name=user.name
    )


# ==========================================
# Password Reset / Forgotten Password Routes
# ==========================================

@router.post("/forgot-password", response_model=ForgotPasswordResponse)
def forgot_password(
    request: ForgotPasswordRequest,
    db: Session = Depends(get_db)
):
    """
    Initiate forgotten-password recovery.
    
    Security:
    - Returns generic success message even if email is not found to prevent email enumeration.
    - Generates a short-lived, single-use token/OTP.
    - Stores SHA-256 hash of token in database.
    """
    normalized_email = request.email.strip().lower()
    user = db.query(User).filter(func.lower(User.email) == normalized_email).first()
    
    if user:
        # Invalidate any prior active tokens for this user
        db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.used.is_(False)
        ).update({"used": True})
        
        # Generate new reset token / OTP
        plain_token = generate_reset_token()
        token_hash = hash_reset_token(plain_token)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.reset_token_expiration_minutes)
        
        reset_entry = PasswordResetToken(
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
            used=False
        )
        db.add(reset_entry)
        db.commit()
        
        # Deliver via email service (SMTP or log fallback)
        send_password_reset_email(user.email, plain_token, user_name=user.name)
    
    return ForgotPasswordResponse(
        message="If this email is registered, password reset instructions have been sent.",
        success=True
    )


@router.post("/verify-reset-token", response_model=VerifyResetTokenResponse)
def verify_reset_token_endpoint(
    request: VerifyResetTokenRequest,
    db: Session = Depends(get_db)
):
    """
    Check if a reset token / OTP is valid and unexpired before presenting the reset form.
    """
    normalized_email = request.email.strip().lower()
    user = db.query(User).filter(func.lower(User.email) == normalized_email).first()
    
    if not user:
        return VerifyResetTokenResponse(valid=False, message="Invalid or expired reset token")
    
    now = datetime.now(timezone.utc)
    token_hash = hash_reset_token(request.token)
    
    active_token = db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.token_hash == token_hash,
        PasswordResetToken.used.is_(False),
        PasswordResetToken.expires_at > now
    ).first()
    
    if not active_token:
        return VerifyResetTokenResponse(valid=False, message="Invalid or expired reset token")
    
    return VerifyResetTokenResponse(valid=True, message="Reset token is valid")


@router.post("/reset-password", response_model=ResetPasswordResponse)
def reset_password_endpoint(
    request: ResetPasswordRequest,
    db: Session = Depends(get_db)
):
    """
    Complete password reset by updating the password using a valid reset token.
    """
    normalized_email = request.email.strip().lower()
    user = db.query(User).filter(func.lower(User.email) == normalized_email).first()
    
    if not user:
        raise HTTPException(status_code=400, detail="Invalid request or expired reset token")
    
    now = datetime.now(timezone.utc)
    token_hash = hash_reset_token(request.token)
    
    active_token = db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user.id,
        PasswordResetToken.token_hash == token_hash,
        PasswordResetToken.used.is_(False),
        PasswordResetToken.expires_at > now
    ).first()
    
    if not active_token:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    
    # Hash new password
    hashed_password = hash_password(request.new_password)
    
    # Update password and mark token as used
    user.password = hashed_password
    user.updatedAt = func.now()
    active_token.used = True
    
    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to update password")
    
    return ResetPasswordResponse(
        message="Password has been reset successfully. You can now login with your new password.",
        success=True
    )
