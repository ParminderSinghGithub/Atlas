"""
Authentication routes.

CRITICAL: Routes must match Node.js service endpoints and behavior exactly.

Node.js routes:
- GET  /api/auth/ping        → { message: "User service alive" }
- POST /api/auth/signup      → { id, email }
- POST /api/auth/login       → { token }

Python routes (matching + enhanced):
- GET  /api/auth/ping        → { message: "User service alive" }
- POST /api/auth/register    → { id } (renamed from signup for clarity)
- POST /api/auth/signup      → { id } (alias for backward compatibility)
- POST /api/auth/login       → { token, id } (enhanced with id)
- GET  /api/auth/me          → { id, email, name } (NEW endpoint)
"""
from fastapi import APIRouter, HTTPException, Depends, Header
from sqlalchemy.orm import Session
from typing import Optional

from app.api.schemas import (
    RegisterRequest,
    RegisterResponse,
    LoginRequest,
    LoginResponse,
    MeResponse
)
from app.models import User
from app.core import get_db, hash_password, verify_password, create_jwt_token
from jose import jwt, JWTError
from app.core.config import settings

router = APIRouter(tags=["auth"])


@router.get("/ping")
def ping():
    """
    Health check endpoint.
    
    CRITICAL: Must match Node.js response exactly.
    """
    return {"message": "User service alive"}


@router.post("/register", response_model=RegisterResponse, status_code=201)
def register(
    request: RegisterRequest,
    db: Session = Depends(get_db)
):
    """
    Register a new user.
    
    CRITICAL Contract:
    - Request: { name, email, password }
    - Response: { id }
    - Status: 201 Created
    
    Enhancements vs Node.js:
    - Adds name field (required)
    - Returns id only (not email) for security
    """
    # Check if user already exists
    existing_user = db.query(User).filter(User.email == request.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Hash password
    hashed_password = hash_password(request.password)
    
    # Create user
    user = User(
        name=request.name,
        email=request.email,
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
    """
    Alias for /register endpoint for backward compatibility.
    
    Node.js service uses /signup, but /register is more idiomatic.
    This ensures both work.
    """
    return register(request, db)


@router.post("/login", response_model=LoginResponse)
def login(
    request: LoginRequest,
    db: Session = Depends(get_db)
):
    """
    Authenticate user and return JWT token.
    
    CRITICAL Contract:
    - Request: { email, password }
    - Response: { token, id }
    - Status: 200 OK
    
    Enhancement vs Node.js:
    - Returns both token AND id (Node.js only returns token)
    - Frontend needs id, so this avoids extra /me call
    """
    # Find user
    user = db.query(User).filter(User.email == request.email).first()
    
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
    
    NEW ENDPOINT (not in Node.js service).
    
    Usage:
        GET /api/auth/me
        Header: Authorization: Bearer <token>
    
    Response: { id, email, name }
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
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    # Get user from database
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return MeResponse(
        id=str(user.id),
        email=user.email,
        name=user.name
    )
