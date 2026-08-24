import time
from typing import List
import aiomysql
from npci.core.config import settings

DB_CONFIG = {
    "host": settings.DB_HOST,
    "port": settings.DB_PORT,
    "user": settings.DB_USER,
    "password": settings.DB_PASS,
    "db": settings.DB_NAME,
    "charset": "utf8mb4",
    "cursorclass": aiomysql.DictCursor,
    "autocommit": True,
    "pool_recycle": 1800,
    "connect_timeout": 10,
}

_pool = None

async def init_db_pool():
    global _pool
    if _pool is None:
        _pool = await aiomysql.create_pool(**DB_CONFIG, minsize=1, maxsize=10)

async def close_db_pool():
    global _pool
    if _pool is not None:
        _pool.close()
        await _pool.wait_closed()
        _pool = None

async def load_categories_from_db(force_refresh: bool = False) -> List[str]:
    # Hardcoded categories for NPCI
    return [
        "Transaction Failure",
        "Money Not Credited",
        "App Performance",
        "Fraud",
        "Account Blocked",
        "Login Issues",
        "Customer Support",
        "General Enquiry",
        "Profile Issue",
        "Account Linking",
        "App Experience",
        "General Feedback",
        "Generic"
    ]
