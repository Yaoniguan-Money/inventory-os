from __future__ import annotations

from typing import Annotated

from fastapi import Depends

from app.core.errors import PermissionDeniedError
from app.core.security import CurrentUser, get_current_user

ROLE_SCOPES: dict[str, set[str]] = {
    "OWNER": {
        "products:read", "products:write",
        "inventory:read", "inventory:receive", "inventory:adjust", "inventory:ship",
        "orders:read", "orders:write", "orders:confirm", "orders:fulfill",
        "purchases:read", "purchases:write",
        "pricing:internal:read", "pricing:internal:write", "pricing:cost:read",
        "market:read", "market:write",
        "health:read",
        "integrations:read", "integrations:write",
        "users:manage",
        "equipment:read", "equipment:write",
        "knowledge:read", "knowledge:write",
        "ai:read",
    },
    "ADMIN": {
        "products:read", "products:write",
        "inventory:read", "inventory:receive", "inventory:adjust", "inventory:ship",
        "orders:read", "orders:write", "orders:confirm", "orders:fulfill",
        "purchases:read", "purchases:write",
        "pricing:internal:read", "pricing:internal:write", "pricing:cost:read",
        "market:read", "market:write",
        "health:read",
        "integrations:read", "integrations:write",
        "users:manage",
        "equipment:read", "equipment:write",
        "knowledge:read", "knowledge:write",
        "ai:read",
    },
    "MANAGER": {
        "products:read", "products:write",
        "inventory:read", "inventory:receive", "inventory:adjust", "inventory:ship",
        "orders:read", "orders:write", "orders:confirm", "orders:fulfill",
        "purchases:read", "purchases:write",
        "pricing:internal:read", "pricing:internal:write", "pricing:cost:read",
        "market:read", "market:write",
        "health:read",
        "integrations:read",
        "equipment:read", "equipment:write",
        "knowledge:read", "knowledge:write",
        "ai:read",
    },
    "WAREHOUSE": {
        "products:read",
        "inventory:read", "inventory:receive", "inventory:adjust", "inventory:ship",
        "orders:read", "orders:confirm", "orders:fulfill",
        "purchases:read",
        "pricing:cost:read",
        "health:read",
        "equipment:read",
        "knowledge:read",
        "ai:read",
    },
    "SALES": {
        "products:read",
        "inventory:read",
        "orders:read", "orders:write", "orders:confirm", "orders:fulfill",
        "purchases:read",
        "pricing:internal:read", "pricing:internal:write",
        "market:read",
        "health:read",
        "equipment:read",
        "knowledge:read",
        "ai:read",
    },
    "PURCHASING": {
        "products:read",
        "inventory:read",
        "orders:read",
        "purchases:read", "purchases:write",
        "pricing:internal:read", "pricing:internal:write", "pricing:cost:read",
        "market:read", "market:write",
        "health:read",
        "equipment:read",
        "knowledge:read",
        "ai:read",
    },
    "VIEWER": {
        "products:read",
        "inventory:read",
        "orders:read",
        "purchases:read",
        "pricing:internal:read", "pricing:cost:read",
        "market:read",
        "health:read",
        "equipment:read",
        "knowledge:read",
        "ai:read",
    },
}


def role_scopes(role: str) -> set[str]:
    return ROLE_SCOPES.get(role, set())


def require_scope(scope: str):
    async def dependency(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
        if not user.has_scope(scope):
            raise PermissionDeniedError(f"缺少权限: {scope}")
        return user

    return dependency


CurrentUserWithScope = Annotated[CurrentUser, Depends(get_current_user)]
