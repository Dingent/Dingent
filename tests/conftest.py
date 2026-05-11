import os
from pathlib import Path
import shutil
import uuid
from fastapi.testclient import TestClient
from dingent.server.api.dependencies import get_db_session
from dingent.server.app import create_app
import pytest
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from dingent.core.db.models import *
from dingent.core.paths import paths, AppPaths

TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(name="session")
def session_fixture():
    """
    创建一个测试用的 Session。
    每个测试函数都会获得一个新的 Session，且在这个 Session 中的操作
    会在测试结束后回滚 (Rollback)，保证测试之间互不干扰。
    """
    # 创建内存引擎
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False}, poolclass=StaticPool)

    # 创建表结构
    SQLModel.metadata.create_all(engine)

    with Session(engine) as init_session:
        required_roles = ["admin", "user", "guest"]
        for role_name in required_roles:
            init_session.add(Role(name=role_name, description="Test Role"))
        init_session.commit()

    with Session(engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(session: Session):
    app = create_app()

    def get_session_override():
        return session

    app.dependency_overrides[get_db_session] = get_session_override

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture
def create_workspace(session: Session):
    """
    返回一个函数，调用该函数可以快速创建一个 Workspace。
    """

    def _create(id=None, name="Test Workspace"):
        workspace = Workspace(
            id=id or uuid.uuid4(),
            name=name,
            slug=name.lower().replace(" ", "-"),
            allow_guest_access=True,
        )
        session.add(workspace)
        session.commit()
        session.refresh(workspace)
        return workspace

    return _create


@pytest.fixture(scope="session", autouse=True)
def mock_app_paths(tmp_path_factory):
    """
    全局 Fixture：
    1. 创建一个临时的测试根目录。
    2. 设置环境变量 DINGENT_HOME 指向它。
    3. 重新初始化全局的 paths 对象，让它加载新路径。
    4. 测试结束后清理。
    """
    # 1. 创建临时目录 (Scope=session 时推荐用 tmp_path_factory)
    test_home = tmp_path_factory.mktemp("dingent_test_home")

    # 2. 设置环境变量 (强制让 AppPaths 走 if env_home: 分支)
    os.environ["DINGENT_HOME"] = str(test_home)

    # 3. 关键步骤：重新运行 __init__ 逻辑
    # 因为 paths 是在模块导入时就创建好的单例，我们需要手动刷新它
    paths.__init__()

    # 验证一下
    print(f"\n[Test Setup] App paths redirected to: {paths.data_root}")
    assert paths.data_root == test_home

    yield test_home

    del os.environ["DINGENT_HOME"]


@pytest.fixture(scope="session")
def plugin_cache_dir():
    """
    创建一个缓存目录，里面放好了所有测试需要的插件。
    这个目录在整个测试会话期间只创建一次。
    """

    source_plugins = Path("tests/data/plugins")
    return source_plugins


@pytest.fixture(autouse=True)
def populate_plugins(mock_app_paths, plugin_cache_dir):
    """
    软链接插件目录到 App 的 plugins 目录下。
    """
    target_plugin_dir = mock_app_paths / "plugins"
    target_plugin_dir.mkdir(parents=True, exist_ok=True)

    for plugin_path in plugin_cache_dir.iterdir():
        target_link = target_plugin_dir / plugin_path.name
        if not target_link.exists():
            target_link.symlink_to(plugin_path.resolve(), target_is_directory=True)
