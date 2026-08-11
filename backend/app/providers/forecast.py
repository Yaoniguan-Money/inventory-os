from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol


@dataclass
class ForecastCapability:
    enabled: bool
    provider: str
    types: list[str]


class ForecastProvider(Protocol):
    """V1 只保留契约与扩展位，不实现预测模型。"""

    async def forecast_price(self, subject_id: str, horizon: str, **kwargs: Any) -> dict: ...

    async def forecast_demand(self, subject_id: str, horizon: str, **kwargs: Any) -> dict: ...

    async def forecast_supply_risk(self, subject_id: str, horizon: str, **kwargs: Any) -> dict: ...

    async def capability(self) -> ForecastCapability: ...


class DisabledForecastProvider(ForecastProvider):
    """默认实现：capability 明确 disabled，不生成任何伪造预测。"""

    async def capability(self) -> ForecastCapability:
        return ForecastCapability(enabled=False, provider="disabled", types=["price", "demand", "supply_risk"])

    async def forecast_price(self, subject_id: str, horizon: str, **kwargs: Any) -> dict:
        return self._disabled("price", subject_id, horizon)

    async def forecast_demand(self, subject_id: str, horizon: str, **kwargs: Any) -> dict:
        return self._disabled("demand", subject_id, horizon)

    async def forecast_supply_risk(self, subject_id: str, horizon: str, **kwargs: Any) -> dict:
        return self._disabled("supply_risk", subject_id, horizon)

    def _disabled(self, forecast_type: str, subject_id: str, horizon: str) -> dict:
        return {
            "forecast_type": forecast_type,
            "subject_id": subject_id,
            "horizon": horizon,
            "points": [],
            "confidence": None,
            "model": None,
            "evidence": [],
            "generated_at": datetime.now(UTC).isoformat(),
            "enabled": False,
            "message": "V1 未启用预测模型，不生成预测数据。",
        }
