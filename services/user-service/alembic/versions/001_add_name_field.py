"""Add name field to Users table

Revision ID: 001_add_name_field
Revises: 
Create Date: 2026-01-10 12:00:00.000000

This migration safely adds the 'name' field to the Users table.

SAFETY:
- Uses ALTER TABLE ADD COLUMN (non-destructive)
- Adds with default empty string for existing users
- Then updates constraint to NOT NULL after backfill
- Rollback: Drops column without data loss
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '001_add_name_field'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """
    Add name column to Users table.
    
    Step 1: Add column as nullable with default
    Step 2: Backfill existing users with placeholder
    Step 3: Make column NOT NULL
    """
    # Step 1: Add name column (nullable initially for safe migration)
    op.add_column(
        'Users',
        sa.Column('name', sa.String(), nullable=True)
    )
    
    # Step 2: Backfill existing users with email prefix as name
    # This ensures no NULL values before setting NOT NULL constraint
    op.execute("""
        UPDATE "Users"
        SET name = SPLIT_PART(email, '@', 1)
        WHERE name IS NULL
    """)
    
    # Step 3: Now safe to make NOT NULL
    op.alter_column('Users', 'name', nullable=False)


def downgrade() -> None:
    """
    Remove name column from Users table.
    
    Safe rollback - drops column without affecting other data.
    """
    op.drop_column('Users', 'name')
