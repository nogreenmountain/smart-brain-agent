import fastapi
from fastapi.middleware.cors import CORSMiddleware

from agentops.common.middleware import (
    CacheControlMiddleware,
    ExceptionMiddleware,
    DefaultContentTypeMiddleware,
)
from agentops.api.routes import v1, v2, v3, v4


app = fastapi.FastAPI(
    docs_url=None,
    openapi_url=None,
    title="AgentOps API",
    description="AgentOps API for managing sessions, agents, and events",
)

# Middleware order matters. FastAPI wraps them so the *last added* is the
# outermost. We want ExceptionMiddleware on the OUTSIDE so that any
# HTTPException / 500 response it generates still passes through
# CORSMiddleware on the way out (otherwise CORS headers are missing and
# the browser fails the preflight/login response).
app.add_middleware(ExceptionMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(CacheControlMiddleware)
app.add_middleware(DefaultContentTypeMiddleware)

app.include_router(v1.router)
app.include_router(v2.router)
app.include_router(v3.router)
app.include_router(v4.router)


@app.get("/health")
async def health_check():
    return {"message": "Server Up"}