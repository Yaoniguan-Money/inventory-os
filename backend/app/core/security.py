from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.errors import UnauthorizedError
from app.models import ApiKey, Membership, Organization, User

_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hasher.verify(password_hash, password)
    except (VerifyMismatchError, ValueError):
        return False


def create_access_token(subject: str, expires_minutes: int | None = None) -> str:
    expire_minutes = expires_minutes or settings.access_token_expire_minutes
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "iat": now,
        "exp": now + timedelta(minutes=expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_token(token: str) -> dict[str, Any]:
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("登录状态无效或已过期") from exc


class CurrentUser:
    """Authenticated actor: user + active membership (scopes already computed)."""

    def __init__(
        self,
        *,
        user_id: str,
        email: str,
        organization_id: str,
        role: str,
        scopes: set[str],
        is_org_owner: bool = False,
    ) -> None:
        self.user_id = user_id
        self.email = email
        self.organization_id = organization_id
        self.role = role
        self.scopes = scopes
        self.is_org_owner = is_org_owner

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> CurrentUser:
    from app.core.permissions import role_scopes

    auth_header = request.headers.get("Authorization", "")
    token: str | None = None
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
    if not token:
        raise UnauthorizedError("缺少 Authorization 头")

    payload = decode_token(token)
    user_id = payload.get("sub")
    if not user_id:
        raise UnauthorizedError("Token 缺少用户标识")

    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("用户不存在或已停用")

    membership = (
        await db.execute(
            select(Membership).where(
                Membership.user_id == user_id,
                Membership.active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise UnauthorizedError("用户不属于任何有效组织")

    org = await db.get(Organization, membership.organization_id)
    if org is None:
        raise UnauthorizedError("组织不存在")

    return CurrentUser(
        user_id=str(user.id),
        email=user.email,
        organization_id=str(membership.organization_id),
        role=membership.role,
        scopes=role_scopes(membership.role),
        is_org_owner=membership.role == "OWNER",
    )


async def get_actor_id(request: Request, db: AsyncSession = Depends(get_db)) -> str | None:
    try:
        user = await get_current_user(request, db)
    except UnauthorizedError:
        return None
    return user.user_id


async def authenticate_api_key(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> ApiKey:
    """Authenticate an API key (X-API-Key) for integration endpoints."""

    from app.core.errors import PermissionDeniedError

    key_value = request.headers.get("X-API-Key", "")
    if not key_value:
        raise PermissionDeniedError("缺少 X-API-Key 头")

    prefix, _, secret = key_value.partition(".")
    if not prefix or not secret:
        raise PermissionDeniedError("API Key 格式无效")

    # Hash with the same algorithm used for keys: sha256(secret) hex digest.
    import hashlib

    secret_hash = hashlib.sha256(secret.encode("utf-8")).hexdigest()
    key = (
        await db.execute(
            select(ApiKey).where(
                ApiKey.prefix == prefix,
                ApiKey.revoked_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if key is None or key.key_hash != secret_hash:
        raise PermissionDeniedError("API Key 无效或已撤销")
    if key.expires_at is not None and key.expires_at < datetime.now(UTC):
        raise PermissionDeniedError("API Key 已过期")
    key.last_used_at = datetime.now(UTC)
    await db.flush()
    return key
