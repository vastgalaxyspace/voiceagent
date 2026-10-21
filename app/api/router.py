from fastapi import APIRouter

from app.api.routes import admin, auth, conversations, health, knowledge, live, harness, memories, usage, users

router = APIRouter()
router.include_router(health.router)
router.include_router(live.router)
router.include_router(harness.router)
router.include_router(auth.router)
router.include_router(users.router)
router.include_router(conversations.router)
router.include_router(usage.router)
router.include_router(admin.router)
router.include_router(memories.router)
router.include_router(knowledge.router)
router.include_router(knowledge.admin_router)
