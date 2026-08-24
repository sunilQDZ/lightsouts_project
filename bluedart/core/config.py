import os
from dotenv import load_dotenv

load_dotenv(override=True)

class Config:
    API_TOKEN = os.getenv("BLUEDART_API_TOKEN", os.getenv("API_TOKEN", "my_secret_123"))
    DOCS_USERNAME = os.getenv("DOCS_USERNAME", "admin")
    DOCS_PASSWORD = os.getenv("DOCS_PASSWORD", os.getenv("BLUEDART_API_TOKEN", "my_secret_123"))
    
    ANTHROPIC_API_KEY = os.getenv("BLUEDART_ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL = os.getenv("BLUEDART_ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    
    DB_HOST = os.getenv("BLUEDART_SURVEY_DB_HOST", "localhost")
    DB_PORT = int(os.getenv("BLUEDART_SURVEY_DB_PORT", 3306))
    DB_USER = os.getenv("BLUEDART_SURVEY_DB_USER", "")
    DB_PASS = os.getenv("BLUEDART_SURVEY_DB_PASSWORD", "")
    DB_NAME = os.getenv("BLUEDART_SURVEY_DB_NAME", "")
    
    BLUEDART_USERNAME = os.getenv("BLUEDART_USERNAME", "")
    BLUEDART_PASSWORD = os.getenv("BLUEDART_PASSWORD", "")
    
    BATCH_LIMIT = int(os.getenv("BATCH_LIMIT", 20))
    
    CATEGORY_CACHE_TTL_SECONDS = int(os.getenv("CATEGORY_CACHE_TTL_SECONDS", "30"))

settings = Config()
