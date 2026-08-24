import time
import asyncio
import os
import shutil
import glob
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from npci.models.schemas import InferenceRequest, InsightResponse, InsightPredictionItem
from npci.core.security import require_api_key
from npci.services.insight_service import generate_insight
from npci.core.config import settings
from npci.services.batch_processor import run_batch_pipeline

router = APIRouter()

import logging
from logging.handlers import RotatingFileHandler

log_file_path = "npci_app.log"
logger = logging.getLogger("npci_api")
logger.setLevel(logging.INFO)
if not logger.handlers:
    handler = RotatingFileHandler(log_file_path, maxBytes=5000000, backupCount=2)
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)


@router.get("/health", tags=["Health"])
async def health():
    return {
        "status": "ok",
        "model_type": "claude_anthropic",
        "anthropic_model": settings.ANTHROPIC_MODEL,
        "version": "1.0.0",
    }



@router.post("/start-daily-analysis", tags=["ETL"], dependencies=[Depends(require_api_key)])
async def start_daily_analysis(background_tasks: BackgroundTasks):
    """
    Triggers the production daily ETL pipeline to fetch ALL day-1 detractors (NPS <= 6)
    from NPCI BHIM survey data (e.g. App Performance, Transactions),
    processes them through the AI pipeline, and saves results into both AI_Analyzed and voc_alerts.
    """
    background_tasks.add_task(run_batch_pipeline)
    return {
        "status": "success",
        "message": "Production NPCI BHIM daily detractor analysis started in background. Processing all day-1 detractors into AI_Analyzed and voc_alerts."
    }

@router.post("/clear-cache", tags=["Admin"], dependencies=[Depends(require_api_key)])
async def clear_cache():
    """
    Clears the local JSON inference cache and all Python compiled caches (__pycache__).
    Use this to force the AI to re-evaluate comments after changing business rules.
    """
    messages = []
    
    # 1. Clear JSON inference cache
    from npci.services.insight_service import CACHE_FILE as cache_file
    if os.path.exists(cache_file):
        try:
            os.remove(cache_file)
            messages.append(f"Successfully deleted {cache_file}.")
        except Exception as e:
            messages.append(f"Failed to delete {cache_file}: {e}")
    else:
        messages.append(f"{cache_file} was not found (already cleared).")
        
    # 2. Clear __pycache__ directories
    pycache_dirs = glob.glob("app/**/__pycache__", recursive=True)
    deleted_pycache_count = 0
    for pycache in pycache_dirs:
        try:
            shutil.rmtree(pycache)
            deleted_pycache_count += 1
        except Exception:
            pass
            
    if deleted_pycache_count > 0:
        messages.append(f"Successfully deleted {deleted_pycache_count} __pycache__ directories.")
    else:
        messages.append("No __pycache__ directories found to delete.")
        
    return {
        "status": "success",
        "message": "Cache clear operation completed.",
        "details": messages
    }

@router.get("/logs", tags=["Admin"], dependencies=[Depends(require_api_key)])
async def get_logs(lines: int = 1000):
    """
    Fetch the latest logs for npci.
    """
    if os.path.exists(log_file_path):
        with open(log_file_path, "r", encoding="utf-8") as f:
            log_lines = f.readlines()
            return {"logs": "".join(log_lines[-lines:])}
    return {"logs": "No logs found."}
