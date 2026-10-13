"""
图生成数据模型 —— S1-S5 全链路类型定义

原则：
- Step 边界处的输出类型与下一级输入类型必须严格对齐
- 禁止核心字段类型漂移
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Any, List, Optional
from enum import Enum, auto


class PipelineStage(Enum):
    """流程阶段枚举 —— 禁止字符串漂移"""
    S0_ANALYSIS = auto()
    S1_STRATEGY = auto()
    S2_SKETCH = auto()
    S3_DIRECTION = auto()
    S4_FORMAL = auto()
    S5_FINAL = auto()


@dataclass
class DiagramVariant:
    """布局变体定义 —— 与 candidate_variants.py 严格对齐"""
    id: str
    identity: str
    layout: str
    color: str
    style: str

    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "DiagramVariant":
        if not isinstance(data, dict):
            raise ValueError(f"DiagramVariant.from_dict expects dict, got {type(data).__name__}")
        return cls(
            id=str(data.get("id", "")),
            identity=str(data.get("identity", "")),
            layout=str(data.get("layout", "")),
            color=str(data.get("color", "")),
            style=str(data.get("style", "")),
        )


@dataclass
class DiagramPrompt:
    """结构化提示词 —— S1/S4 输出"""
    candidate_id: str
    prompt_text: str
    variant: DiagramVariant
    target_image_path: Path
    prompt_path: Path
    stage: PipelineStage


@dataclass
class DiagramResult:
    """
    单张图生成结果 —— S5 最终输出

    字段命名与 paper2diagram 生成结果一致，禁止别名/冗余字段
    """
    candidate_id: str
    image_path: Path
    prompt: DiagramPrompt
    generated: bool
    size_kb: float = 0.0
    error: Optional[str] = None
    stage: PipelineStage = PipelineStage.S5_FINAL
