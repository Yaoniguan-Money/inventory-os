from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.permissions import require_scope
from app.core.security import CurrentUser
from app.domains.equipment.models import (
    EquipmentAsset,
    FaultRecord,
    InspectionRecord,
    MaintenanceRecord,
)
from app.domains.equipment.schemas import (
    DiagnoseRequest,
    DiagnoseResult,
    EquipmentCreate,
    EquipmentOut,
    EquipmentUpdate,
    FaultCreate,
    FaultOut,
    InspectionCreate,
    InspectionOut,
    MaintenanceCreate,
    MaintenanceOut,
    MaintenancePartUsageOut,
)
from app.domains.equipment.service import (
    add_fault,
    add_inspection,
    add_maintenance,
    create_equipment,
    diagnose_equipment,
    get_equipment,
    update_equipment,
)

router = APIRouter(tags=["equipment"])


@router.get("/equipment", response_model=list[EquipmentOut])
async def list_equipment(
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("equipment:read")),
) -> list[EquipmentOut]:
    rows = (
        await db.execute(
            select(EquipmentAsset)
            .where(EquipmentAsset.organization_id == uuid.UUID(user.organization_id))
            .order_by(EquipmentAsset.asset_code)
        )
    ).scalars().all()
    return [EquipmentOut.model_validate(row) for row in rows]


@router.post("/equipment", response_model=EquipmentOut, status_code=201)
async def create_equipment_route(
    payload: EquipmentCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("equipment:write")),
) -> EquipmentOut:
    equipment = await create_equipment(
        db, organization_id=user.organization_id, actor_id=user.user_id, payload=payload
    )
    await db.commit()
    return EquipmentOut.model_validate(equipment)


@router.get("/equipment/{equipment_id}", response_model=EquipmentOut)
async def get_equipment_route(
    equipment_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("equipment:read")),
) -> EquipmentOut:
    equipment = await get_equipment(
        db, organization_id=user.organization_id, equipment_id=equipment_id
    )
    return EquipmentOut.model_validate(equipment)


@router.patch("/equipment/{equipment_id}", response_model=EquipmentOut)
async def update_equipment_route(
    equipment_id: str,
    payload: EquipmentUpdate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("equipment:write")),
) -> EquipmentOut:
    equipment = await update_equipment(
        db,
        organization_id=user.organization_id,
        actor_id=user.user_id,
        equipment_id=equipment_id,
        payload=payload,
    )
    await db.commit()
    return EquipmentOut.model_validate(equipment)


@router.get("/equipment/{equipment_id}/inspections", response_model=list[InspectionOut])
async def list_inspections(
    equipment_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("equipment:read")),
) -> list[InspectionOut]:
    await get_equipment(db, organization_id=user.organization_id, equipment_id=equipment_id)
    rows = (
        await db.execute(
            select(InspectionRecord)
            .where(InspectionRecord.equipment_id == uuid.UUID(equipment_id))
            .order_by(InspectionRecord.inspected_at.desc())
        )
    ).scalars().all()
    return [InspectionOut.model_validate(row) for row in rows]


@router.post(
    "/equipment/{equipment_id}/inspections", response_model=InspectionOut, status_code=201
)
async def create_inspection(
    equipment_id: str,
    payload: InspectionCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("equipment:write")),
) -> InspectionOut:
    inspection = await add_inspection(
        db, organization_id=user.organization_id, equipment_id=equipment_id, payload=payload
    )
    await db.commit()
    return InspectionOut.model_validate(inspection)


@router.get("/equipment/{equipment_id}/faults", response_model=list[FaultOut])
async def list_faults(
    equipment_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("equipment:read")),
) -> list[FaultOut]:
    await get_equipment(db, organization_id=user.organization_id, equipment_id=equipment_id)
    rows = (
        await db.execute(
            select(FaultRecord)
            .where(FaultRecord.equipment_id == uuid.UUID(equipment_id))
            .order_by(FaultRecord.occurred_at.desc())
        )
    ).scalars().all()
    return [FaultOut.model_validate(row) for row in rows]


@router.post("/equipment/{equipment_id}/faults", response_model=FaultOut, status_code=201)
async def create_fault(
    equipment_id: str,
    payload: FaultCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("equipment:write")),
) -> FaultOut:
    fault = await add_fault(
        db, organization_id=user.organization_id, equipment_id=equipment_id, payload=payload
    )
    await db.commit()
    return FaultOut.model_validate(fault)


@router.get("/equipment/{equipment_id}/maintenance", response_model=list[MaintenanceOut])
async def list_maintenance(
    equipment_id: str,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("equipment:read")),
) -> list[MaintenanceOut]:
    await get_equipment(db, organization_id=user.organization_id, equipment_id=equipment_id)
    rows = (
        await db.execute(
            select(MaintenanceRecord)
            .where(MaintenanceRecord.equipment_id == uuid.UUID(equipment_id))
            .order_by(MaintenanceRecord.performed_at.desc())
        )
    ).scalars().all()
    return [MaintenanceOut.model_validate(row) for row in rows]


@router.post(
    "/equipment/{equipment_id}/maintenance",
    response_model=dict,
    status_code=201,
)
async def create_maintenance(
    equipment_id: str,
    payload: MaintenanceCreate,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("equipment:write")),
) -> dict:
    maintenance, usages = await add_maintenance(
        db,
        organization_id=user.organization_id,
        actor_id=user.user_id,
        equipment_id=equipment_id,
        payload=payload,
    )
    await db.commit()
    return {
        "maintenance": MaintenanceOut.model_validate(maintenance).model_dump(),
        "parts": [MaintenancePartUsageOut.model_validate(u).model_dump() for u in usages],
    }


@router.post("/equipment/{equipment_id}/diagnose", response_model=DiagnoseResult)
async def diagnose(
    equipment_id: str,
    payload: DiagnoseRequest,
    db: AsyncSession = Depends(get_db),
    user: CurrentUser = Depends(require_scope("equipment:read")),
) -> DiagnoseResult:
    result = await diagnose_equipment(
        db,
        organization_id=user.organization_id,
        equipment_id=equipment_id,
        symptom=payload.symptom,
        fault_code=payload.fault_code,
    )
    await db.commit()
    return DiagnoseResult.model_validate(result)
