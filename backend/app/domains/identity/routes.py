from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import ConflictError
from app.core.permissions import require_scope
from app.core.security import CurrentUser, create_access_token, get_current_user
from app.domains.identity.models import ApiKey, Membership, Organization, User
from app.domains.identity.schemas import (
    ApiKeyCreate,
    ApiKeyCreated,
    ApiKeyOut,
    LoginRequest,
    LoginResponse,
    MeResponse,
    OrganizationOut,
    UserCreate,
    UserOut,
    UserWithMembershipOut,
)
from app.domains.identity.service import (
    authenticate_user,
    create_api_key,
    create_org_user,
    revoke_api_key,
)

router = APIRouter(tags=["identity"])


@router.post("/auth/login", response_model=LoginResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> LoginResponse:
    user, membership, org = await authenticate_user(
        db, email=str(payload.email), password=payload.password
    )
    token = create_access_token(str(user.id))
    return LoginResponse(
        access_token=token,
        user=UserOut.model_validate(user),
        organization=OrganizationOut.model_validate(org),
        role=membership.role,
    )


@router.post("/auth/logout")
async def logout(user: CurrentUser = Depends(get_current_user)) -> dict[str, bool]:
    # JWT 无状态；由客户端丢弃 token。
    return {"ok": True}


@router.get("/auth/me", response_model=MeResponse)
async def me(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
) -> MeResponse:
    db_user = await db.get(User, user.user_id)
    org = await db.get(Organization, user.organization_id)
    if db_user is None or org is None:
        raise ConflictError("用户或组织不存在")
    return MeResponse(
        user=UserOut.model_validate(db_user),
        organization=OrganizationOut.model_validate(org),
        role=user.role,
        scopes=sorted(user.scopes),
    )


@router.get("/users", response_model=list[UserWithMembershipOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("users:manage")),
) -> list[UserWithMembershipOut]:
    rows = (
        await db.execute(
            select(User, Membership.role)
            .join(Membership, Membership.user_id == User.id)
            .where(Membership.organization_id == user.organization_id)
            .order_by(User.created_at)
        )
    ).all()
    return [
        UserWithMembershipOut(user=UserOut.model_validate(db_user), role=role)
        for db_user, role in rows
    ]


@router.post("/users", response_model=UserWithMembershipOut, status_code=201)
async def create_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
    actor: CurrentUser = Depends(require_scope("users:manage")),
) -> UserWithMembershipOut:
    db_user, _ = await create_org_user(
        db,
        organization_id=actor.organization_id,
        actor_id=actor.user_id,
        email=str(payload.email),
        password=payload.password,
        display_name=payload.display_name,
        role=payload.role,
    )
    await db.commit()
    return UserWithMembershipOut(
        user=UserOut.model_validate(db_user),
        role=payload.role,
    )


@router.get("/integrations/api-keys", response_model=list[ApiKeyOut])
async def list_api_keys(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("integrations:read")),
) -> list[ApiKeyOut]:
    rows = (
        await db.execute(
            select(ApiKey).where(ApiKey.organization_id == user.organization_id)
        )
    ).scalars().all()
    return [ApiKeyOut.model_validate(row) for row in rows]


@router.post("/integrations/api-keys", response_model=ApiKeyCreated, status_code=201)
async def create_api_key_route(
    payload: ApiKeyCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("integrations:write")),
) -> ApiKeyCreated:
    api_key, secret = await create_api_key(
        db,
        organization_id=user.organization_id,
        created_by=user.user_id,
        name=payload.name,
        scopes=payload.scopes,
        expires_at=payload.expires_at,
    )
    await db.commit()
    return ApiKeyCreated(
        **ApiKeyOut.model_validate(api_key).model_dump(),
        api_key=secret,
    )


@router.delete("/integrations/api-keys/{api_key_id}")
async def revoke_api_key_route(
    api_key_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("integrations:write")),
) -> dict[str, bool]:
    await revoke_api_key(
        db,
        organization_id=user.organization_id,
        api_key_id=api_key_id,
        actor_id=user.user_id,
    )
    await db.commit()
    return {"ok": True}
