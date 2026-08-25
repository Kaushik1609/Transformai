"""
TransformIQ Backend — ORM Models Package

All eight core entity models are defined here and importable from this package.
Importing this module is sufficient to register all models with the declarative
base (required by Alembic autogenerate).
"""
from app.db.models.user import User
from app.db.models.project import Project
from app.db.models.source import Source
from app.db.models.source_chunk import SourceChunk
from app.db.models.generation_configuration import GenerationConfiguration
from app.db.models.transformation_job import TransformationJob
from app.db.models.output import Output
from app.db.models.verification_result import VerificationResult
from app.db.models.canonical_content import CanonicalContent
from app.db.models.content_analysis_trace import ContentAnalysisTrace

__all__ = [
    "User",
    "Project",
    "Source",
    "SourceChunk",
    "GenerationConfiguration",
    "TransformationJob",
    "Output",
    "VerificationResult",
    "CanonicalContent",
    "ContentAnalysisTrace",
]
