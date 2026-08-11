from __future__ import annotations

from typing import Any

from app.providers.ai.base import AIProvider, ProviderCapability


class DemoAIProvider(AIProvider):
    """
    明确标记的 Demo AI Provider：无 LLM、无外部调用，
    仅基于传入的证据做确定性摘要。系统在无 AI Key 时仍完整可运行。
    """

    name = "demo"

    @property
    def capability(self) -> ProviderCapability:
        return ProviderCapability(
            supports_text=True,
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
        lines: list[str] = []
        if tools_result:
            for item in tools_result:
                lines.append(f"- {item.get('label', '数据')}: {item.get('summary', item.get('value', ''))}")
        if not lines:
            lines.append("（Demo AI 模式：未提供可引用的业务证据，请连接真实 AI Provider 获取生成式回答。）")
        return "\n".join(lines)

    async def vision(
        self,
        *,
        system: str,
        prompt: str,
        image_data_url: str,
    ) -> str:
        return "Demo AI 模式不支持视觉识别；请使用条码或文字匹配，或配置支持视觉的 AI Provider。"
