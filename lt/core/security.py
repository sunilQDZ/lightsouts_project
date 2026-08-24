import secrets
import base64
from typing import Optional
from fastapi import HTTPException, status, Depends, Request
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from lt.core.config import settings

security_basic = HTTPBasic(auto_error=False)

def require_api_key(
    request: Request,
    credentials: Optional[HTTPBasicCredentials] = Depends(security_basic)
) -> str:
    expected_username = getattr(settings, "DOCS_USERNAME", "admin")
    expected_password = getattr(settings, "DOCS_PASSWORD", None) or getattr(settings, "API_TOKEN", "my_secret_123")
    
    query_key = request.query_params.get("api_key")
    header_key = request.headers.get("X-API-Key")
    if (header_key and header_key == expected_password) or (query_key and query_key == expected_password):
        return expected_password
        
    if credentials:
        user_ok = secrets.compare_digest(credentials.username, expected_username)
        pass_ok = secrets.compare_digest(credentials.password, expected_password)
        if user_ok and pass_ok:
            return expected_password
            
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized: Invalid or missing API key",
        headers={"WWW-Authenticate": "Basic"}
    )

def require_docs_web_lock(
    request: Request,
    credentials: Optional[HTTPBasicCredentials] = Depends(security_basic)
) -> bool:
    expected_username = getattr(settings, "DOCS_USERNAME", "admin")
    expected_password = getattr(settings, "DOCS_PASSWORD", None) or getattr(settings, "API_TOKEN", "my_secret_123")
    
    query_key = request.query_params.get("api_key")
    header_key = request.headers.get("X-API-Key")
    if (header_key and header_key == expected_password) or (query_key and query_key == expected_password):
        return True
        
    if credentials:
        user_ok = secrets.compare_digest(credentials.username, expected_username)
        pass_ok = secrets.compare_digest(credentials.password, expected_password)
        if user_ok and pass_ok:
            return True
            
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect username or password",
        headers={"WWW-Authenticate": "Basic"}
    )
