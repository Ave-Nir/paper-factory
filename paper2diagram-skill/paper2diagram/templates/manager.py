"""
模板管理器 —— 管理布局模板，提供模板选择和配置加载功能

## 模板与布局变体的职责边界

本模块的 TemplateConfig 是**轻量级大结构方向提示器**，只划定布局的"骨架方向"，
不控制具体布局细节。具体布局、配色、风格由 candidate_variants.py 中的变体主导。

职责划分：
- **模板（TemplateConfig）提供大结构方向**：
  - layout: 布局大方向（horizontal / vertical / hybrid）
  - n_frames: 段数骨架（如 3 段、4 段）
  - arrow_style: 连线样式基调（如 orthogonal）
  - font_family / font_size_main: 排版基调
- **变体（candidate_variants）主导具体表现**：
  - layout 字段：具体布局描述（如"经典水平管线"、"中心压缩布局"）
  - color 字段：具体配色方案（含十六进制色值）
  - style 字段：具体视觉风格描述

这样设计的目的是：以变体为主保持生图自由度，避免过于严格的模板限制降低生图质量，
同时通过模板的 n_frames/layout/arrow_style 划定大结构方向，保证不偏离论文骨架。
"""
import yaml
from pathlib import Path
from typing import Dict, Optional
from dataclasses import dataclass


@dataclass
class TemplateConfig:
    """轻量级大结构方向配置，仅提供布局骨架提示，不控制具体布局细节"""
    id: str = ""
    name: str = ""
    description: str = ""
    layout: str = "horizontal"          # 布局大方向：horizontal / vertical / hybrid
    n_frames: int = 3                    # 段数骨架
    arrow_style: str = "orthogonal"      # 连线样式基调
    font_family: str = "Source Han Sans CN"
    font_size_main: int = 10


class TemplateManager:
    def __init__(self, template_dir: Optional[str] = None):
        self.template_dir = Path(template_dir) if template_dir else Path(__file__).parent / "configs"
        self.templates: Dict[str, TemplateConfig] = {}
        self._loaded = False

    def load_all(self) -> "TemplateManager":
        """加载所有模板配置"""
        if not self.template_dir.exists():
            self.template_dir.mkdir(parents=True, exist_ok=True)
            self._create_default_templates()

        self.templates.clear()
        for yaml_file in sorted(self.template_dir.glob("*.yaml")):
            try:
                data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
                if data:
                    cfg = self._parse_template(data)
                    self.templates[cfg.id] = cfg
            except Exception as e:
                print(f"[WARN] 加载模板 {yaml_file.name} 失败: {type(e).__name__}: {e}")
        self._loaded = True
        return self

    def _parse_template(self, data: Dict) -> TemplateConfig:
        """解析YAML配置为TemplateConfig（仅读取大结构方向字段）"""
        return TemplateConfig(
            id=data.get("id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            layout=data.get("layout", "horizontal"),
            n_frames=data.get("n_frames", 3),
            arrow_style=data.get("arrow_style", "orthogonal"),
            font_family=data.get("font_family", "Source Han Sans CN"),
            font_size_main=data.get("font_size_main", 10),
        )

    def _create_default_templates(self):
        """创建默认模板配置文件（仅含大结构方向字段）"""
        templates = [
            {
                "id": "horizontal_3frame",
                "name": "横向三段式",
                "description": "左→中→右三个独立大框，适用于技术流程、算法框图",
                "layout": "horizontal",
                "n_frames": 3,
                "arrow_style": "orthogonal",
                "font_family": "Source Han Sans CN",
                "font_size_main": 10,
            },
            {
                "id": "vertical_3stage",
                "name": "纵向三段式",
                "description": "上→中→下三个独立区域，适用于实验流程、方法论",
                "layout": "vertical",
                "n_frames": 3,
                "arrow_style": "orthogonal",
                "font_family": "Source Han Sans CN",
                "font_size_main": 10,
            },
            {
                "id": "hybrid_3x2",
                "name": "混合式3×2",
                "description": "顶部横向两段+底部纵向一段，适用于复杂机制分析",
                "layout": "hybrid",
                "n_frames": 3,
                "arrow_style": "orthogonal",
                "font_family": "Source Han Sans CN",
                "font_size_main": 10,
            },
            {
                "id": "complex_multi",
                "name": "复杂多阶段",
                "description": "四阶段或更多的复杂流程，适用于系统架构图",
                "layout": "horizontal",
                "n_frames": 4,
                "arrow_style": "orthogonal",
                "font_family": "Source Han Sans CN",
                "font_size_main": 10,
            },
        ]

        for tpl in templates:
            file_path = self.template_dir / f"{tpl['id']}.yaml"
            file_path.write_text(yaml.dump(tpl, allow_unicode=True), encoding="utf-8")

    def get(self, template_id: str) -> TemplateConfig:
        """按ID获取模板"""
        if not self._loaded:
            self.load_all()
        if template_id not in self.templates:
            raise KeyError(f"模板 '{template_id}' 不存在。可用模板: {list(self.templates.keys())}")
        return self.templates[template_id]

    def suggest(self, analysis: Dict) -> str:
        """根据论文分析结果自动推荐模板（基于阶段数选择骨架段数）"""
        if not self._loaded:
            self.load_all()

        template_type = analysis.get("template_type", "horizontal_3frame")
        if template_type in self.templates:
            return template_type

        n_stages = len(analysis.get("stages", []))
        if n_stages == 3:
            return "horizontal_3frame"
        elif n_stages == 4:
            return "complex_multi"
        else:
            return "horizontal_3frame"

    def list_all(self) -> Dict[str, str]:
        """列出所有模板"""
        if not self._loaded:
            self.load_all()
        return {t.id: t.name for t in self.templates.values()}
