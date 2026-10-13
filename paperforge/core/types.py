"""
PaperForge 类型系统 —— 所有数据流转使用的严格类型定义。

设计原则：
- 所有类型使用 TypedDict 或 dataclass，保证结构可验证
- 每个 Claim 强制关联 citation_keys，防止"孤儿声明"
- 引用数据库与论文数据分离，便于复用
"""

from dataclasses import dataclass, field
from typing import TypedDict, Literal, Optional, List, Dict
from enum import Enum


# ============================================================================
# 文档解析类型（Block 体系）
# ============================================================================

@dataclass
class Block:
    type: str
    level: int = 0
    title: str = ""
    content: str = ""
    idx: int = 0
    data: dict = field(default_factory=dict)


@dataclass
class DocxImage:
    idx: int
    rid: str = ""
    extracted_path: str = ""
    caption: str = ""
    paragraph_index: int = 0
    width: int = 0      # 图片宽度（像素）
    height: int = 0     # 图片高度（像素）


@dataclass
class DocxTable:
    idx: int = 0
    headers: List[str] = field(default_factory=list)
    rows: List[List[str]] = field(default_factory=list)
    caption: str = ""
    paragraph_index: int = 0


@dataclass
class DocumentContent:
    blocks: List[Block] = field(default_factory=list)
    text: str = ""
    images: List[DocxImage] = field(default_factory=list)
    tables: List[DocxTable] = field(default_factory=list)
    source_file: str = ""

    def has_images(self) -> bool:
        return len(self.images) > 0

    def has_tables(self) -> bool:
        return len(self.tables) > 0


# ============================================================================
# 基础原子类型
# ============================================================================

class Author(TypedDict):
    name: str
    affiliation: str
    email: Optional[str]
    orcid: Optional[str]


class BibEntry(TypedDict):
    """单个 BibTeX 条目"""
    key: str
    entry_type: str          # "article", "inproceedings", "book", etc.
    fields: dict[str, str]   # author, title, journal, year, etc.


class Claim(TypedDict):
    """一个带引用的声明 —— 论文内容的最小原子单元"""
    text: str
    citation_keys: list[str]  # 强制非空，防止"孤儿声明"
    confidence: Literal["established", "emerging", "speculative"]


class Contribution(TypedDict):
    """一条核心贡献"""
    text: str
    evidence: str             # 支撑该贡献的证据/实验


class FigureSpec(TypedDict):
    """图表规格"""
    key: str                  # \label{fig:xxx}
    path: str                 # 图片文件路径
    caption: str
    placement: Literal["t", "b", "p", "h", "H"]  # LaTeX 浮动位置
    width: str                # 如 "0.8\\textwidth"


class TableSpec(TypedDict):
    """表格规格"""
    key: str
    caption: str
    headers: list[str]
    rows: list[list[str]]
    placement: Literal["t", "b", "p", "h", "H"]
    column_format: str        # 如 "lccc"


# ============================================================================
# 论文级类型
# ============================================================================

class PaperSpec(TypedDict):
    """论文元数据"""
    title: str
    authors: list[Author]
    venue: str                # 如 "neurips2024", "icml2025"
    field: str                # 如 "cs_ml", "cs_cv", "bio_informatics"
    keywords: list[str]
    abstract: Optional[str]   # 可先空着，由 AbstractComposer 生成


# ============================================================================
# 各章节结构化数据类型
# ============================================================================

class IntroductionData(TypedDict):
    background: list[Claim]
    problem_statement: str
    research_gap: str
    contributions: list[Contribution]
    paper_structure: list[str]   # "Section 2: ...", "Section 3: ..."


class RelatedWorkData(TypedDict):
    subsections: list["RelatedWorkSubSection"]


class RelatedWorkSubSection(TypedDict):
    topic: str
    works: list[Claim]


class MethodData(TypedDict):
    overview: str
    subsections: list["MethodSubSection"]
    algorithms: list["AlgorithmSpec"]


class MethodSubSection(TypedDict):
    title: str
    content: str               # 已格式化的技术描述
    equations: list["EquationSpec"]
    figures: list[FigureSpec]


class AlgorithmSpec(TypedDict):
    key: str                   # \label{alg:xxx}
    caption: str
    steps: list[str]
    input_desc: str
    output_desc: str


class EquationSpec(TypedDict):
    key: str                   # \label{eq:xxx}
    latex: str                 # 纯 LaTeX 数学公式
    description: str


class ExperimentData(TypedDict):
    subsections: list["ExperimentSubSection"]


class ExperimentSubSection(TypedDict):
    title: str                 # "Main Results", "Ablation Study", etc.
    description: str
    tables: list[TableSpec]
    figures: list[FigureSpec]
    findings: list[Claim]      # 从实验结果中得出的声明


class ConclusionData(TypedDict):
    summary: str
    limitations: list[str]
    future_work: list[str]


class AbstractData(TypedDict):
    context: str               # 1-2 句背景
    problem: str               # 1 句问题
    approach: str              # 2-3 句方法
    results: str               # 1-2 句结果
    impact: str                # 1 句影响/展望


# ============================================================================
# 引用数据库
# ============================================================================

@dataclass
class ReferenceDB:
    """引用数据库 —— 所有 BibTeX 条目的集合"""
    entries: dict[str, BibEntry] = field(default_factory=dict)
    
    def add(self, entry: BibEntry) -> None:
        self.entries[entry["key"]] = entry
    
    def get(self, key: str) -> Optional[BibEntry]:
        return self.entries.get(key)
    
    def validate_keys_exist(self, keys: list[str]) -> tuple[bool, list[str]]:
        """检查所有引用 key 是否存在。返回 (全部存在, 缺失的 keys)"""
        missing = [k for k in keys if k not in self.entries]
        return len(missing) == 0, missing
    
    def export_bibtex(self) -> str:
        """导出完整的 .bib 文件内容 —— 自动转义字段值中的特殊字符
        
        处理规则：
        - author 字段中的 & 替换为 and（BibTeX 用 and 分隔作者）
        - 其他字段（publisher, title, journal 等）用 {\&} 转义
        - 其他特殊字符（_, %, #, $）用 LaTeX 转义命令保护
        """
        def _escape_bib_field(field_name: str, v: str) -> str:
            """按字段名区别处理"""
            if not v:
                return v
            
            # 作者字段：将 "A & B" 格式的 & 替换为 "and"
            if field_name in ("author", "authors", "editor", "editors"):
                # 只替换看起来像分隔符的 &（前后都是空格或在行首/行尾）
                import re as _re
                v = _re.sub(r"\s*&\s*", " and ", v)
                return v
            
            # 其他字段：转义特殊字符
            # 使用 {\&} 而不是 \&，因为某些 bst 样式会吃掉 \
            for ch, rep in [("&", r"{\&}"), ("%", r"\%"),
                            ("_", r"\_"), ("#", r"\#"),
                            ("$", r"\$")]:
                v = v.replace(ch, rep)
            return v
        
        lines = []
        for entry in self.entries.values():
            lines.append(f"@{entry['entry_type']}{{{entry['key']},")
            for k, v in entry["fields"].items():
                lines.append(f"  {k} = {{{_escape_bib_field(k, v)}}},")
            lines.append("}\n")
        return "\n".join(lines)
    
    def __len__(self) -> int:
        return len(self.entries)


# ============================================================================
# SectionData 联合类型
# ============================================================================

SectionData = (
    IntroductionData | RelatedWorkData | MethodData | 
    ExperimentData | ConclusionData | AbstractData
)


# ============================================================================
# Gate 报告类型
# ============================================================================

class DiagnosticSeverity(Enum):
    ERROR = "error"       # 必须修复
    WARNING = "warning"   # 建议修复
    INFO = "info"         # 仅记录


@dataclass
class Diagnostic:
    severity: DiagnosticSeverity
    location: str          # 如 "introduction.background[2]", "equation:eq:main_loss"
    message: str
    fix_suggestion: str = ""


@dataclass
class GateReport:
    gate_name: str
    status: Literal["PASS", "FAIL", "WARN"]
    diagnostics: list[Diagnostic] = field(default_factory=list)
    
    @property
    def can_proceed(self) -> bool:
        """FAIL 状态不允许继续"""
        return self.status != "FAIL"
    
    @property
    def errors(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == DiagnosticSeverity.ERROR]
    
    @property
    def warnings(self) -> list[Diagnostic]:
        return [d for d in self.diagnostics if d.severity == DiagnosticSeverity.WARNING]


# ============================================================================
# 输出类型
# ============================================================================

@dataclass
class LaTeXBlock:
    """一个章节的 LaTeX 输出块"""
    content: str
    section_name: str
    estimated_pages: float = 0.0


@dataclass
class CompileResult:
    """LaTeX 编译结果"""
    success: bool
    pdf_path: Optional[str] = None
    log: str = ""
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    engine: str = "pdflatex"  # pdflatex / xelatex


@dataclass
class BuildResult:
    """完整构建结果"""
    tex_path: str
    pdf_path: Optional[str]
    gate_reports: list[GateReport]
    all_passed: bool

    @property
    def tex_content(self) -> str:
        with open(self.tex_path, "r", encoding="utf-8") as f:
            return f.read()


# ============================================================================
# 模板检测类型
# ============================================================================

@dataclass
class TemplateCandidate:
    """模板候选"""
    name: str
    score: float
    matched_rules: list[str] = field(default_factory=list)


@dataclass
class TemplateDetection:
    """模板检测结果"""
    template: str
    confidence: float
    candidates: list[TemplateCandidate] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)

    @property
    def is_confident(self) -> bool:
        """置信度 >= 0.7 视为可信"""
        return self.confidence >= 0.7


# ============================================================================
# 质量检查类型
# ============================================================================

class IssueSeverity(Enum):
    ERROR = "error"        # 必须修复
    WARNING = "warning"    # 建议修复
    INFO = "info"          # 仅记录


@dataclass
class CompileIssue:
    """编译问题"""
    severity: IssueSeverity
    category: str          # "font_missing", "char_missing", "package_error", etc.
    message: str
    location: str = ""     # 日志行号或位置


@dataclass
class QualityReport:
    """输出质量报告"""
    success: bool
    pdf_exists: bool
    pdf_pages: int = 0
    issues: list[CompileIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[CompileIssue]:
        return [i for i in self.issues if i.severity == IssueSeverity.ERROR]

    @property
    def warnings(self) -> list[CompileIssue]:
        return [i for i in self.issues if i.severity == IssueSeverity.WARNING]

    def summary(self) -> str:
        """生成摘要报告"""
        lines = [f"PDF: {'✓' if self.pdf_exists else '✗'} ({self.pdf_pages} 页)"]
        if self.errors:
            lines.append(f"错误: {len(self.errors)} 个")
        if self.warnings:
            lines.append(f"警告: {len(self.warnings)} 个")
        return " | ".join(lines)