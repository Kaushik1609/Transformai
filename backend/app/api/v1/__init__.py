"""
TransformIQ Backend — API v1 Router

All Phase 1+ endpoints are registered here.
Phase 2 adds: projects, sources, configurations, transformations, outputs.
"""
from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.admin import router as admin_router
from app.api.v1.projects import router as projects_router
from app.api.v1.sources import project_sources_router, sources_router
from app.api.v1.configurations import project_configs_router, configs_router
from app.api.v1.transformations import (
    transformations_router,
    outputs_router,
    project_transformations_router,
)
from app.api.v1.content_intelligence import router as content_intelligence_router

router = APIRouter()

# ---------------------------------------------------------------------------
# Auth (Phase 11F — L1 Perimeter & Identity)
# ---------------------------------------------------------------------------
router.include_router(auth_router)
router.include_router(admin_router)

# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
router.include_router(projects_router, prefix="/projects")

# ---------------------------------------------------------------------------
# Sources (nested under projects + standalone)
# ---------------------------------------------------------------------------
router.include_router(project_sources_router, prefix="/projects")
router.include_router(sources_router, prefix="/sources")
router.include_router(content_intelligence_router)

# ---------------------------------------------------------------------------
# Configurations (nested under projects + standalone)
# ---------------------------------------------------------------------------
router.include_router(project_configs_router, prefix="/projects")
router.include_router(configs_router, prefix="/configurations")

# ---------------------------------------------------------------------------
# Transformations + Outputs
# ---------------------------------------------------------------------------
router.include_router(project_transformations_router, prefix="/projects")
router.include_router(transformations_router, prefix="/transformations")
router.include_router(outputs_router, prefix="/outputs")
