"""AI providers (replaceable; demo mode works without any API key)."""

from __future__ import annotations

from app.core.config import settings
from app.providers.ai.base import AIProvider, DisabledAIProvider
from app.providers.ai.demo import DemoAIProvider
from app.providers.ai.openai_compatible import OpenAICompatibleProvider


def get_ai_provider() -> AIProvider:
    provider_name = (settings.ai_provider or "demo").lower()
    if provider_name in ("openai", "openai_compatible") and settings.ai_api_key:
        return OpenAICompatibleProvider(
            base_url=settings.ai_base_url,
            api_key=settings.ai_api_key,
            model=settings.ai_model,
        )
    if provider_name in ("openai", "openai_compatible"):
        return DisabledAIProvider(reason="AI_PROVIDER=openai 但未配置 AI_API_KEY")
    if provider_name == "demo":
        return DemoAIProvider()
    raise ValueError(
        f"未知 AI Provider: {provider_name}（可选: demo, openai/openai_compatible）"
    )


__all__ = [
    "get_ai_provider",
    "AIProvider",
    "DemoAIProvider",
    "DisabledAIProvider",
    "OpenAICompatibleProvider",
]
