"""Painting module routers, aggregated under /painting (nginx maps /api/)."""
from fastapi import APIRouter

from app.painting.routers import colormatch, guides, health, inventory, paints

router = APIRouter(prefix="/painting", tags=["painting"])
router.include_router(health.router)
router.include_router(guides.router)
router.include_router(paints.router)
router.include_router(inventory.router)
router.include_router(colormatch.router)
