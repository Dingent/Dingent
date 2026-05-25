from typing import Any
from uuid import UUID

from sqlmodel import Session, select

from dingent.core.db.models import Role, User, UserIdentity, Workspace, WorkspaceMember
from dingent.core.workspaces.schemas import UserCreate


def get_user(session: Session, email: str) -> User | None:
    statement = select(User).where(User.email == email)
    result = session.exec(statement).first()
    return result


def get_user_by_id(session: Session, user_id: str | UUID) -> User | None:
    statement = select(User).where(User.id == UUID(str(user_id)))
    result = session.exec(statement).first()
    return result


def get_user_identity(session: Session, provider: str, provider_subject: str) -> UserIdentity | None:
    statement = select(UserIdentity).where(UserIdentity.provider == provider, UserIdentity.provider_subject == provider_subject)
    return session.exec(statement).first()


def create_user(session: Session, user_in: UserCreate) -> User:
    """
    接收 Pydantic 模型，处理密码加密，保存到数据库，并创建默认工作空间。
    """
    from dingent.server.auth.security import get_password_hash

    # 1. 密码加密逻辑
    hashed_pw = get_password_hash(user_in.password)

    # 2. 创建用户对象
    db_user = User(
        username=user_in.username,
        email=user_in.email,
        hashed_password=hashed_pw,
    )

    # 分配默认角色 (系统级角色，如 standard user)
    default_role_name = "user"
    statement = select(Role).where(Role.name == default_role_name)
    role_obj = session.exec(statement).first()
    if not role_obj:
        raise ValueError(f"系统错误：默认角色 '{default_role_name}' 未在数据库中创建。")
    db_user.roles.append(role_obj)

    session.add(db_user)
    # 注意：这里先 flush 以获取 db_user.id，但不 commit，保证原子性
    session.flush()

    # --- 新增：自动创建默认工作空间 ---

    # 3. 创建个人工作空间
    default_workspace = Workspace(
        name=f"{user_in.username}'s Workspace",
        slug=f"user-{db_user.id}-workspace",
        description="Default personal workspace",
    )
    session.add(default_workspace)
    # flush 以获取 workspace.id
    session.flush()

    # 4. 将用户设为该空间的 Owner
    member_link = WorkspaceMember(workspace_id=default_workspace.id, user_id=db_user.id, role="owner")
    session.add(member_link)

    # 5. 统一提交
    session.commit()
    session.refresh(db_user)

    return db_user


def create_external_user(
    session: Session,
    *,
    provider: str,
    provider_subject: str,
    email: str,
    username: str,
    display_name: str | None = None,
    raw_profile: dict[str, Any] | None = None,
) -> User:
    db_user = User(
        username=username,
        email=email,
        full_name=display_name,
        hashed_password=None,
    )

    default_role_name = "user"
    statement = select(Role).where(Role.name == default_role_name)
    role_obj = session.exec(statement).first()
    if not role_obj:
        raise ValueError(f"系统错误：默认角色 '{default_role_name}' 未在数据库中创建。")
    db_user.roles.append(role_obj)

    session.add(db_user)
    session.flush()

    identity = UserIdentity(
        user_id=db_user.id,
        provider=provider,
        provider_subject=provider_subject,
        email=email,
        username=username,
        display_name=display_name,
        raw_profile=raw_profile or {},
    )
    session.add(identity)

    default_workspace = Workspace(
        name=f"{username}'s Workspace",
        slug=f"user-{db_user.id}-workspace",
        description="Default personal workspace",
    )
    session.add(default_workspace)
    session.flush()

    member_link = WorkspaceMember(workspace_id=default_workspace.id, user_id=db_user.id, role="owner")
    session.add(member_link)
    session.commit()
    session.refresh(db_user)
    return db_user


def link_user_identity(
    session: Session,
    *,
    user: User,
    provider: str,
    provider_subject: str,
    email: str | None = None,
    username: str | None = None,
    display_name: str | None = None,
    raw_profile: dict[str, Any] | None = None,
) -> UserIdentity:
    identity = UserIdentity(
        user_id=user.id,
        provider=provider,
        provider_subject=provider_subject,
        email=email,
        username=username,
        display_name=display_name,
        raw_profile=raw_profile or {},
    )
    session.add(identity)
    session.commit()
    session.refresh(identity)
    return identity
