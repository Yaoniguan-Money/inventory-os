from __future__ import annotations

from typing import Any

import httpx

from app.providers.ai.base import AIProvider, ProviderCapability


class OpenAICompatibleProvider(AIProvider):
    """通用 OpenAI-compatible chat completions Provider。"""

    name = "openai_compatible"

    def __init__(self, *, base_url: str, api_key: str, model: str) -> None:
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.api_key = api_key
        self.model = model or "gpt-4o-mini"

    @property
    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            supports_text=True,
            supports_vision="vision" in self.model.lower() or "gpt-4o" in self.model.lower(),
            supports_tool_calling=True,
            supports_streaming=True,
        )

    async def complete(
        self,
        *,
        system: str,
        user: str,
        tools_result: list[dict[str, Any]] | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.2,
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    async def vision(
        self,
        *,
        system: str,
        prompt: str,
        image_data_url: str,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_data_url}},
                    ],
                },
            ],
        }
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
