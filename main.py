import os
from dotenv import load_dotenv

# Load the master .env BEFORE importing anything else
load_dotenv(override=True)

from fastapi import FastAPI
from contextlib import asynccontextmanager
import uvicorn

# BlueDart imports
from bluedart.api.routes import router as bluedart_router
from bluedart.core.database import init_db_pool as bd_init_db, close_db_pool as bd_close_db, load_categories_from_db as bd_load_cats
from bluedart.services.anthropic_client import close_anthropic_client as bd_close_llm

# L&T imports
from lt.api.routes import router as lt_router
from lt.core.database import init_db_pool as lt_init_db, close_db_pool as lt_close_db, load_categories_from_db as lt_load_cats
from lt.services.anthropic_client import close_anthropic_client as lt_close_llm

# NPCI imports
from npci.api.routes import router as npci_router
from npci.core.database import init_db_pool as npci_init_db, close_db_pool as npci_close_db, load_categories_from_db as npci_load_cats
from npci.services.anthropic_client import close_anthropic_client as npci_close_llm

# DMI imports
from dmi.api.routes import router as dmi_router
from dmi.core.database import init_db_pool as dmi_init_db, close_db_pool as dmi_close_db, load_categories_from_db as dmi_load_cats
from dmi.services.anthropic_client import close_anthropic_client as dmi_close_llm

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    # BlueDart init
    print("Initializing Blue Dart...")
    await bd_init_db()
    await bd_load_cats(force_refresh=True)
    
    # L&T init
    print("Initializing L&T...")
    await lt_init_db()
    await lt_load_cats(force_refresh=True)
    
    # NPCI init
    print("Initializing NPCI...")
    await npci_init_db()
    await npci_load_cats(force_refresh=True)
    
    # DMI init
    print("Initializing DMI...")
    await dmi_init_db()
    await dmi_load_cats(force_refresh=True)
    
    print("=" * 80)
    print("CENTRALIZED LIGHTSOUTS API STARTED")
    print("API is running at: http://127.0.0.1:8000")
    print("Swagger Docs: http://127.0.0.1:8000/docs")
    print("=" * 80)
    
    yield
    
    # --- SHUTDOWN ---
    await bd_close_db()
    try:
        await bd_close_llm()
    except Exception:
        pass

    await lt_close_db()
    try:
        await lt_close_llm()
    except Exception:
        pass

    await npci_close_db()
    try:
        await npci_close_llm()
    except Exception:
        pass

    await dmi_close_db()
    try:
        await dmi_close_llm()
    except Exception:
        pass


from fastapi import FastAPI, Depends
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from fastapi.openapi.utils import get_openapi
from dmi.core.security import require_docs_web_lock

app = FastAPI(
    title="Centralized Lightsouts API",
    description="Unified FastAPI system running Blue Dart, L&T, NPCI, and DMI AI analysis logic.",
    version="3.0.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.include_router(bluedart_router, prefix="/bluedart")
app.include_router(lt_router, prefix="/lt")
app.include_router(npci_router, prefix="/npci")
app.include_router(dmi_router, prefix="/dmi")

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

@app.get("/")
async def root():
    return {
        "message": "Welcome to the Centralized Lightsouts API",
        "docs_url": "/docs",
        "status": "online"
    }

if __name__ == "__main__":
    should_reload = os.getenv("RELOAD", "false").lower() == "true"
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        log_level="info",
        reload=should_reload
    )
