from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.errors import ConflictError, NotFoundError, UnauthorizedError
from app.core.security import hash_password, verify_password
from app.domains.identity.models import ApiKey, Membership, Organization, User

ROLES = {"OWNER", "ADMIN", "MANAGER", "WAREHOUSE", "SALES", "PURCHASING", "VIEWER"}


async def create_organization_with_admin(
    db: AsyncSession,
    *,
    name: str,
    slug: str,
    admin_email: str,
    admin_password: str,
    display_name: str = "Administrator",
    timezone: str = "Asia/Shanghai",
    default_currency: str = "CNY",
) -> tuple[Organization, User, Membership]:
    existing_slug = (
        await db.execute(select(Organization).where(Organization.slug == slug))
    ).scalar_one_or_none()
    if existing_slug is not None:
        raise ConflictError(f"组织 slug 已存在: {slug}")

    existing_user = (
        await db.execute(select(User).where(User.email == admin_email))
    ).scalar_one_or_none()
    if existing_user is not None:
        raise ConflictError(f"邮箱已注册: {admin_email}")

    org = Organization(
        name=name,
        slug=slug,
        timezone=timezone,
        default_currency=default_currency,
    )
    db.add(org)
    await db.flush()

    user = User(
        email=admin_email,
        password_hash=hash_password(admin_password),
        display_name=display_name,
        is_active=True,
    )
    db.add(user)
    await db.flush()

    membership = Membership(
        organization_id=org.id,
        user_id=user.id,
        role="OWNER",
        active=True,
    )
    db.add(membership)
    await db.flush()
    return org, user, membership


async def authenticate_user(
    db: AsyncSession, *, email: str, password: str
) -> tuple[User, Membership, Organization]:
    user = (
        await db.execute(select(User).where(User.email == email, User.is_active.is_(True)))
    ).scalar_one_or_none()
    if user is None or not verify_password(password, user.password_hash):
        raise UnauthorizedError("邮箱或密码错误")

    membership = (
        await db.execute(
            select(Membership).where(
                Membership.user_id == user.id,
                Membership.active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if membership is None:
        raise UnauthorizedError("用户不属于任何有效组织")
    org = await db.get(Organization, membership.organization_id)
    if org is None:
        raise UnauthorizedError("组织不存在")
    return user, membership, org


async def create_api_key(
    db: AsyncSession,
    *,
    organization_id: str,
    created_by: str,
    name: str,
    scopes: list[str],
    expires_at: datetime | None = None,
) -> tuple[ApiKey, str]:
    prefix = "io_" + secrets.token_hex(4)
    secret = secrets.token_urlsafe(32)
    api_key = ApiKey(
        organization_id=organization_id,
        name=name,
        key_hash=ApiKey.hash_secret(secret),
        prefix=prefix,
        scopes=scopes,
        expires_at=expires_at,
        created_by=uuid.UUID(created_by),
    )
    db.add(api_key)
    await db.flush()
    record_audit(
        db,
        organization_id=organization_id,
        actor_type="USER",
        actor_id=created_by,
        action="api_key.create",
        entity_type="api_key",
        entity_id=str(api_key.id),
        after_json={"name": name, "prefix": prefix, "scopes": scopes},
    )
    return api_key, f"{prefix}.{secret}"


async def revoke_api_key(
    db: AsyncSession,
    *,
    organization_id: str,
    api_key_id: str,
    actor_id: str,
) -> ApiKey:
    api_key = (
        await db.execute(
            select(ApiKey).where(
                ApiKey.id == uuid.UUID(api_key_id),
                ApiKey.organization_id == uuid.UUID(organization_id),
            )
        )
    ).scalar_one_or_none()
    if api_key is None:
        raise NotFoundError("API Key 不存在")
    if api_key.revoked_at is not None:
        raise ConflictError("API Key 已撤销")
    api_key.revoked_at = datetime.now(UTC)
    await db.flush()
    record_audit(
        db,
        organization_id=organization_id,
        actor_type="USER",
        actor_id=actor_id,
        action="api_key.revoke",
        entity_type="api_key",
        entity_id=str(api_key.id),
        before_json={"name": api_key.name, "prefix": api_key.prefix},
    )
    return api_key


async def create_org_user(
    db: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    email: str,
    password: str,
    display_name: str,
    role: str,
) -> tuple[User, Membership]:
    if role not in ROLES:
        raise ConflictError(f"非法角色: {role}")
    existing_user = (
        await db.execute(select(User).where(User.email == email))
    ).scalar_one_or_none()
    if existing_user is not None:
        raise ConflictError(f"邮箱已注册: {email}")
    existing_member = (
        await db.execute(
            select(User)
            .join(Membership, Membership.user_id == User.id)
            .where(Membership.organization_id == uuid.UUID(organization_id), User.email == email)
        )
    ).scalar_one_or_none()
    if existing_member is not None:
        raise ConflictError("该用户已在本组织")

    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=display_name,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    membership = Membership(
        organization_id=uuid.UUID(organization_id),
        user_id=user.id,
        role=role,
        active=True,
    )
    db.add(membership)
    await db.flush()
    record_audit(
        db,
        organization_id=organization_id,
        actor_type="USER",
        actor_id=actor_id,
        action="user.create",
        entity_type="user",
        entity_id=str(user.id),
        after_json={"email": email, "role": role},
    )
    return user, membership
