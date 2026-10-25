from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.sessions import router as sessions_router
from app.core.config import settings
from app.storage.database import Base, engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.database_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    Base.metadata.create_all(bind=engine)

    try:
        yield
    finally:
        engine.dispose()


app = FastAPI(
    title=settings.app_name,
    description="开发者故障排查与工单协作平台",
    version="0.1.0",
    lifespan=lifespan,
)

app.include_router(sessions_router)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "devsupport-backend",
        "environment": settings.app_env,
    }