from datetime import timedelta
from typing import Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlmodel import Session
from starlette.responses import RedirectResponse

from dingent.core.config import settings
from dingent.core.db.crud.user import create_external_user, create_user, get_user, get_user_identity, link_user_identity
from dingent.core.db.models import User
from dingent.core.workspaces.schemas import UserCreate, UserRead
from dingent.server.api.dependencies import authenticate_user, get_current_user, get_db_session
from dingent.server.auth.security import ACCESS_TOKEN_EXPIRE_MINUTES, create_access_token
from dingent.server.auth.sso import SSOProfile, get_sso_provider

router = APIRouter(prefix="/auth", tags=["Authentication"])


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserRead


class AuthConfigResponse(BaseModel):
    password_login_enabled: bool = True
    sso_enabled: bool
    sso_label: str
    sso_login_url: str | None = None


def to_user_read(user: User) -> UserRead:
    return UserRead(
        id=user.id,
        email=user.email,
        username=user.username,
        full_name=user.full_name,
        role=[role.name for role in user.roles] or ["user"],
    )


def issue_login_response(user: User | UserRead) -> LoginResponse:
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    user_read = user if isinstance(user, UserRead) else to_user_read(user)
    access_token = create_access_token(
        data={"sub": str(user_read.id)},
        expires_delta=access_token_expires,
    )
    return LoginResponse(
        access_token=access_token,
        token_type="bearer",
        user=user_read,
    )


def get_or_create_sso_user(session: Session, profile: SSOProfile) -> User:
    identity = get_user_identity(session, profile.provider, profile.subject)
    if identity:
        return identity.user

    if profile.email and settings.SSO_ALLOW_EMAIL_LINKING:
        existing_user = get_user(session, profile.email)
        if existing_user:
            link_user_identity(
                session,
                user=existing_user,
                provider=profile.provider,
                provider_subject=profile.subject,
                email=profile.email,
                username=profile.username,
                display_name=profile.display_name,
                raw_profile=profile.attributes,
            )
            return existing_user

    if not settings.SSO_AUTO_CREATE_USER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="SSO user is not linked to a Dingent account")

    if not profile.email:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="SSO profile does not include an email address")

    username = profile.username or profile.email.split("@", maxsplit=1)[0]
    return create_external_user(
        session,
        provider=profile.provider,
        provider_subject=profile.subject,
        email=profile.email,
        username=username,
        display_name=profile.display_name,
        raw_profile=profile.attributes,
    )


@router.get("/config", response_model=AuthConfigResponse)
def get_auth_config() -> AuthConfigResponse:
    return AuthConfigResponse(
        sso_enabled=settings.SSO_ENABLED,
        sso_label=settings.SSO_LABEL,
        sso_login_url="/auth/sso/login" if settings.SSO_ENABLED else None,
    )


@router.get("/me", response_model=UserRead)
def get_me(current_user: User = Depends(get_current_user)) -> UserRead:
    return to_user_read(current_user)


@router.post("/token", response_model=LoginResponse)
async def login_for_access_token(
    user: UserRead = Depends(authenticate_user),
):
    return issue_login_response(user)


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def register_user(user_in: UserCreate, session: Session = Depends(get_db_session)):
    """
    用户注册接口
    """
    existing_user = get_user(session, user_in.email)
    if existing_user:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Email {user_in.email} already registered")

    new_user = create_user(session, user_in)

    return new_user


@router.get("/sso/login")
async def sso_login(request: Request, next: str | None = Query(default=None)):
    if not settings.SSO_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SSO is not enabled")

    provider = get_sso_provider()
    login_url = provider.build_login_redirect_url(request=request, next_url=next)
    return RedirectResponse(login_url)


@router.get("/sso/callback")
async def sso_callback(request: Request, next: str | None = Query(default=None), session: Session = Depends(get_db_session)):
    if not settings.SSO_ENABLED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SSO is not enabled")

    provider = get_sso_provider()
    profile = await provider.authenticate_callback(request=request)
    user = get_or_create_sso_user(session, profile)
    login_response = issue_login_response(user)
    callback_url = settings.SSO_CALLBACK_FRONTEND_URL
    query = urlencode(
        {
            "token": login_response.access_token,
            "next": next or "/",
        }
    )
    return RedirectResponse(f"{callback_url}?{query}")
