from fastapi import APIRouter

from app.routes import (
    agents_router,
    assets_router,
    bootstrap_demo,
    demo_router,
    feishu_integration_router,
    providers_router,
    sessions_runs_router,
)

router = APIRouter()
router.include_router(providers_router)
router.include_router(assets_router)
router.include_router(agents_router)
router.include_router(sessions_runs_router)
router.include_router(feishu_integration_router)
router.include_router(demo_router)

__all__ = ["bootstrap_demo", "router"]
