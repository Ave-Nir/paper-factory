"""
LLM 工厂 —— 统一从 api_config 创建 LLM 客户端。

安全原则：
- API Key 从统一配置中心（api_config.py）读取
- 支持 DeepSeek（默认）和 OpenAI 兼容后端
- 通过 base_url 切换不同 provider
- 任何调用方都不应直接构造 OpenAILLM，统一通过 create_llm_from_env() 获取

使用：
    from core.llm_factory import create_llm_from_env

    llm = create_llm_from_env()  # 从 api_config 读取
    response = llm(system_prompt, user_prompt)

配置来源：
    api_config.py（统一配置中心）
    环境变量：LLM_API_KEY、LLM_BASE_URL、LLM_MODEL
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional

# 确保项目根目录在path中
_project_root = str(Path(__file__).resolve().parents[2])  # paper-factory 根目录
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# 从统一配置中心导入API配置
from api_config import LLM_API

from .nl_intake import OpenAILLM, LLMResponse, LLMCallable


# ============================================================
# 默认配置（按用户当前选择）
# ============================================================
DEFAULT_PROVIDER = "deepseek"
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


class LLMConfigError(RuntimeError):
    """未找到 API key 或配置不合法时抛出。"""


def _resolve_api_key(provider: str) -> str:
    """按 provider 解析 API key，从统一配置中心读取。"""
    if provider == "deepseek":
        key = LLM_API.api_key
    elif provider == "openai":
        key = os.environ.get("OPENAI_API_KEY", "").strip()
    else:
        raise LLMConfigError(f"Unknown LLM provider: {provider}")

    if not key:
        raise LLMConfigError(
            f"未找到 {provider.upper()} 的 API key。\n"
            f"请设置环境变量 {provider.upper()}_API_KEY 后重试。\n"
            f"注意：不要把密钥写入代码或配置文件。"
        )
    return key


def _resolve_provider(explicit: Optional[str] = None) -> str:
    """按以下顺序解析 provider：显式参数 > LLM_PROVIDER 环境变量 > 默认 deepseek。"""
    if explicit:
        return explicit.strip().lower()
    env = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if env:
        return env
    return DEFAULT_PROVIDER


def create_llm_from_env(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
) -> LLMCallable:
    """从统一配置中心创建 LLM 客户端。

    Args:
        provider: 强制指定 provider（deepseek / openai），None 时按 LLM_PROVIDER 推断
        model:    强制指定模型名，None 时使用 provider 的默认模型
        base_url: 强制指定 base url，None 时使用 provider 的默认 base url

    Returns:
        可调用对象 (system_prompt, user_prompt) -> LLMResponse
    """
    provider = _resolve_provider(provider)

    if provider == "deepseek":
        api_key = _resolve_api_key("deepseek")
        resolved_base_url = base_url or LLM_API.base_url
        resolved_model = model or LLM_API.model
    elif provider == "openai":
        api_key = _resolve_api_key("openai")
        resolved_base_url = (
            base_url
            or os.environ.get("OPENAI_BASE_URL", "").strip()
            or DEFAULT_OPENAI_BASE_URL
        )
        resolved_model = (
            model
            or os.environ.get("OPENAI_MODEL", "").strip()
            or DEFAULT_OPENAI_MODEL
        )
    else:
        raise LLMConfigError(
            f"Unsupported provider: {provider} (supported: deepseek, openai)"
        )

    return OpenAILLM(
        api_key=api_key,
        base_url=resolved_base_url,
        model=resolved_model,
    )


def describe_config() -> dict:
    """返回当前 LLM 配置的描述（不包含密钥本身），用于日志/调试。"""
    provider = _resolve_provider()
    if provider == "deepseek":
        has_key = bool(LLM_API.api_key)
        base_url = LLM_API.base_url
        model = LLM_API.model
    else:
        has_key = bool(os.environ.get("OPENAI_API_KEY", "").strip())
        base_url = (
            os.environ.get("OPENAI_BASE_URL", "").strip()
            or DEFAULT_OPENAI_BASE_URL
        )
        model = (
            os.environ.get("OPENAI_MODEL", "").strip()
            or DEFAULT_OPENAI_MODEL
        )
    return {
        "provider": provider,
        "model": model,
        "base_url": base_url,
        "has_api_key": has_key,
    }
