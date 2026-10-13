"""
论文分析数据模型 —— S0 阶段输出类型定义

原则：
- 所有字段类型明确，禁止隐式类型转换
- LLM 输出反序列化必须带异常捕获与兜底校验
- 同一业务字段全链路命名、类型、结构完全统一
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class PaperStage:
    """论文阶段/模块"""
    name: str
    description: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PaperStage":
        if not isinstance(data, dict):
            raise ValueError(f"PaperStage.from_dict expects dict, got {type(data).__name__}")
        return cls(
            name=str(data.get("name", "")),
            description=str(data.get("description", "")),
        )


@dataclass
class PaperModule:
    """论文模块"""
    name: str
    description: str = ""
    inputs: List[str] = field(default_factory=list)
    outputs: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PaperModule":
        if not isinstance(data, dict):
            raise ValueError(f"PaperModule.from_dict expects dict, got {type(data).__name__}")
        return cls(
            name=str(data.get("name", "")),
            description=str(data.get("description", "")),
            inputs=[str(x) for x in data.get("inputs", []) if x is not None],
            outputs=[str(x) for x in data.get("outputs", []) if x is not None],
        )


@dataclass
class PaperConnection:
    """模块连接关系"""
    source: str
    target: str
    label: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PaperConnection":
        if not isinstance(data, dict):
            raise ValueError(f"PaperConnection.from_dict expects dict, got {type(data).__name__}")
        return cls(
            source=str(data.get("source", "")),
            target=str(data.get("target", "")),
            label=str(data.get("label", "")),
        )


@dataclass
class PaperAnalysis:
    """
    S0 论文基础分析结果 —— 全链路统一类型

    字段与 paper2diagram PaperAnalyzer.analyze_paper() 输出严格对齐：
      - title: str
      - stages: List[Dict] -> 转换为 List[PaperStage]
      - modules: List[Dict] -> 转换为 List[PaperModule]
      - connections: List[Dict] -> 转换为 List[PaperConnection]
    """
    title: str = ""
    stages: List[PaperStage] = field(default_factory=list)
    modules: List[PaperModule] = field(default_factory=list)
    connections: List[PaperConnection] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_raw(cls, raw: Dict[str, Any]) -> "PaperAnalysis":
        """
        从原始 LLM 输出构建类型安全的 PaperAnalysis

        禁止裸解析：所有字段必须经过类型校验与兜底处理
        """
        if not isinstance(raw, dict):
            raise ValueError(f"PaperAnalysis.from_raw expects dict, got {type(raw).__name__}")

        stages_raw = raw.get("stages", [])
        modules_raw = raw.get("modules", [])
        connections_raw = raw.get("connections", [])

        return cls(
            title=str(raw.get("title", "")),
            stages=[PaperStage.from_dict(s) for s in stages_raw if isinstance(s, dict)],
            modules=[PaperModule.from_dict(m) for m in modules_raw if isinstance(m, dict)],
            connections=[PaperConnection.from_dict(c) for c in connections_raw if isinstance(c, dict)],
            raw=raw,
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换回 dict，用于传递给下游 paper2diagram 组件"""
        return {
            "title": self.title,
            "stages": [{"name": s.name, "description": s.description} for s in self.stages],
            "modules": [{"name": m.name, "description": m.description} for m in self.modules],
            "connections": [{"source": c.source, "target": c.target, "label": c.label} for c in self.connections],
        }
