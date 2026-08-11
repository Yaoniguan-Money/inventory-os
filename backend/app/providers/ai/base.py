from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.core.errors import AppError


@dataclass
class ProviderCapability:
    supports_text: bool
    supports_vision: bool
    supports_tool_calling: bool
    supports_streaming: bool


class AIProvider(Protocol):
    name: str

    @property
    def capability(self) -> ProviderCapability: ...

    async def complete(
        self,
        *,
        system: str,
        user: str,
        tools_result: list[dict[str, Any]] | None = None,
    ) -> str: ...

    async def vision(
        self,
        *,
        system: str,
        prompt: str,
        image_data_url: str,
    ) -> str: ...


class DisabledAIProvider(AIProvider):
    """明确标记的禁用 Provider：配置错误时显式失败，不做 silent fallback。"""

    name = "disabled"

    def __init__(self, reason: str) -> None:
        self.reason = reason

    @property
    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            supports_text=False,
            supports_vision=False,
            supports_tool_calling=False,
            supports_streaming=False,
        )

    async def complete(
        self,
        *,
        system: str,
        user: str,
        tools_result: list[dict[str, Any]] | None = None,
    ) -> str:
        raise AppError(f"AI Provider 未启用：{self.reason}", details={"provider": "disabled"})

    async def vision(
        self,
        *,
        system: str,
        prompt: str,
        image_data_url: str,
    ) -> str:
        raise AppError(f"AI Provider 未启用：{self.reason}", details={"provider": "disabled"})
