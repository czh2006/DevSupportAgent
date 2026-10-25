from fastapi import FastAPI

app = FastAPI(
    title="DevSupport Agent",
    description="开发者故障排查与工单协作平台",
    version="0.1.0",
)


@app.get("/health")
def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "devsupport-backend",
    }