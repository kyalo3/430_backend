"""Authentication helpers: JWT access/refresh, cookies, CSRF, password policy."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import get_settings
from app.models.user import get_user_by_username

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token", auto_error=False)

ACCESS_COOKIE = "ss_access"
REFRESH_COOKIE = "ss_refresh"
CSRF_COOKIE = "ss_csrf"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def password_is_strong(password: str) -> bool:
    if len(password) < 10:
        return False
    classes = sum(
        [
            any(c.islower() for c in password),
            any(c.isupper() for c in password),
            any(c.isdigit() for c in password),
            any(c in "!@#$%^&*()-_=+[]{};:,.?/" for c in password),
        ]
    )
    return classes >= 3


def _encode(data: dict, minutes: Optional[int] = None, days: Optional[int] = None) -> str:
    settings = get_settings()
    payload = data.copy()
    now = datetime.now(timezone.utc)
    if days is not None:
        expire = now + timedelta(days=days)
    else:
        expire = now + timedelta(minutes=minutes or settings.access_token_expire_minutes)
    payload.update({"exp": expire, "iat": now})
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def create_access_token(*, subject: str, role: str, jti: Optional[str] = None) -> str:
    return _encode(
        {"sub": subject, "role": role, "type": "access", "jti": jti or secrets.token_hex(8)},
        minutes=get_settings().access_token_expire_minutes,
    )


def create_refresh_token(*, subject: str, role: str, jti: Optional[str] = None) -> str:
    return _encode(
        {"sub": subject, "role": role, "type": "refresh", "jti": jti or secrets.token_hex(16)},
        days=get_settings().refresh_token_expire_days,
    )


def decode_token(token: str) -> dict:
    settings = get_settings()
    return jwt.decode(token, settings.secret_key, algorithms=["HS256"])


def set_auth_cookies(response: Response, access: str, refresh: str, csrf: str) -> None:
    settings = get_settings()
    common = {
        "httponly": True,
        "secure": settings.cookie_secure or settings.is_production,
        "samesite": settings.cookie_samesite,
        "path": "/",
    }
    if settings.cookie_domain:
        common["domain"] = settings.cookie_domain
    response.set_cookie(ACCESS_COOKIE, access, max_age=settings.access_token_expire_minutes * 60, **common)
    response.set_cookie(
        REFRESH_COOKIE,
        refresh,
        max_age=settings.refresh_token_expire_days * 86400,
        **common,
    )
    # CSRF cookie is readable by JS for double-submit
    response.set_cookie(
        CSRF_COOKIE,
        csrf,
        max_age=settings.refresh_token_expire_days * 86400,
        httponly=False,
        secure=common["secure"],
        samesite=common["samesite"],
        path="/",
        **({"domain": settings.cookie_domain} if settings.cookie_domain else {}),
    )


def clear_auth_cookies(response: Response) -> None:
    for name in (ACCESS_COOKIE, REFRESH_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/")


def _extract_bearer(request: Request, header_token: Optional[str]) -> Optional[str]:
    if header_token:
        return header_token
    return request.cookies.get(ACCESS_COOKIE)


def enforce_csrf(request: Request) -> None:
    """Require CSRF header matching cookie for cookie-authenticated mutating requests."""
    if request.method in {"GET", "HEAD", "OPTIONS", "TRACE"}:
        return
    if request.headers.get("Authorization"):
        return  # Bearer clients (tests/API) skip cookie CSRF
    csrf_cookie = request.cookies.get(CSRF_COOKIE)
    csrf_header = request.headers.get(get_settings().csrf_header_name)
    if not csrf_cookie or not csrf_header or csrf_cookie != csrf_header:
        raise HTTPException(status_code=403, detail="CSRF validation failed")


async def get_current_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
) -> dict[str, Any]:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    raw = _extract_bearer(request, token)
    if not raw:
        raise credentials_exception
    if request.cookies.get(ACCESS_COOKIE) and not request.headers.get("Authorization"):
        enforce_csrf(request)
    try:
        payload = decode_token(raw)
        if payload.get("type") != "access":
            raise credentials_exception
        username = payload.get("sub")
        if not username:
            raise credentials_exception
    except JWTError as exc:
        raise credentials_exception from exc
    user = await get_user_by_username(username)
    if user is None:
        raise credentials_exception
    if user.get("status") in {"anonymised", "pending_deletion"}:
        raise credentials_exception
    if user.get("status") == "suspended":
        raise HTTPException(status_code=403, detail="Account suspended")
    user.pop("password", None)
    return user


async def get_optional_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
) -> Optional[dict[str, Any]]:
    try:
        return await get_current_user(request, token)
    except HTTPException:
        return None
