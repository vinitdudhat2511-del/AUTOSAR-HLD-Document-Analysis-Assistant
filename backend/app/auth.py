import hashlib
import hmac
import secrets
from typing import Optional, List
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.database import get_db, User

security = HTTPBearer()

def hash_password(password: str, salt: Optional[str] = None) -> str:
    """Hash password using PBKDF2 with SHA-256."""
    if not salt:
        salt = secrets.token_hex(16)
    hashed = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt.encode('utf-8'),
        iterations=100000
    ).hex()
    return f"{salt}:{hashed}"

def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify password against salt:hash."""
    try:
        salt, stored_hash = password_hash.split(":", 1)
        expected_hash = hashlib.pbkdf2_hmac(
            'sha256',
            plain_password.encode('utf-8'),
            salt.encode('utf-8'),
            iterations=100000
        ).hex()
        return hmac.compare_digest(stored_hash, expected_hash)
    except Exception:
        return False

def generate_session_token() -> str:
    """Generate cryptographically secure session token."""
    return secrets.token_urlsafe(32)

from datetime import datetime

def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db)
) -> User:
    """Authenticate request using Bearer token with expiration check."""
    token = credentials.credentials
    user = db.query(User).filter(User.token == token).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user.token_expires_at and datetime.utcnow() > user.token_expires_at:
        user.token = None
        user.token_expires_at = None
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token has expired. Please log in again.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user

class RequireRole:
    """Role-based authorization dependency."""
    def __init__(self, allowed_roles: List[str]):
        self.allowed_roles = allowed_roles

    def __call__(self, current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in self.allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied. Required role in {self.allowed_roles}, your role is '{current_user.role}'"
            )
        return current_user

def check_project_access(user: User, project_id: str) -> bool:
    """Verify if user has permission to access the specified project."""
    if user.role == "admin":
        return True
    allowed = [p.strip() for p in (user.allowed_projects or "").split(",") if p.strip()]
    if "*" in allowed or project_id in allowed:
        return True
    return False
