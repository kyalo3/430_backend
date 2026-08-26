"""Auth endpoints: login (cookie + optional bearer), refresh, logout."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field

from app.core.audit import write_audit
from app.core.config import get_settings
from app.core.rate_limit import client_key, limiter
from app.core.rbac import PUBLIC_ROLES
from app.core.security import (
    clear_auth_cookies,
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    hash_password,
    password_is_strong,
    set_auth_cookies,
    verify_password,
)
from app.database import refresh_token_collection, user_collection
from app.models.user import UserCreate, create_user, get_user_by_email, get_user_by_username
from app.routes.auth import authenticate_user

router = APIRouter(prefix="/auth", tags=["auth"])
compat_router = APIRouter(tags=["auth-compat"])


class RegisterBody(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    email: EmailStr
    password: str
    role: str


class LegacyRegisterBody(BaseModel):
    user: RegisterBody
    admin_code: str | None = None


@router.post("/register", status_code=status.HTTP_201_CREATED)
@compat_router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(request: Request):
    settings = get_settings()
    limiter.check(client_key(request, "register"), settings.rate_limit_auth_per_minute)
    raw = await request.json()
    if "user" in raw:
        nested = LegacyRegisterBody(**raw)
        body = nested.user
    else:
        body = RegisterBody(**raw)
    if body.role not in PUBLIC_ROLES:
        raise HTTPException(status_code=403, detail="Public registration is limited to donor, recipient, or volunteer")
    if not password_is_strong(body.password):
        raise HTTPException(
            status_code=400,
            detail="Password must be at least 10 characters and include 3 of: lower, upper, digit, symbol",
        )
    if await get_user_by_username(body.username) or await get_user_by_email(body.email):
        raise HTTPException(status_code=400, detail="Unable to register with the provided credentials")
    user = UserCreate(username=body.username, email=body.email, password=body.password, role=body.role)
    created = await create_user(user)
    await write_audit(
        actor_id=created.get("id"),
        actor_role=body.role,
        action="user.registered",
        entity_type="user",
        entity_id=created.get("id"),
    )
    return {"id": created.get("id"), "username": created.get("username"), "email": created.get("email"), "role": created.get("role")}


async def _issue_session(response: Response, user: dict) -> dict:
    access = create_access_token(subject=user["username"], role=user["role"])
    refresh_jti = secrets.token_hex(16)
    refresh = create_refresh_token(subject=user["username"], role=user["role"], jti=refresh_jti)
    csrf = secrets.token_urlsafe(32)
    settings = get_settings()
    await refresh_token_collection.insert_one(
        {
            "jti": refresh_jti,
            "username": user["username"],
            "revoked": False,
            "expires_at": datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days),
        }
    )
    set_auth_cookies(response, access, refresh, csrf)
    return {
        "token_type": "bearer",
        # access_token returned for API clients/tests; SPAs should rely on HttpOnly cookie
        "access_token": access,
        "csrf_token": csrf,
        "user": {"id": user.get("id"), "username": user.get("username"), "role": user.get("role"), "email": user.get("email")},
    }


@router.post("/token")
@compat_router.post("/token")
async def login(response: Response, request: Request, form_data: OAuth2PasswordRequestForm = Depends()):
    settings = get_settings()
    limiter.check(client_key(request, "auth"), settings.rate_limit_auth_per_minute)
    user = await authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=400, detail="Incorrect username or password")
    await write_audit(
        actor_id=str(user.get("id")),
        actor_role=user.get("role"),
        action="user.login",
        entity_type="user",
        entity_id=str(user.get("id")),
    )
    return await _issue_session(response, user)


@router.post("/logout")
@compat_router.post("/logout")
@compat_router.post("/auth/logout")
async def logout(response: Response, request: Request, current_user: dict = Depends(get_current_user)):
    refresh = request.cookies.get("ss_refresh")
    if refresh:
        try:
            payload = decode_token(refresh)
            jti = payload.get("jti")
            if jti:
                await refresh_token_collection.update_one({"jti": jti}, {"$set": {"revoked": True}})
        except Exception:
            pass
    clear_auth_cookies(response)
    await write_audit(
        actor_id=str(current_user.get("id")),
        actor_role=current_user.get("role"),
        action="user.logout",
        entity_type="user",
        entity_id=str(current_user.get("id")),
    )
    return {"message": "Logged out"}


@router.post("/refresh")
@compat_router.post("/refresh")
@compat_router.post("/auth/refresh")
async def refresh_session(response: Response, request: Request):
    token = request.cookies.get("ss_refresh")
    if not token:
        raise HTTPException(401, "Missing refresh session")
    try:
        payload = decode_token(token)
        if payload.get("type") != "refresh":
            raise HTTPException(401, "Invalid refresh token")
        jti = payload.get("jti")
        stored = await refresh_token_collection.find_one({"jti": jti, "revoked": False})
        if not stored:
            raise HTTPException(401, "Refresh token revoked")
        # rotate
        await refresh_token_collection.update_one({"jti": jti}, {"$set": {"revoked": True}})
        user = await get_user_by_username(payload.get("sub"))
        if not user:
            raise HTTPException(401, "User not found")
        return await _issue_session(response, user)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(401, "Invalid refresh token") from exc


@router.get("/me")
async def auth_me(current_user: dict = Depends(get_current_user)):
    return {
        "id": current_user.get("id"),
        "username": current_user.get("username"),
        "email": current_user.get("email"),
        "role": current_user.get("role"),
        "status": current_user.get("status", "active"),
    }
