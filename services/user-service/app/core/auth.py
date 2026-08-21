"""
Authentication utilities for JWT token generation, password hashing, and secure reset token operations.

Maintains complete compatibility with Node.js jsonwebtoken and bcrypt, with built-in standard-library
HMAC-SHA256 and PBKDF2 fallbacks.
"""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import base64
import json
import secrets
from typing import Dict, Any, Optional

from app.core.config import settings

# ----------------------------------------------------------------------
# Password Hashing (bcrypt with fallback)
# ----------------------------------------------------------------------
try:
    import bcrypt

    def hash_password(password: str) -> str:
        """Hash password using bcrypt."""
        hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt(rounds=settings.bcrypt_rounds))
        return hashed.decode('utf-8')

    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Verify plain password against hashed password."""
        try:
            if hashed_password.startswith("$2a$") or hashed_password.startswith("$2b$") or hashed_password.startswith("$2y$"):
                return bcrypt.checkpw(plain_password.encode('utf-8'), hashed_password.encode('utf-8'))
            elif hashed_password.startswith("$pbkdf2$"):
                parts = hashed_password.split("$")
                salt, h = parts[2], parts[3]
                computed = hashlib.pbkdf2_hmac('sha256', plain_password.encode('utf-8'), salt.encode('utf-8'), 100000).hex()
                return secrets.compare_digest(computed, h)
            return False
        except Exception:
            return False

except ImportError:
    def hash_password(password: str) -> str:
        salt = secrets.token_hex(16)
        h = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), 100000).hex()
        return f"$pbkdf2${salt}${h}"

    def verify_password(plain_password: str, hashed_password: str) -> bool:
        try:
            if hashed_password.startswith("$pbkdf2$"):
                parts = hashed_password.split("$")
                salt, h = parts[2], parts[3]
                computed = hashlib.pbkdf2_hmac('sha256', plain_password.encode('utf-8'), salt.encode('utf-8'), 100000).hex()
                return secrets.compare_digest(computed, h)
            return False
        except Exception:
            return False


# ----------------------------------------------------------------------
# JWT Tokens (python-jose with fallback)
# ----------------------------------------------------------------------
try:
    from jose import jwt, JWTError
except ImportError:
    class JWTError(Exception):
        pass

    class _JWT:
        @staticmethod
        def encode(payload: Dict[str, Any], key: str, algorithm: str = "HS256") -> str:
            # Transform exp if datetime
            clean_payload = {}
            for k, v in payload.items():
                if isinstance(v, datetime):
                    clean_payload[k] = int(v.timestamp())
                else:
                    clean_payload[k] = v

            header = {"typ": "JWT", "alg": algorithm}
            seg1 = base64.urlsafe_b64encode(json.dumps(header).encode('utf-8')).decode('utf-8').rstrip('=')
            seg2 = base64.urlsafe_b64encode(json.dumps(clean_payload, default=str).encode('utf-8')).decode('utf-8').rstrip('=')
            signing_input = f"{seg1}.{seg2}".encode('utf-8')
            signature = hmac.new(key.encode('utf-8'), signing_input, hashlib.sha256).digest()
            seg3 = base64.urlsafe_b64encode(signature).decode('utf-8').rstrip('=')
            return f"{seg1}.{seg2}.{seg3}"

        @staticmethod
        def decode(token: str, key: str, algorithms: Optional[list] = None) -> Dict[str, Any]:
            try:
                parts = token.split(".")
                if len(parts) != 3:
                    raise JWTError("Invalid token segments")
                seg1, seg2, seg3 = parts
                signing_input = f"{seg1}.{seg2}".encode('utf-8')
                signature = hmac.new(key.encode('utf-8'), signing_input, hashlib.sha256).digest()
                expected_seg3 = base64.urlsafe_b64encode(signature).decode('utf-8').rstrip('=')
                if not secrets.compare_digest(seg3, expected_seg3):
                    raise JWTError("Signature verification failed")
                padding = '=' * (4 - len(seg2) % 4)
                payload = json.loads(base64.urlsafe_b64decode(seg2 + padding).decode('utf-8'))
                exp = payload.get("exp")
                if exp and datetime.now(timezone.utc).timestamp() > exp:
                    raise JWTError("Token expired")
                return payload
            except Exception as e:
                raise JWTError(str(e))

    jwt = _JWT()


def create_jwt_token(user_id: str) -> str:
    """
    Create JWT token for user authentication.
    """
    expire = datetime.now(timezone.utc) + timedelta(hours=settings.jwt_expiration_hours)
    
    payload = {
        "id": user_id,
        "exp": expire
    }
    
    token = jwt.encode(
        payload,
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm
    )
    
    return token


# ----------------------------------------------------------------------
# Password Reset Tokens & OTPs
# ----------------------------------------------------------------------
def generate_reset_token() -> str:
    """
    Generate a cryptographically secure 6-digit numeric OTP.
    """
    otp_int = secrets.randbelow(1_000_000)
    return f"{otp_int:06d}"


def hash_reset_token(plain_token: str) -> str:
    """
    Hash a reset token using SHA-256 before database storage.
    """
    return hashlib.sha256(plain_token.strip().encode('utf-8')).hexdigest()


def verify_reset_token(plain_token: str, token_hash: str) -> bool:
    """
    Verify a plain reset token against its stored SHA-256 hash.
    """
    computed = hash_reset_token(plain_token)
    return secrets.compare_digest(computed, token_hash)
