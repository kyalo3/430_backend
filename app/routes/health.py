from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.database import client

router = APIRouter(tags=["health"])


@router.get("/health/live")
async def live():
    return {"status": "ok"}


@router.get("/health/ready")
async def ready():
    try:
        await client.admin.command("ping")
        return {"status": "ready", "mongo": "ok"}
    except Exception:
        return JSONResponse(status_code=503, content={"status": "not_ready", "mongo": "error"})
