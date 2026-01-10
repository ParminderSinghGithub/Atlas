"""
User model for authentication.

CRITICAL: Table name and structure must match existing Node.js Sequelize model.
"""
from sqlalchemy import Column, String, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid

from app.core.database import Base


class User(Base):
    """
    User model.
    
    Table: Users (Sequelize default pluralization)
    
    Schema:
    - id: UUID primary key (matches Sequelize UUIDV4)
    - email: Unique email (matches Sequelize STRING + unique)
    - password: Bcrypt hashed password (matches Sequelize STRING)
    - name: User's full name (NEW FIELD for UX enhancement)
    - createdAt: Timestamp (matches Sequelize timestamps)
    - updatedAt: Timestamp (matches Sequelize timestamps)
    
    CRITICAL: Table name "Users" matches Sequelize default (capital U + plural)
    """
    __tablename__ = "Users"
    
    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        nullable=False
    )
    
    email = Column(
        String,
        unique=True,
        nullable=False,
        index=True
    )
    
    password = Column(
        String,
        nullable=False
    )
    
    name = Column(
        String,
        nullable=False  # Required for all new users
    )
    
    createdAt = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False
    )
    
    updatedAt = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False
    )
    
    def __repr__(self):
        return f"<User(id={self.id}, email={self.email}, name={self.name})>"
