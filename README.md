# Dingent

Dingent is a cross-platform AI agent framework. It combines a Python backend, a Next.js frontend, workspace-based collaboration, assistant/workflow management, plugin execution, and chat runtime APIs into one deployable application.

The project is under active development. The current codebase is centered around the bundled FastAPI service and the `ui/` Next.js application.

## What Is Included

- FastAPI backend under `src/dingent/`.
- Next.js dashboard and chat UI under `ui/`.
- SQLModel persistence with Alembic migrations.
- Workspace membership and role checks.
- Local email/password authentication with Dingent-issued JWT access tokens.
- Open SSO extension points for CAS and private enterprise providers.
- Assistant, workflow, plugin, market, logging, and model configuration services.

## Repository Layout

- `src/dingent/`: Python package, FastAPI app, CLI, database models, services, auth, and runtime logic.
- `ui/`: Next.js frontend built with Bun.
- `alembic/`: Database migrations.
- `tests/`: Backend and integration tests.
- `docs/`, `examples/`, `website/`: Project documentation and examples.
- `justfile`: Common development commands.

## Development

Python dependencies are managed with `uv`; frontend dependencies are managed with `bun`.

```bash
uv sync
cd ui && bun install
```

Run backend tests:

```bash
uv run pytest
```

Run lint and format checks:

```bash
uv run ruff check .
uv run ruff format --check .
uv run basedpyright
```

Build the frontend:

```bash
just _build-ui
```

Build the assembled application:

```bash
just build
```

## Authentication

Dingent uses a two-layer authentication model:

- External authentication proves who the user is.
- Dingent authentication issues a Dingent JWT and applies workspace permissions.

The built-in password login flow remains available at `/api/v1/auth/token`. SSO providers should authenticate the external identity, map it to a local Dingent `User`, and then reuse the same Dingent token flow.

Core open-source auth pieces:

- `User`: Dingent's internal account and permission subject.
- `UserIdentity`: external identity binding, keyed by `provider` and `provider_subject`.
- `SSOProvider`: provider interface for login redirects and callback validation.
- `MockSSOProvider`: local development provider.
- `StandardCASProvider`: basic CAS `/serviceValidate` or `/p3/serviceValidate` XML integration.
- `/api/v1/auth/config`: frontend-safe auth configuration.
- `/api/v1/auth/sso/login`: starts SSO login.
- `/api/v1/auth/sso/callback`: completes SSO login and redirects to the frontend callback page.

## SSO Configuration

Common settings are read from the Dingent environment or `.env` file:

```env
SECRET_KEY=change-me
ACCESS_TOKEN_EXPIRE_MINUTES=3600
SSO_ENABLED=false
SSO_PROVIDER=mock
SSO_LABEL=SSO
SSO_AUTO_CREATE_USER=true
SSO_ALLOW_EMAIL_LINKING=false
SSO_CALLBACK_FRONTEND_URL=/auth/sso/callback
SSO_PROVIDER_CLASS=
```

For a standard CAS server:

```env
SSO_ENABLED=true
SSO_PROVIDER=cas
SSO_LABEL=CAS
CAS_LOGIN_URL=https://sso.example.com/cas/login
CAS_VALIDATE_URL=https://sso.example.com/cas/p3/serviceValidate
CAS_EMAIL_ATTRIBUTE=email
CAS_USERNAME_ATTRIBUTE=username
CAS_DISPLAY_NAME_ATTRIBUTE=displayName
```

`SSO_ALLOW_EMAIL_LINKING` is disabled by default. This prevents a new external identity from being silently attached to an existing local account just because the email matches.

## Private Enterprise SSO

Internal company SSO details should not be committed to this open-source repository.

Keep these in a separate private package or private deployment layer:

- Internal CAS or SSO URLs.
- App IDs, secrets, certificates, and private keys.
- Java SDK compatibility logic.
- Non-standard ticket validation, signing, encryption, or token exchange.
- Internal employee ID, department, role, and organization mapping.
- Internal audit and error-code handling.

Recommended private package shape:

```text
company-dingent-auth/
  company_auth/
    dingent.py
```

The private package should expose a provider class:

```python
from dingent.server.auth.sso import SSOProfile


class CompanyCasProvider:
    name = "company_cas"

    def build_login_redirect_url(self, *, request, next_url=None) -> str:
        ...

    async def authenticate_callback(self, *, request) -> SSOProfile:
        ...
```

Then configure the deployment without changing the open-source Dingent code:

```env
SSO_ENABLED=true
SSO_PROVIDER=company_cas
SSO_PROVIDER_CLASS=company_auth.dingent.CompanyCasProvider
```

The provider only needs to return `SSOProfile(provider, subject, email, username, display_name, attributes)`. Dingent handles local user binding, account creation, JWT issuance, and workspace permissions.

## Frontend Auth Flow

The frontend reads `/api/v1/auth/config` to decide whether to show the SSO button. It does not know CAS URLs, secrets, ticket validation rules, or internal user mapping.

SSO flow:

```text
Login page -> /api/v1/auth/sso/login -> external SSO -> /api/v1/auth/sso/callback -> /auth/sso/callback -> Dingent app
```

## Contributing

Open-source contributions should keep enterprise-specific integrations behind generic interfaces. If a feature requires private infrastructure, add an extension point, a mock implementation, and documentation instead of committing private logic or secrets.

Before opening a pull request, run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

For frontend changes, also run:

```bash
cd ui && bun run build
```

## License

This project is licensed under the [MIT License](./LICENSE).
