"""
模板引擎 —— 加载和管理不同会议/期刊的 LaTeX 模板。

设计原则：
- BaseTemplate ABC 定义所有模板必须实现的接口
- 每个 venue 模板通过子类实现，配置可来自 YAML 文件
- TemplateRegistry 管理所有已注册模板
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
import yaml
import os


# ============================================================================
# 模板配置类型
# ============================================================================

@dataclass
class PackageSpec:
    """LaTeX 包规格"""
    name: str
    options: list[str] = field(default_factory=list)


@dataclass
class ResolvedTemplate:
    """解析后的完整模板参数"""
    # 文档类
    document_class: str
    class_options: list[str]
    
    # 包
    packages: list[PackageSpec]
    
    # 结构
    section_order: list[str]  # 章节名称及顺序
    
    # 格式
    citation_style: str       # "numeric", "author-year", "alphabetic"
    bibliography_style: str   # "plainnat", "ieeetr", "unsrt", "gbt7714-nsfc", etc.
    page_limit: int
    column_layout: str        # "single", "double"
    font_size: str            # "10pt", "11pt", "12pt"
    
    # 图表
    figure_placement_default: str
    table_placement_default: str
    
    # 标题页
    title_page_template: str  # Jinja2 模板路径
    anonymous: bool            # 是否为匿名审稿格式
    
    # 中文字体 & 引擎
    engine: str = "pdflatex"  # "pdflatex" / "xelatex"
    language: str = "english" # "english" / "chinese"（决定 xeCJK / ctex 包）
    
    # 额外
    extra_preamble: str = ""   # 额外的 preamble 内容


# ============================================================================
# 抽象基类
# ============================================================================

class BaseTemplate(ABC):
    """所有 venue 模板的基类"""
    
    venue_key: str = ""
    venue_name: str = ""
    venue_year: str = ""
    
    @abstractmethod
    def get_config(self) -> ResolvedTemplate:
        """返回该 venue 的完整 LaTeX 配置"""
        ...
    
    @abstractmethod
    def get_default_section_composers(self) -> dict[str, str]:
        """
        返回 section_name → composer_class_name 的映射。
        如 {"introduction": "IntroductionComposer", "method": "MethodComposer"}
        """
        ...
    
    def render_preamble(self) -> str:
        """生成 LaTeX preamble（\documentclass 到 \begin{document}）"""
        cfg = self.get_config()
        lines = []
        
        # 文档类
        opts = ",".join(cfg.class_options)
        lines.append(f"\\documentclass[{opts}]{{{cfg.document_class}}}")
        
        # 包
        for pkg in cfg.packages:
            if pkg.options:
                opts = ",".join(pkg.options)
                lines.append(f"\\usepackage[{opts}]{{{pkg.name}}}")
            else:
                lines.append(f"\\usepackage{{{pkg.name}}}")
        
        # 额外 preamble
        if cfg.extra_preamble:
            lines.append(cfg.extra_preamble)
        
        # 引用设置
        if cfg.citation_style == "numeric":
            lines.append("\\bibliographystyle{" + cfg.bibliography_style + "}")
        
        lines.append("\\begin{document}")
        return "\n".join(lines)
    
    def render_end(self) -> str:
        """生成 LaTeX 尾部（bibliography + \end{document}）"""
        return "\\bibliography{references}\n\\end{document}"
    
    def validate_config(self) -> tuple[bool, list[str]]:
        """验证模板配置的合法性"""
        errors = []
        cfg = self.get_config()
        
        if not cfg.document_class:
            errors.append("document_class is empty")
        if not cfg.section_order:
            errors.append("section_order is empty")
        if cfg.page_limit <= 0:
            errors.append(f"invalid page_limit: {cfg.page_limit}")
        
        return len(errors) == 0, errors


# ============================================================================
# 模板注册表
# ============================================================================

class TemplateRegistry:
    """管理所有已注册的 venue 模板"""
    
    _templates: dict[str, type[BaseTemplate]] = {}
    
    @classmethod
    def register(cls, template_cls: type[BaseTemplate]) -> type[BaseTemplate]:
        key = template_cls.venue_key
        cls._templates[key] = template_cls
        return template_cls
    
    @classmethod
    def get(cls, venue_key: str) -> BaseTemplate:
        if venue_key not in cls._templates:
            raise ValueError(
                f"Unknown venue '{venue_key}'. "
                f"Available: {list(cls._templates.keys())}"
            )
        return cls._templates[venue_key]()
    
    @classmethod
    def list_venues(cls) -> list[str]:
        return list(cls._templates.keys())
    
    @classmethod
    def load_from_yaml(cls, yaml_path: str) -> None:
        """从 YAML 配置文件批量注册模板

        支持两种 YAML 格式：
        1. 多模板：根节点为 `venues: { venue_key1: {...}, venue_key2: {...} }`
        2. 单模板：根节点为 venue 配置，无 `venues:` 前缀
           - 自动从 `venue_key` 字段或 `name` 字段或文件名获取 key
        """
        import os as _os
        with open(yaml_path, "r", encoding="utf-8") as f:
            configs = yaml.safe_load(f)

        if configs is None:
            return

        # 格式 1：多模板
        if isinstance(configs, dict) and "venues" in configs and isinstance(configs["venues"], dict):
            for venue_key, cfg in configs["venues"].items():
                template_cls = _create_template_from_yaml(venue_key, cfg)
                cls.register(template_cls)
            return

        # 格式 2：单模板
        if isinstance(configs, dict):
            # 从 YAML 中或从文件名推断 venue_key
            venue_key = configs.get("venue_key")
            if not venue_key:
                venue_key = configs.get("name")
            if not venue_key:
                venue_key = _os.path.splitext(_os.path.basename(yaml_path))[0]
            venue_key = str(venue_key).lower().replace(" ", "_")
            template_cls = _create_template_from_yaml(venue_key, configs)
            cls.register(template_cls)


def _create_template_from_yaml(venue_key: str, cfg: dict) -> type[BaseTemplate]:
    """从 YAML 配置动态创建模板类"""
    # 用闭包变量避免 class body 内的同名覆盖问题
    _key = venue_key
    _name = cfg.get("name", venue_key)
    _year = str(cfg.get("year", ""))

    class YamlTemplate(BaseTemplate):
        venue_key = _key
        venue_name = _name
        venue_year = _year
        
        def get_config(self) -> ResolvedTemplate:
            return ResolvedTemplate(
                document_class=cfg["document_class"],
                class_options=cfg.get("class_options", []),
                packages=[PackageSpec(**p) if isinstance(p, dict) else PackageSpec(name=p) 
                         for p in cfg.get("packages", [])],
                section_order=cfg.get("section_order", 
                    ["introduction", "related_work", "method", "experiments", "conclusion"]),
                citation_style=cfg.get("citation_style", "numeric"),
                bibliography_style=cfg.get("bibliography_style", "unsrt"),
                page_limit=cfg.get("page_limit", 9),
                column_layout=cfg.get("column_layout", "single"),
                font_size=cfg.get("font_size", "10pt"),
                figure_placement_default=cfg.get("figure_placement_default", "t"),
                table_placement_default=cfg.get("table_placement_default", "t"),
                title_page_template=cfg.get("title_page_template", "base/title_page.tex.j2"),
                anonymous=cfg.get("anonymous", False),
                engine=cfg.get("engine", "pdflatex"),
                language=cfg.get("language", "english"),
                extra_preamble=cfg.get("extra_preamble", ""),
            )
        
        def get_default_section_composers(self) -> dict[str, str]:
            return cfg.get("section_composers", {
                "introduction": "IntroductionComposer",
                "related_work": "RelatedWorkComposer",
                "method": "MethodComposer",
                "experiments": "ExperimentsComposer",
                "conclusion": "ConclusionComposer",
                "abstract": "AbstractComposer",
            })
    
    return YamlTemplate


# ============================================================================
# 内置模板
# ============================================================================

@TemplateRegistry.register
class NeurIPS2024Template(BaseTemplate):
    venue_key = "neurips2024"
    venue_name = "NeurIPS"
    venue_year = "2024"
    
    def get_config(self) -> ResolvedTemplate:
        return ResolvedTemplate(
            document_class="article",
            class_options=[],
            packages=[
                PackageSpec(name="neurips_2024"),
                PackageSpec(name="inputenc", options=["utf8"]),
                PackageSpec(name="fontenc", options=["T1"]),
                PackageSpec(name="amsmath"),
                PackageSpec(name="amssymb"),
                PackageSpec(name="graphicx"),
                PackageSpec(name="booktabs"),
                PackageSpec(name="hyperref"),
                PackageSpec(name="url"),
                PackageSpec(name="cleveref"),
            ],
            section_order=[
                "introduction", "related_work", "method",
                "experiments", "conclusion"
            ],
            citation_style="numeric",
            bibliography_style="unsrt",
            page_limit=9,
            column_layout="single",
            font_size="10pt",
            figure_placement_default="t",
            table_placement_default="t",
            title_page_template="neurips2024/title_page.tex.j2",
            anonymous=True,
        )
    
    def get_default_section_composers(self) -> dict[str, str]:
        return {
            "abstract": "AbstractComposer",
            "introduction": "IntroductionComposer",
            "related_work": "RelatedWorkComposer",
            "method": "MethodComposer",
            "experiments": "ExperimentsComposer",
            "conclusion": "ConclusionComposer",
        }


@TemplateRegistry.register
class ICML2025Template(BaseTemplate):
    venue_key = "icml2025"
    venue_name = "ICML"
    venue_year = "2025"
    
    def get_config(self) -> ResolvedTemplate:
        return ResolvedTemplate(
            document_class="article",
            class_options=[],
            packages=[
                PackageSpec(name="icml2025"),
                PackageSpec(name="inputenc", options=["utf8"]),
                PackageSpec(name="amsmath"),
                PackageSpec(name="amssymb"),
                PackageSpec(name="graphicx"),
                PackageSpec(name="booktabs"),
                PackageSpec(name="hyperref"),
                PackageSpec(name="cleveref"),
            ],
            section_order=[
                "introduction", "related_work", "method",
                "experiments", "conclusion"
            ],
            citation_style="author-year",
            bibliography_style="plainnat",
            page_limit=8,
            column_layout="single",
            font_size="10pt",
            figure_placement_default="t",
            table_placement_default="t",
            title_page_template="icml2025/title_page.tex.j2",
            anonymous=True,
        )
    
    def get_default_section_composers(self) -> dict[str, str]:
        return {
            "abstract": "AbstractComposer",
            "introduction": "IntroductionComposer",
            "related_work": "RelatedWorkComposer",
            "method": "MethodComposer",
            "experiments": "ExperimentsComposer",
            "conclusion": "ConclusionComposer",
        }


@TemplateRegistry.register
class IEEETemplate(BaseTemplate):
    venue_key = "ieee"
    venue_name = "IEEE"
    venue_year = ""
    
    def get_config(self) -> ResolvedTemplate:
        return ResolvedTemplate(
            document_class="IEEEtran",
            class_options=["conference"],
            packages=[
                PackageSpec(name="inputenc", options=["utf8"]),
                PackageSpec(name="amsmath"),
                PackageSpec(name="amssymb"),
                PackageSpec(name="graphicx"),
                PackageSpec(name="booktabs"),
                PackageSpec(name="hyperref"),
                PackageSpec(name="cite"),
            ],
            section_order=[
                "introduction", "related_work", "method",
                "experiments", "conclusion"
            ],
            citation_style="numeric",
            bibliography_style="IEEEtran",
            page_limit=6,
            column_layout="double",
            font_size="10pt",
            figure_placement_default="t",
            table_placement_default="t",
            title_page_template="ieee/title_page.tex.j2",
            anonymous=False,
        )
    
    def get_default_section_composers(self) -> dict[str, str]:
        return {
            "abstract": "AbstractComposer",
            "introduction": "IntroductionComposer",
            "related_work": "RelatedWorkComposer",
            "method": "MethodComposer",
            "experiments": "ExperimentsComposer",
            "conclusion": "ConclusionComposer",
        }