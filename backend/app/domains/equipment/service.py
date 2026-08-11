from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import record_audit
from app.core.errors import NotFoundError
from app.core.events import record_event
from app.domains.equipment.models import (
    EquipmentAsset,
    EquipmentDocumentLink,
    FaultRecord,
    InspectionRecord,
    MaintenancePartUsage,
    MaintenanceRecord,
)
from app.domains.knowledge.models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    KnowledgeEntityLink,
)
from app.domains.warehouse.service import allocate_issue


async def get_equipment(
    db: AsyncSession, *, organization_id: str, equipment_id: str, for_update: bool = False
) -> EquipmentAsset:
    stmt = select(EquipmentAsset).where(
        EquipmentAsset.id == uuid.UUID(equipment_id),
        EquipmentAsset.organization_id == uuid.UUID(organization_id),
    )
    if for_update:
        stmt = stmt.with_for_update()
    equipment = (await db.execute(stmt)).scalar_one_or_none()
    if equipment is None:
        raise NotFoundError("设备不存在")
    return equipment


async def create_equipment(
    db: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    payload,
) -> EquipmentAsset:
    equipment = EquipmentAsset(
        organization_id=uuid.UUID(organization_id),
        **payload.model_dump(),
    )
    db.add(equipment)
    await db.flush()
    record_event(
        db,
        organization_id=organization_id,
        event_type="equipment.created",
        aggregate_type="equipment",
        aggregate_id=str(equipment.id),
        payload={"asset_code": equipment.asset_code, "name": equipment.name},
    )
    record_audit(
        db,
        organization_id=organization_id,
        actor_type="USER",
        actor_id=actor_id,
        action="equipment.create",
        entity_type="equipment",
        entity_id=str(equipment.id),
        after_json={"asset_code": equipment.asset_code},
    )
    return equipment


async def update_equipment(
    db: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    equipment_id: str,
    payload,
) -> EquipmentAsset:
    equipment = await get_equipment(
        db, organization_id=organization_id, equipment_id=equipment_id, for_update=True
    )
    before = {"status": equipment.status, "name": equipment.name}
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(equipment, field, value)
    await db.flush()
    record_audit(
        db,
        organization_id=organization_id,
        actor_type="USER",
        actor_id=actor_id,
        action="equipment.update",
        entity_type="equipment",
        entity_id=str(equipment.id),
        before_json=before,
        after_json={"status": equipment.status, "name": equipment.name},
    )
    return equipment


async def add_inspection(
    db: AsyncSession,
    *,
    organization_id: str,
    equipment_id: str,
    payload,
) -> InspectionRecord:
    equipment = await get_equipment(db, organization_id=organization_id, equipment_id=equipment_id)
    inspection = InspectionRecord(
        organization_id=uuid.UUID(organization_id),
        equipment_id=equipment.id,
        inspection_type=payload.inspection_type,
        result=payload.result,
        measurements_json=payload.measurements_json,
        notes=payload.notes,
        inspected_at=payload.inspected_at or datetime.now(UTC),
        inspected_by=payload.inspected_by,
    )
    db.add(inspection)
    await db.flush()
    record_event(
        db,
        organization_id=organization_id,
        event_type="equipment.inspected",
        aggregate_type="equipment",
        aggregate_id=str(equipment.id),
        payload={"inspection_type": inspection.inspection_type, "result": inspection.result},
    )
    return inspection


async def add_fault(
    db: AsyncSession,
    *,
    organization_id: str,
    equipment_id: str,
    payload,
) -> FaultRecord:
    equipment = await get_equipment(db, organization_id=organization_id, equipment_id=equipment_id)
    fault = FaultRecord(
        organization_id=uuid.UUID(organization_id),
        equipment_id=equipment.id,
        fault_code=payload.fault_code,
        symptom=payload.symptom,
        severity=payload.severity,
        status="OPEN",
        occurred_at=payload.occurred_at or datetime.now(UTC),
        reported_by=payload.reported_by,
    )
    db.add(fault)
    await db.flush()
    record_event(
        db,
        organization_id=organization_id,
        event_type="equipment.fault.reported",
        aggregate_type="equipment",
        aggregate_id=str(equipment.id),
        payload={"fault_id": str(fault.id), "fault_code": fault.fault_code, "severity": fault.severity},
    )
    return fault


async def add_maintenance(
    db: AsyncSession,
    *,
    organization_id: str,
    actor_id: str,
    equipment_id: str,
    payload,
) -> tuple[MaintenanceRecord, list[MaintenancePartUsage]]:
    equipment = await get_equipment(
        db, organization_id=organization_id, equipment_id=equipment_id, for_update=True
    )
    if payload.fault_record_id:
        fault = (
            await db.execute(
                select(FaultRecord).where(
                    FaultRecord.id == payload.fault_record_id,
                    FaultRecord.organization_id == uuid.UUID(organization_id),
                    FaultRecord.equipment_id == equipment.id,
                )
            )
        ).scalar_one_or_none()
        if fault is None:
            raise NotFoundError("故障记录不存在或不属于当前设备")
    maintenance = MaintenanceRecord(
        organization_id=uuid.UUID(organization_id),
        equipment_id=equipment.id,
        fault_record_id=payload.fault_record_id,
        maintenance_type=payload.maintenance_type,
        description=payload.description,
        performed_at=payload.performed_at or datetime.now(UTC),
        performed_by=payload.performed_by,
        downtime_minutes=payload.downtime_minutes,
        result=payload.result,
    )
    db.add(maintenance)
    await db.flush()
    usages: list[MaintenancePartUsage] = []
    for part in payload.parts:
        allocations = await allocate_issue(
            db,
            organization_id=organization_id,
            actor_id=actor_id,
            product_id=str(part.product_id),
            quantity=part.quantity,
            reason=f"设备维修领用 {equipment.asset_code}",
            reference_type="MAINTENANCE",
            reference_id=str(maintenance.id),
        )
        first_movement = allocations[0][1][0] if allocations and allocations[0][1] else None
        usage = MaintenancePartUsage(
            organization_id=uuid.UUID(organization_id),
            maintenance_record_id=maintenance.id,
            product_id=part.product_id,
            quantity=part.quantity,
            stock_movement_id=first_movement.id if first_movement else None,
        )
        db.add(usage)
        usages.append(usage)
    equipment.last_maintenance_at = maintenance.performed_at
    await db.flush()
    record_event(
        db,
        organization_id=organization_id,
        event_type="equipment.maintenance.completed",
        aggregate_type="equipment",
        aggregate_id=str(equipment.id),
        payload={
            "maintenance_id": str(maintenance.id),
            "maintenance_type": maintenance.maintenance_type,
            "parts": [str(p.product_id) for p in usages],
        },
    )
    return maintenance, usages


async def diagnose_equipment(
    db: AsyncSession,
    *,
    organization_id: str,
    user_role: str,
    equipment_id: str,
    symptom: str,
    fault_code: str | None,
) -> dict:
    equipment = await get_equipment(db, organization_id=organization_id, equipment_id=equipment_id)
    org_uuid = uuid.UUID(organization_id)
    # 收集知识来源：设备关联文档 + 实体链接文档
    doc_ids = set(
        (
            await db.execute(
                select(EquipmentDocumentLink.document_id).where(
                    EquipmentDocumentLink.organization_id == org_uuid,
                    EquipmentDocumentLink.equipment_id == equipment.id,
                )
            )
        ).scalars()
    )
    doc_ids.update(
        (
            await db.execute(
                select(KnowledgeEntityLink.document_id).where(
                    KnowledgeEntityLink.organization_id == org_uuid,
                    KnowledgeEntityLink.entity_type == "EQUIPMENT",
                    KnowledgeEntityLink.entity_id == equipment.id,
                )
            )
        ).scalars()
    )
    if user_role not in ("OWNER", "ADMIN"):
        owner_doc_ids = set(
            (
                await db.execute(
                    select(KnowledgeDocument.id).where(
                        KnowledgeDocument.organization_id == org_uuid,
                        KnowledgeDocument.id.in_(list(doc_ids)),
                        KnowledgeDocument.access_scope == "OWNER",
                    )
                )
            ).scalars()
        )
        doc_ids -= owner_doc_ids
    citations: list[dict] = []
    excerpts: list[str] = []
    if doc_ids:
        docs = (
            await db.execute(
                select(KnowledgeDocument).where(KnowledgeDocument.id.in_(list(doc_ids)))
            )
        ).scalars().all()
        doc_titles = {doc.id: doc.title for doc in docs}
        all_versions = (
            await db.execute(
                select(KnowledgeDocumentVersion)
                .where(KnowledgeDocumentVersion.document_id.in_(list(doc_ids)))
                .order_by(
                    KnowledgeDocumentVersion.document_id,
                    KnowledgeDocumentVersion.version.desc(),
                )
            )
        ).scalars().all()
        latest_by_doc: dict[uuid.UUID, KnowledgeDocumentVersion] = {}
        for version in all_versions:
            latest_by_doc.setdefault(version.document_id, version)
        version_ids = [version.id for version in latest_by_doc.values()]
        doc_by_version = {
            version.id: doc_titles.get(version.document_id, "文档")
            for version in latest_by_doc.values()
        }
        chunks = (
            await db.execute(
                select(KnowledgeChunk).where(KnowledgeChunk.document_version_id.in_(version_ids))
            )
        ).scalars().all()
        keywords = [symptom] + ([fault_code] if fault_code else [])
        for chunk in chunks:
            if any(kw and kw.lower() in chunk.content.lower() for kw in keywords if kw):
                doc_title = doc_by_version.get(chunk.document_version_id, "文档")
                citations.append(
                    {
                        "source_type": "knowledge",
                        "title": doc_title,
                        "excerpt": chunk.content[:200],
                    }
                )
                excerpts.append(chunk.content[:300])
    faults = (
        await db.execute(
            select(FaultRecord)
            .where(
                FaultRecord.organization_id == org_uuid,
                FaultRecord.equipment_id == equipment.id,
                FaultRecord.fault_code.is_not(None),
            )
            .order_by(FaultRecord.occurred_at.desc())
            .limit(5)
        )
    ).scalars().all()
    for fault in faults[:3]:
        citations.append(
            {
                "source_type": "history",
                "title": f"历史故障 {fault.fault_code or ''}",
                "excerpt": fault.symptom[:200],
            }
        )
    if not citations:
        citations.append(
            {
                "source_type": "manual",
                "title": "通用排查建议",
                "excerpt": "未检索到完全匹配的案例，请结合设备手册与现场现象排查。",
            }
        )
    cause_hint = f"错误码 {fault_code} 或现象「{symptom}」" if fault_code else f"现象「{symptom}」"
    possible_causes = [
        f"{cause_hint} 可能与传动/电气/气动子系统相关（待现场确认）",
        "部件磨损、传感器漂移或接线松动是常见原因",
    ]
    if excerpts:
        possible_causes.append("知识库存在相近案例，请优先核对引用片段中的检查项")
    recommended_steps = [
        "确认设备已断电/急停并挂牌，再开始检查",
        "核对设备面板错误码与说明书对应章节",
        "检查电源、气源、传感器与机械传动部位",
        "按引用文档执行逐项排查，并记录测量值",
    ]
    return {
        "possible_causes": possible_causes,
        "recommended_steps": recommended_steps,
        "citations": citations,
        "disclaimer": "以上为辅助判断，不构成设备控制指令，请由持证人员核实后操作。",
    }
