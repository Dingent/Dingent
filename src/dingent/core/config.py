from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

from dingent.core.paths import paths


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(paths.env_file), env_file_encoding="utf-8", extra="ignore")

    # --- 基础配置 ---
    PROJECT_NAME: str = "Dingent"

    DING_MASTER_KEY: str | None = None

    DATABASE_URL: str = f"sqlite:///{paths.sqlite_path}"

    # --- Authentication ---
    SECRET_KEY: str = "YOUR_SUPER_SECRET_KEY_CHANGE_THIS"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 3600
    SSO_ENABLED: bool = False
    SSO_PROVIDER: str = "mock"
    SSO_LABEL: str = "SSO"
    SSO_AUTO_CREATE_USER: bool = True
    SSO_ALLOW_EMAIL_LINKING: bool = False
    SSO_CALLBACK_FRONTEND_URL: str = "/auth/sso/callback"
    SSO_PROVIDER_CLASS: str | None = None
    CAS_LOGIN_URL: str | None = None
    CAS_VALIDATE_URL: str | None = None
    CAS_EMAIL_ATTRIBUTE: str = "email"
    CAS_USERNAME_ATTRIBUTE: str = "username"
    CAS_DISPLAY_NAME_ATTRIBUTE: str = "displayName"
    CAS_VALIDATE_TIMEOUT_SECONDS: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
