from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.exceptions import HTTPException
from jose import JWTError, jwt
from pwdlib import PasswordHash
from sqlmodel import Session
from starlette import status

from dingent.core.config import settings
from dingent.core.db.crud.user import get_user_by_id

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = settings.ACCESS_TOKEN_EXPIRE_MINUTES

password_hash = PasswordHash.recommended()
# --- 密码相关函数 ---


def get_password_hash(password: str) -> str:
    """生成密码的哈希值"""
    return password_hash.hash(password)


def verify_password(plain_password: str, hashed_password: str | None) -> bool:
    """验证明文密码和哈希密码是否匹配"""
    if not hashed_password:
        return False
    return password_hash.verify(plain_password, hashed_password)


# --- JWT 相关函数 ---


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """
    创建 JWT Access Token

    :param data: 要编码到 Token 中的数据 (payload)。
    :param expires_delta: Token 的可选过期时间。
    :return: 编码后的 JWT 字符串。
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=15)

    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def decode_token(token: str) -> dict[str, Any] | None:
    """
    解码 JWT Token，验证其签名和有效期。

    :param token: JWT 字符串。
    :return: 如果 Token 有效，则返回 payload；否则返回 None。
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


def get_current_user_from_token(session: Session, token: str):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exception
    payload = decode_token(token)
    if payload is None:
        raise credentials_exception

    user_id: str | None = payload.get("sub")  # no default; be strict
    if not user_id:
        raise credentials_exception

    user = get_user_by_id(session, user_id)
    if user is None:
        raise credentials_exception
    return user
