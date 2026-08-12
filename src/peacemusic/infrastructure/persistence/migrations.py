"""Pure helpers shared by Alembic and deployment validation."""

from __future__ import annotations


def normalize_alembic_database_url(url: str) -> str:
    """Use the asyncpg SQLAlchemy dialect required by ``env.py``."""

    normalized = url.strip()
    if normalized.startswith("postgres://"):
        return "postgresql+asyncpg://" + normalized[len("postgres://") :]
    if normalized.startswith("postgresql://"):
        return "postgresql+asyncpg://" + normalized[len("postgresql://") :]
    if normalized.startswith("postgresql+asyncpg://"):
        return normalized
    raise ValueError("DATABASE_URL must use a PostgreSQL URL")
