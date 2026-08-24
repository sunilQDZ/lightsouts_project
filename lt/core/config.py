import os
from dotenv import load_dotenv

load_dotenv(override=True)

class Config:
    API_TOKEN = os.getenv("LT_API_TOKEN", os.getenv("API_TOKEN", "my_secret_123"))
    DOCS_USERNAME = os.getenv("DOCS_USERNAME", "admin")
    DOCS_PASSWORD = os.getenv("DOCS_PASSWORD", os.getenv("LT_API_TOKEN", "my_secret_123"))
    
    ANTHROPIC_API_KEY = os.getenv("LT_ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL = os.getenv("LT_ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    
    DB_HOST = os.getenv("LT_DB_HOST", "188.241.187.49")
    DB_PORT = int(os.getenv("LT_DB_PORT", 3306))
    DB_USER = os.getenv("LT_DB_USER", "surveycx_demousers")
    DB_PASS = os.getenv("LT_DB_PASS", "4lipmrdfjvff73mo")
    DB_NAME = os.getenv("LT_DB_NAME", "surveycx_demo")
    
    CATEGORY_CACHE_TTL_SECONDS = int(os.getenv("CATEGORY_CACHE_TTL_SECONDS", "30"))

settings = Config()
