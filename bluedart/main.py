from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn
from bluedart.core.database import init_db_pool, close_db_pool, load_categories_from_db
from bluedart.services.anthropic_client import close_anthropic_client
from bluedart.api.routes import router
from bluedart.core.config import settings

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db_pool()
    await load_categories_from_db(force_refresh=True)
    
    print("=" * 80)
    print("API is running at: http://127.0.0.1:8000")
    print("API Docs: http://127.0.0.1:8000/docs")
    print("=" * 80)
    
    yield
    # Shutdown
    await close_db_pool()
    await close_anthropic_client()

from fastapi import FastAPI, Depends
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from fastapi.openapi.utils import get_openapi
from bluedart.core.security import require_docs_web_lock

app = FastAPI(
    title="CX Anthropic AI API",
    description="FastAPI-based AI system that analyzes customer comments (Voice of Customer - VOC) using Anthropic Claude for Blue Dart.",
    version="1.0.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.include_router(router)

@app.get("/openapi.json", include_in_schema=False, dependencies=[Depends(require_docs_web_lock)])
async def get_open_api_endpoint():
    return get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )

@app.get("/docs", include_in_schema=False, dependencies=[Depends(require_docs_web_lock)])
async def get_documentation():
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title=app.title + " - Swagger UI",
    )

@app.get("/redoc", include_in_schema=False, dependencies=[Depends(require_docs_web_lock)])
async def get_redoc_documentation():
    return get_redoc_html(
        openapi_url="/openapi.json",
        title=app.title + " - ReDoc",
    )

import os

if __name__ == "__main__":
    print("=" * 80)
    print("CX CLAUDE API - MAIN.PY")
    print(f"Anthropic Model: {settings.ANTHROPIC_MODEL}")
    print("API is running at: http://127.0.0.1:8000")
    
    print("=" * 80)
    should_reload = os.getenv("RELOAD", "false").lower() == "true"
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        reload=should_reload
    )
