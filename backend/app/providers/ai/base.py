from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


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
