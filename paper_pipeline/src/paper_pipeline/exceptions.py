"""
统一异常体系 —— 所有异常必须携带完整上下文信息

原则：
- 禁止裸抛通用 Exception
- 禁止静默吞错
- 所有异常必须纳入统一异常处理体系
"""
from typing import Optional, Dict, Any


class PipelineError(Exception):
    """流程基异常 —— 所有自定义异常的根"""

    def __init__(
        self,
        message: str,
        stage: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None,
    ):
        super().__init__(message)
        self.message = message
        self.stage = stage
        self.context = context or {}
        self.cause = cause

    def __str__(self) -> str:
        parts = [f"[{self.stage}] {self.message}" if self.stage else self.message]
        if self.context:
            ctx = ", ".join(f"{k}={v}" for k, v in self.context.items())
            parts.append(f"context={{{ctx}}}")
        if self.cause:
            parts.append(f"caused_by={type(self.cause).__name__}: {self.cause}")
        return " | ".join(parts)


class ConfigurationError(PipelineError):
    """配置异常 —— 环境变量缺失、配置文件格式错误等"""
    pass


class ValidationError(PipelineError):
    """校验异常 —— Gate 检查失败、输入不符合要求"""
    pass


class DiagramGenerationError(PipelineError):
    """生图异常 —— S0-S5 任意阶段失败"""
    pass


class TypesetError(PipelineError):
    """排版异常 —— PDF/TEX 编译失败"""
    pass


class InsertionError(PipelineError):
    """插入异常 —— 图片插入 docx 失败"""
    pass


class LLMError(PipelineError):
    """LLM 调用异常 —— API 错误、解析失败、超时"""
    pass
