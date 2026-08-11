from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EquipmentCreate(BaseModel):
    asset_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=200)
    model: str | None = None
    serial_number: str | None = None
    manufacturer: str | None = None
    location: str | None = None
    production_line: str | None = None
    status: str = Field(default="OPERATIONAL", max_length=24)
    commissioned_at: datetime | None = None


class EquipmentUpdate(BaseModel):
    name: str | None = None
    model: str | None = None
    serial_number: str | None = None
    manufacturer: str | None = None
    location: str | None = None
    production_line: str | None = None
    status: str | None = None
    next_maintenance_at: datetime | None = None


class EquipmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    asset_code: str
    name: str
    model: str | None
    serial_number: str | None
    manufacturer: str | None
    location: str | None
    production_line: str | None
    status: str
    commissioned_at: datetime | None
    last_maintenance_at: datetime | None
    next_maintenance_at: datetime | None


class InspectionCreate(BaseModel):
    inspection_type: str = Field(min_length=1, max_length=40)
    result: str = Field(default="PASS", max_length=24)
    measurements_json: dict[str, Any] | None = None
    notes: str | None = None
    inspected_at: datetime | None = None
    inspected_by: str | None = None


class InspectionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    equipment_id: uuid.UUID
    inspection_type: str
    result: str
    measurements_json: dict[str, Any] | None
    notes: str | None
    inspected_at: datetime
    inspected_by: str | None


class FaultCreate(BaseModel):
    fault_code: str | None = None
    symptom: str = Field(min_length=1)
    severity: str = Field(default="MEDIUM", max_length=16)
    occurred_at: datetime | None = None
    reported_by: str | None = None


class FaultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    equipment_id: uuid.UUID
    fault_code: str | None
    symptom: str
    severity: str
    status: str
    occurred_at: datetime
    resolved_at: datetime | None
    reported_by: str | None


class MaintenancePartUse(BaseModel):
    product_id: uuid.UUID
    quantity: Decimal = Field(gt=0)


class MaintenanceCreate(BaseModel):
    fault_record_id: uuid.UUID | None = None
    maintenance_type: str = Field(min_length=1, max_length=40)
    description: str | None = None
    performed_at: datetime | None = None
    performed_by: str | None = None
    downtime_minutes: int | None = Field(default=None, ge=0)
    result: str = Field(default="COMPLETED", max_length=24)
    parts: list[MaintenancePartUse] = Field(default_factory=list)


class MaintenanceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    equipment_id: uuid.UUID
    fault_record_id: uuid.UUID | None
    maintenance_type: str
    description: str | None
    performed_at: datetime
    performed_by: str | None
    downtime_minutes: int | None
    result: str


class MaintenancePartUsageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    maintenance_record_id: uuid.UUID
    product_id: uuid.UUID
    quantity: Decimal
    stock_movement_id: uuid.UUID | None


class DiagnoseRequest(BaseModel):
    fault_code: str | None = None
    symptom: str = Field(min_length=1)


class DiagnoseCitation(BaseModel):
    source_type: str
    title: str
    excerpt: str


class DiagnoseResult(BaseModel):
    possible_causes: list[str]
    recommended_steps: list[str]
    citations: list[DiagnoseCitation]
    disclaimer: str = "以上为辅助判断，不构成设备控制指令，请由持证人员核实后操作。"
