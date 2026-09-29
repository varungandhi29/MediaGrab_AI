import time
import hashlib
from typing import Optional
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr, Field

router = APIRouter(prefix="/api/auth", tags=["auth"])

class LoginRequest(BaseModel):
    email: str = Field(..., description="User email address")
    password: str = Field(..., min_length=4, description="User password")

class RegisterRequest(BaseModel):
    name: str = Field(..., min_length=2, description="Full name or username")
    email: str = Field(..., description="User email address")
    password: str = Field(..., min_length=4, description="User password")

class AuthResponse(BaseModel):
    success: bool
    token: str
    user: dict
    message: str

# In-memory user store for session auth
_USERS_DB = {
    "user@mediagrab.ai": {
        "id": "usr_demo123",
        "name": "MediaGrab User",
        "email": "user@mediagrab.ai",
        "password_hash": hashlib.sha256("password123".encode()).hexdigest(),
        "created_at": time.time(),
        "tier": "Pro Member"
    }
}

def _hash_pw(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def _make_token(email: str) -> str:
    ts = str(int(time.time()))
    return f"mgtok_{hashlib.md5((email + ts + 'secret_salt_2026').encode()).hexdigest()}"

@router.post("/login", response_model=AuthResponse)
async def login(payload: LoginRequest):
    email = payload.email.lower().strip()
    user = _USERS_DB.get(email)
    
    # Auto-allow demo logins or registered users
    if not user:
        # Create user profile on the fly for ease of onboarding
        user_id = f"usr_{hashlib.md5(email.encode()).hexdigest()[:8]}"
        name_part = email.split("@")[0].replace(".", " ").title()
        user = {
            "id": user_id,
            "name": name_part,
            "email": email,
            "password_hash": _hash_pw(payload.password),
            "created_at": time.time(),
            "tier": "Verified Member"
        }
        _USERS_DB[email] = user
    else:
        # Verify password if user exists
        if user["password_hash"] != _hash_pw(payload.password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password. Please check your credentials."
            )
    
    token = _make_token(email)
    return AuthResponse(
        success=True,
        token=token,
        user={
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "tier": user.get("tier", "Verified Member"),
        },
        message=f"Welcome back, {user['name']}!"
    )

@router.post("/register", response_model=AuthResponse)
async def register(payload: RegisterRequest):
    email = payload.email.lower().strip()
    name = payload.name.strip()
    
    if email in _USERS_DB:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="An account with this email already exists. Please sign in."
        )
    
    user_id = f"usr_{hashlib.md5(email.encode()).hexdigest()[:8]}"
    new_user = {
        "id": user_id,
        "name": name,
        "email": email,
        "password_hash": _hash_pw(payload.password),
        "created_at": time.time(),
        "tier": "Pro Member"
    }
    _USERS_DB[email] = new_user
    
    token = _make_token(email)
    return AuthResponse(
        success=True,
        token=token,
        user={
            "id": new_user["id"],
            "name": new_user["name"],
            "email": new_user["email"],
            "tier": new_user["tier"],
        },
        message=f"Account created successfully. Welcome to MediaGrab AI, {name}!"
    )

@router.get("/me")
async def get_current_user():
    return {
        "auth_enabled": True,
        "providers": ["email", "google", "github"],
        "status": "operational"
    }
