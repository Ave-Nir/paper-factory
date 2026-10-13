# -*- coding: utf-8 -*-
"""
统一 API 配置中心 —— 全项目 API 密钥与端点的唯一配置源。

设计原则：
- 所有 API 配置集中在此文件管理，业务模块只从这里导入，不各自读环境变量
- 密钥一律通过环境变量或本地 .env 提供，**绝不写入代码或提交到 git**
- 默认值仅为公开可用的端点占位，真实密钥必须由使用者自行配置

配置优先级（高 → 低）：
    1. 进程环境变量
    2. 项目根目录下的 .env 文件

使用方式：
    from api_config import LLM_API, IMAGE_API

    api_key  = LLM_API.api_key     # 密钥
    base_url = LLM_API.base_url    # 端点
    model    = LLM_API.model       # 模型名
"""

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv() -> None:
    """从项目根目录的 .env 加载环境变量（仅在变量尚未存在时填充）。"""
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key, value = key.strip(), value.strip()
            if key and key not in os.environ:
                os.environ[key] = value


_load_dotenv()


@dataclass(frozen=True)
class ApiEndpoint:
    """单个 API 端点的配置。"""

    api_key: str
    base_url: str
    model: str
    timeout: int = 120
    max_retries: int = 3


def _get_env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _get_env_int(key: str, default: int = 0) -> int:
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


# ============================================================
# LLM API（论文分析 / 自然语言接管）
# ============================================================
LLM_API = ApiEndpoint(
    api_key=_get_env("LLM_API_KEY", ""),
    base_url=_get_env("LLM_BASE_URL", "https://api.deepseek.com/v1"),
    model=_get_env("LLM_MODEL", "deepseek-chat"),
    timeout=_get_env_int("LLM_TIMEOUT", 120),
    max_retries=_get_env_int("LLM_MAX_RETRIES", 3),
)

# ============================================================
# 图片生成 API（学术流程图渲染）
# ============================================================
IMAGE_API = ApiEndpoint(
    api_key=_get_env("IMAGE_API_KEY", ""),
    base_url=_get_env("IMAGE_BASE_URL", "https://api.openai.com/v1"),
    model=_get_env("IMAGE_MODEL", "gpt-image-2"),
    timeout=_get_env_int("IMAGE_TIMEOUT", 300),
    max_retries=_get_env_int("IMAGE_MAX_RETRIES", 3),
)


def get_llm_config() -> dict:
    """返回 LLM 配置字典（兼容旧接口）。"""
    return {
        "enabled": bool(LLM_API.api_key),
        "endpoint": f"{LLM_API.base_url}/chat/completions",
        "api_key": LLM_API.api_key,
        "model": LLM_API.model,
        "timeout": LLM_API.timeout,
        "max_retries": LLM_API.max_retries,
        "temperature": 0.7,
        "max_tokens": 4096,
    }


def get_image_config() -> dict:
    """返回图片生成配置字典。"""
    return {
        "api_key": IMAGE_API.api_key,
        "base_url": IMAGE_API.base_url,
        "model": IMAGE_API.model,
        "timeout": IMAGE_API.timeout,
        "max_retries": IMAGE_API.max_retries,
    }


def validate_config() -> list:
    """校验配置完整性，返回缺失项列表。"""
    missing = []
    if not LLM_API.api_key:
        missing.append("LLM_API_KEY")
    if not IMAGE_API.api_key:
        missing.append("IMAGE_API_KEY")
    return missing


if __name__ == "__main__":
    print("=== LLM API 配置 ===")
    print(f"  API Key : {'已设置' if LLM_API.api_key else '未设置'}")
    print(f"  Base URL: {LLM_API.base_url}")
    print(f"  Model   : {LLM_API.model}")
    print("\n=== 图片 API 配置 ===")
    print(f"  API Key : {'已设置' if IMAGE_API.api_key else '未设置'}")
    print(f"  Base URL: {IMAGE_API.base_url}")
    print(f"  Model   : {IMAGE_API.model}")

    missing = validate_config()
    print(f"\n缺失配置: {', '.join(missing)}" if missing else "\n配置完整")