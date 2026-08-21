"""
Password Reset Token model for secure forgotten-password / OTP recovery flow.
"""
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


class PasswordResetToken(Base):
    """
    Password reset token / OTP storage.
    
    Security design:
    - token_hash: SHA-256 hash of the plain token/OTP (plain token is never stored in DB)
    - expires_at: Short-lived expiration (default 15 minutes)
    - used: Single-use invalidation flag
    """
    __tablename__ = "password_resets"
    
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False
    )
    
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("Users.id", ondelete="CASCADE"),
        nullable=False,
        index=True
    )
    
    token_hash = Column(
        String,
        nullable=False,
        index=True
    )
    
    expires_at = Column(
        DateTime(timezone=True),
        nullable=False,
        index=True
    )
    
    used = Column(
        Boolean,
        default=False,
        nullable=False,
        index=True
    )
    
    createdAt = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    
    def __repr__(self):
        return f"<PasswordResetToken(id={self.id}, user_id={self.user_id}, used={self.used})>"
