"""AI providers (replaceable; demo mode works without any API key)."""

from __future__ import annotations

from app.core.config import settings
from app.providers.ai.base import AIProvider
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
    return DemoAIProvider()


__all__ = ["get_ai_provider", "AIProvider", "DemoAIProvider", "OpenAICompatibleProvider"]
