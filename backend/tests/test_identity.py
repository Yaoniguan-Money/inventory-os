from __future__ import annotations

import httpx
from sqlalchemy import select

from app.core.database import new_session
from app.core.security import create_access_token
from app.domains.identity.models import ApiKey, User


async def test_login_and_me(client: httpx.AsyncClient, org_owner_headers: dict[str, str]) -> None:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "Owner@12345"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["token_type"] == "bearer"
    assert data["role"] == "OWNER"
    assert data["user"]["email"] == "owner@example.com"

    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {data['access_token']}"})
    assert me.status_code == 200
    me_data = me.json()
    assert me_data["organization"]["slug"] == "test-org"
    assert "products:read" in me_data["scopes"]


async def test_login_rejects_wrong_password(client: httpx.AsyncClient, org_owner_headers: dict[str, str]) -> None:
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "owner@example.com", "password": "wrong-password"},
    )
    assert resp.status_code == 401


async def test_me_requires_token(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


async def test_cross_org_users_isolated(
    client: httpx.AsyncClient,
    org_owner_headers: dict[str, str],
    second_org_headers: dict[str, str],
) -> None:
    # Owner of org1 creates a user in org1.
    created = await client.post(
        "/api/v1/users",
        headers=org_owner_headers,
        json={
            "email": "member1@example.com",
            "password": "Member@12345",
            "display_name": "成员一",
            "role": "MANAGER",
        },
    )
    assert created.status_code == 201

    # Org2 owner sees only org2 members.
    list_org1 = await client.get("/api/v1/users", headers=org_owner_headers)
    assert list_org1.status_code == 200
    assert {u["user"]["email"] for u in list_org1.json()} == {"owner@example.com", "member1@example.com"}

    list_org2 = await client.get("/api/v1/users", headers=second_org_headers)
    assert list_org2.status_code == 200
    assert {u["user"]["email"] for u in list_org2.json()} == {"owner2@example.com"}


async def test_rbac_forbids_viewer(
    client: httpx.AsyncClient,
    org_owner_headers: dict[str, str],
) -> None:
    created = await client.post(
        "/api/v1/users",
        headers=org_owner_headers,
        json={
            "email": "viewer@example.com",
            "password": "Viewer@12345",
            "display_name": "只读用户",
            "role": "VIEWER",
        },
    )
    assert created.status_code == 201

    async with new_session() as db:
        user = (
            await db.execute(select(User).where(User.email == "viewer@example.com"))
        ).scalar_one()
        viewer_token = create_access_token(str(user.id))

    resp = await client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {viewer_token}"},
        json={
            "email": "nope@example.com",
            "password": "Nope@12345",
            "display_name": "无权限",
            "role": "VIEWER",
        },
    )
    assert resp.status_code == 403


async def test_api_key_lifecycle(
    client: httpx.AsyncClient,
    org_owner_headers: dict[str, str],
) -> None:
    created = await client.post(
        "/api/v1/integrations/api-keys",
        headers=org_owner_headers,
        json={"name": "erp-bridge", "scopes": ["inventory:receive"]},
    )
    assert created.status_code == 201
    data = created.json()
    assert data["api_key"].startswith(data["prefix"] + ".")

    # Plaintext secret must not be persisted.
    async with new_session() as db:
        stored = await db.get(ApiKey, data["id"])
        assert stored is not None
        assert stored.key_hash != data["api_key"]
        assert ApiKey.hash_secret(data["api_key"].split(".", 1)[1]) == stored.key_hash

    listing = await client.get("/api/v1/integrations/api-keys", headers=org_owner_headers)
    assert listing.status_code == 200
    assert listing.json()[0]["name"] == "erp-bridge"
    assert "api_key" not in listing.json()[0]

    revoked = await client.delete(f"/api/v1/integrations/api-keys/{data['id']}", headers=org_owner_headers)
    assert revoked.status_code == 200
