"""
Authentication utilities for JWT token generation and password hashing.

CRITICAL: JWT tokens must be compatible with Node.js jsonwebtoken library.
"""
from datetime import datetime, timedelta, timezone
from jose import jwt
import bcrypt

from app.core.config import settings


def hash_password(password: str) -> str:
    """
    Hash password using bcrypt.
    
    Args:
        password: Plain text password
    
    Returns:
        Hashed password string
    
    Note: Compatible with Node.js bcrypt.hash(password, 10)
    """
    # Convert password to bytes and hash with 10 rounds (matching Node.js default)
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=10))
    return hashed.decode('utf-8')


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verify password against hash.
    
    Args:
        plain_password: Plain text password
        hashed_password: Bcrypt hash
    
    Returns:
        True if password matches hash
    
    Note: Compatible with Node.js bcrypt.compare(password, hash)
    """
    return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))


def create_jwt_token(user_id: str) -> str:
    """
    Create JWT token for user authentication.
    
    Args:
        user_id: User UUID
    
    Returns:
        JWT token string
    
    CRITICAL: Token format must match Node.js jsonwebtoken library:
    - Algorithm: HS256
    - Payload: { "id": user_id, "exp": timestamp }
    - Secret: JWT_SECRET environment variable
    
    Node.js equivalent:
        jwt.sign({ id: user.id }, process.env.JWT_SECRET, { expiresIn: "1h" })
    """
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expiration_hours)
    
    # CRITICAL: Payload must match Node.js structure
    payload = {
        "id": user_id,  # Node.js uses "id" not "sub"
        "exp": expire
    }
    
    token = jwt.encode(
        payload,
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm
    )
    
    return token
