from __future__ import annotations

from importlib import import_module
from typing import Any, Protocol
from urllib.parse import urlencode
from urllib.request import urlopen
from xml.etree import ElementTree

from fastapi import Request, status
from fastapi.exceptions import HTTPException
from pydantic import BaseModel, EmailStr

from dingent.core.config import settings


class SSOProfile(BaseModel):
    provider: str
    subject: str
    email: EmailStr | None = None
    username: str | None = None
    display_name: str | None = None
    attributes: dict[str, Any] = {}


class SSOProvider(Protocol):
    name: str

    def build_login_redirect_url(self, *, request: Request, next_url: str | None = None) -> str: ...

    async def authenticate_callback(self, *, request: Request) -> SSOProfile: ...


class MockSSOProvider:
    name = "mock"

    def build_login_redirect_url(self, *, request: Request, next_url: str | None = None) -> str:
        query = urlencode(
            {
                "subject": "mock-user",
                "email": "mock-sso@example.com",
                "username": "mock-sso",
                "display_name": "Mock SSO User",
                "next": next_url or "/",
            }
        )
        return f"{request.url_for('sso_callback')}?{query}"

    async def authenticate_callback(self, *, request: Request) -> SSOProfile:
        subject = request.query_params.get("subject")
        email = request.query_params.get("email")
        if not subject or not email:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mock SSO callback requires subject and email")

        username = request.query_params.get("username")
        display_name = request.query_params.get("display_name")
        return SSOProfile(
            provider=self.name,
            subject=subject,
            email=email,
            username=username,
            display_name=display_name,
            attributes=dict(request.query_params),
        )


class StandardCASProvider:
    name = "cas"

    def build_login_redirect_url(self, *, request: Request, next_url: str | None = None) -> str:
        if not settings.CAS_LOGIN_URL:
            raise RuntimeError("CAS_LOGIN_URL is required when SSO_PROVIDER=cas")

        service_url = str(request.url_for("sso_callback"))
        if next_url:
            service_url = f"{service_url}?{urlencode({'next': next_url})}"
        return f"{settings.CAS_LOGIN_URL}?{urlencode({'service': service_url})}"

    async def authenticate_callback(self, *, request: Request) -> SSOProfile:
        if not settings.CAS_VALIDATE_URL:
            raise RuntimeError("CAS_VALIDATE_URL is required when SSO_PROVIDER=cas")

        ticket = request.query_params.get("ticket")
        if not ticket:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="CAS callback requires ticket")

        service_url = str(request.url_for("sso_callback"))
        next_url = request.query_params.get("next")
        if next_url:
            service_url = f"{service_url}?{urlencode({'next': next_url})}"

        validate_url = f"{settings.CAS_VALIDATE_URL}?{urlencode({'service': service_url, 'ticket': ticket})}"
        with urlopen(validate_url, timeout=settings.CAS_VALIDATE_TIMEOUT_SECONDS) as response:
            payload = response.read()

        return parse_cas_service_response(payload)


def parse_cas_service_response(payload: bytes) -> SSOProfile:
    root = ElementTree.fromstring(payload)
    namespace = {"cas": "http://www.yale.edu/tp/cas"}
    success = root.find("cas:authenticationSuccess", namespace)
    if success is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="CAS authentication failed")

    user_element = success.find("cas:user", namespace)
    subject = user_element.text if user_element is not None else None
    if not subject:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="CAS response does not include a user")

    attributes: dict[str, Any] = {}
    attributes_element = success.find("cas:attributes", namespace)
    if attributes_element is not None:
        for child in attributes_element:
            key = child.tag.rsplit("}", maxsplit=1)[-1]
            attributes[key] = child.text

    email = attributes.get(settings.CAS_EMAIL_ATTRIBUTE)
    username = attributes.get(settings.CAS_USERNAME_ATTRIBUTE) or subject
    display_name = attributes.get(settings.CAS_DISPLAY_NAME_ATTRIBUTE)
    return SSOProfile(
        provider="cas",
        subject=subject,
        email=email,
        username=username,
        display_name=display_name,
        attributes=attributes,
    )


def load_provider_from_class_path(class_path: str) -> SSOProvider:
    module_name, _, class_name = class_path.rpartition(".")
    if not module_name or not class_name:
        raise RuntimeError("SSO_PROVIDER_CLASS must be a fully qualified class path")

    module = import_module(module_name)
    provider_class = getattr(module, class_name)
    return provider_class()


def get_sso_provider() -> SSOProvider:
    if settings.SSO_PROVIDER_CLASS:
        return load_provider_from_class_path(settings.SSO_PROVIDER_CLASS)

    if settings.SSO_PROVIDER == "mock":
        return MockSSOProvider()

    if settings.SSO_PROVIDER == "cas":
        return StandardCASProvider()

    raise RuntimeError(f"SSO provider '{settings.SSO_PROVIDER}' is not available. Install a provider package and set SSO_PROVIDER_CLASS.")
