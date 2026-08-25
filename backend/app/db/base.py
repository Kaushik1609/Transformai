"""
TransformIQ Backend — SQLAlchemy Declarative Base

All ORM models inherit from Base declared here.
Import Base from this module (not from individual model files)
to avoid circular imports.
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base class for all TransformIQ ORM models."""
    pass
