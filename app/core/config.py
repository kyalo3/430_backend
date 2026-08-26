"""Application settings — fail fast on missing production-critical values."""
from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import BaseSettings, Field, validator


class Settings(BaseSettings):
    app_name: str = "Sustainashare API"
    app_env: str = Field("development", env="APP_ENV")
    api_prefix: str = "/api/v1"
    secret_key: str = Field(..., env="SECRET_KEY")
    mongo_details: str = Field(..., env="MONGO_DETAILS")
    access_token_expire_minutes: int = Field(15, env="ACCESS_TOKEN_EXPIRE_MINUTES")
    refresh_token_expire_days: int = Field(7, env="REFRESH_TOKEN_EXPIRE_DAYS")
    cors_origins: str = Field("http://localhost:5173,http://127.0.0.1:5173", env="CORS_ORIGINS")
    trusted_hosts: str = Field("localhost,127.0.0.1", env="TRUSTED_HOSTS")
    cookie_secure: bool = Field(False, env="COOKIE_SECURE")
    cookie_samesite: str = Field("lax", env="COOKIE_SAMESITE")
    cookie_domain: str | None = Field(None, env="COOKIE_DOMAIN")
    csrf_header_name: str = "X-CSRF-Token"
    rate_limit_auth_per_minute: int = Field(20, env="RATE_LIMIT_AUTH_PER_MINUTE")
    enable_docs: bool = Field(True, env="ENABLE_DOCS")
    verification_required: bool = Field(False, env="VERIFICATION_REQUIRED")

    class Config:
        env_file = ".env"
        case_sensitive = False

    @validator("secret_key")
    def secret_must_be_strong(cls, v: str, values):
        env = values.get("app_env", "development")
        if v in {"secret", "dev-local-secret-change-me"} and env == "production":
            raise ValueError("SECRET_KEY is too weak for production")
        if len(v) < 32 and env == "production":
            raise ValueError("SECRET_KEY must be at least 32 characters in production")
        return v

    @property
    def cors_origin_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def trusted_host_list(self) -> List[str]:
        return [h.strip() for h in self.trusted_hosts.split(",") if h.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
