from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, Path, Request, status
from fastapi.exceptions import HTTPException
from fastapi.security.oauth2 import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlmodel import Session, select

from dingent.core.config import settings
from dingent.core.db.crud import assistant as crud_assistant
from dingent.core.db.crud.user import get_user
from dingent.core.db.models import User, Workspace, WorkspaceMember
from dingent.core.db.session import engine
from dingent.core.logs.log_manager import LogManager
from dingent.core.plugins.plugin_manager import PluginManager
from dingent.core.workspaces.schemas import UserRead
from dingent.server.auth.security import get_current_user_from_token, verify_password
from dingent.server.services.user_plugin_service import UserPluginService
from dingent.server.services.user_workspace_service import UserWorkspaceService
from dingent.server.services.workspace_assistant_service import WorkspaceAssistantService
from dingent.server.services.workspace_workflow_service import WorkspaceWorkflowService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/v1/auth/token")
oauth2_scheme_optional = OAuth2PasswordBearer(tokenUrl="api/v1/auth/token", auto_error=False)


def get_db_session():
    with Session(engine, expire_on_commit=False) as session:
        try:
            yield session
            session.commit()  # 只有在路径函数未抛异常时提交
        except Exception:
            session.rollback()
            raise


async def get_current_user(
    session: Session = Depends(get_db_session),
    token: str = Depends(oauth2_scheme),
):
    return get_current_user_from_token(session, token)


async def get_current_user_optional(
    session: Session = Depends(get_db_session),
    token: str | None = Depends(oauth2_scheme_optional),
) -> User | None:
    """
    Optional authentication dependency for guest support.
    Returns User if authenticated, None if not authenticated.
    """
    if not token:
        return None
    try:
        return get_current_user_from_token(session, token)
    except HTTPException:
        return None


def get_current_workspace(
    # 1. 前端必须在 Header 中传递这个 ID
    workspace_slug: str = Path(..., description="The unique slug of the workspace"),
    current_user: User = Depends(get_current_user),
    # 3. 获取数据库会话
    session: Session = Depends(get_db_session),
) -> Workspace:
    """
    验证用户是否是目标 Workspace 的成员。
    如果是，返回 Workspace 对象；否则抛出 403。
    """
    # 查询关联表
    statement = select(Workspace).where(Workspace.slug == workspace_slug)
    workspace = session.exec(statement).first()
    # 获取并返回 Workspace 对象
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    member_statement = select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.user_id == current_user.id)
    member = session.exec(member_statement).first()
    if not member:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this workspace or it does not exist.")

    return workspace


def get_current_workspace_allow_guest(
    workspace_slug: str = Path(..., description="The unique slug of the workspace"),
    current_user: User | None = Depends(get_current_user_optional),
    session: Session = Depends(get_db_session),
) -> Workspace:
    """
    Get workspace allowing both authenticated users and guests.
    For authenticated users, verifies workspace membership.
    For guests, checks if workspace allows guest access.
    """
    # 查询工作空间
    statement = select(Workspace).where(Workspace.slug == workspace_slug)
    workspace = session.exec(statement).first()

    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # 如果用户已登录，验证成员资格
    if current_user:
        member_statement = select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace.id, WorkspaceMember.user_id == current_user.id)
        member = session.exec(member_statement).first()
        if not member:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="You do not have access to this workspace or it does not exist.")
    else:
        # 游客模式：检查工作空间是否允许游客访问
        if not workspace.allow_guest_access:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="This workspace does not allow guest access. Please sign in or contact the workspace owner.")

    return workspace


def get_log_manager(
    request: Request,
) -> LogManager:
    """
    Dependency to get the LogManager
    """
    return request.app.state.log_manager


def get_resource_manager(
    request: Request,
):
    return request.app.state.resource_manager


def get_plugin_manager(
    request: Request,
) -> PluginManager:
    """
    Dependency to get the PluginManager.
    """
    return request.app.state.plugin_manager


CurrentUserOptional = Annotated[User | None, Depends(get_current_user_optional)]
DbSession = Annotated[Session, Depends(get_db_session)]
CurrentWorkspaceAllowGuest = Annotated[Workspace, Depends(get_current_workspace_allow_guest)]


def get_workspace_assistant_service(
    request: Request,
    workspace: CurrentWorkspaceAllowGuest,
    session: Session = Depends(get_db_session),
) -> WorkspaceAssistantService:
    """
    Dependency to get the AssistantRuntimeManager.
    """
    assistant_factory = request.app.state.assistant_factory
    return WorkspaceAssistantService(workspace.id, session, assistant_factory)


def get_user_plugin_service(
    request: Request,
    user: User = Depends(get_current_user),
    session: Session = Depends(get_db_session),
):
    return UserPluginService(
        user.id,
        session,
        request.app.state.plugin_registry,
    )


async def get_visitor_id(x_visitor_id: str | None = Header(default=None, alias="X-Visitor-Id")) -> str | None:
    if x_visitor_id:
        try:
            return str(UUID(x_visitor_id))
        except ValueError:
            return None
    return None


def get_workspace_workflow_service(
    user: CurrentUserOptional,
    workspace: CurrentWorkspaceAllowGuest,
    session: Session = Depends(get_db_session),
    assistant_service: WorkspaceAssistantService = Depends(get_workspace_assistant_service),
    log_manager: LogManager = Depends(get_log_manager),
    visitor_id: UUID | None = Depends(get_visitor_id),
):
    current_user_id = user.id if user else None
    return WorkspaceWorkflowService(
        workspace_id=workspace.id,
        user_id=current_user_id,
        session=session,
        assistant_service=assistant_service,
        log_manager=log_manager,
        visitor_id=visitor_id,
    )


def get_analytics_manager():
    """
    Dependency to get the analyticsManager
    """
    return None


def get_market_service(
    request: Request,
):
    """
    Dependency to get the MarketService.

    Note: The original code initializes this separately. For consistency,
    it's better to manage it within the AppContext as well.
    If you add `self.market_service = MarketService(self.config_manager.project_root)`
    to your AppContext's __init__, this will work seamlessly.
    """
    return request.app.state.market_service


def get_user_workspace_service(
    session: Session = Depends(get_db_session),
    user: User = Depends(get_current_user),
) -> UserWorkspaceService:
    return UserWorkspaceService(session=session, user_id=user.id)


def get_assistant_and_verify_ownership(
    assistant_id: UUID,
    db: Session = Depends(get_db_session),
    current_workspace: Workspace = Depends(get_current_workspace),
):
    """
    FastAPI Dependency:
    1. Fetches an Assistant by ID using the generic CRUD function.
    2. Raises a 404 if it doesn't exist.
    3. Raises a 403 if the current user is not the owner.
    4. Returns the valid Assistant object if all checks pass.
    """
    # 1. Use the "dumb" CRUD function to get the data
    assistant = crud_assistant.get_assistant_by_id(db=db, id=assistant_id)

    # 2. Check for existence
    if not assistant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Assistant not found",
        )

    # 3. Check for ownership -- THIS IS THE KEY STEP
    if assistant.workspace_id != current_workspace.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this assistant",
        )

    # 4. If all is good, return the object
    return assistant


def get_app_settings():
    return settings


def authenticate_user(form_data: OAuth2PasswordRequestForm = Depends(), session: Session = Depends(get_db_session)) -> UserRead:
    """
    生产级别的用户认证函数
    1. 从数据库获取用户
    2. 验证密码哈希
    """

    user = get_user(session, form_data.username)
    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return UserRead(
        id=user.id,
        email=user.email,
        username=user.username,
        full_name=user.full_name,
        role=[role.name for role in user.roles] or ["user"],
    )
