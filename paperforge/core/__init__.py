"""
PaperForge — Code-Driven LaTeX Paper Writing Skill

核心模块：
- types: 所有数据结构定义
- template_engine: 模板引擎（加载和管理 venue 模板）
- latex_compiler: LaTeX 编译器和静态检查器
- assembler: 将各章节拼装为完整 .tex 文件
- checker: LaTeX 静态检查器（独立模块）
- retryer: 编译重试器（独立模块）
- formatting: 排版格式规格和差异化渲染器
- word_builder: Word 文档构建器（与 PDF 对齐排版）
- formula_engine: 公式处理引擎（支持 Unicode/OMML/LaTeX 输出）
- quality_validator: 质量验证器（检查文档质量问题）
- utils: 工具模块（MiKTeX 路径检测等）
"""

from .types import (
    PaperSpec, Author, BibEntry, Claim, Contribution,
    FigureSpec, TableSpec, EquationSpec, AlgorithmSpec,
    IntroductionData, RelatedWorkData, MethodData,
    ExperimentData, ConclusionData, AbstractData,
    ReferenceDB, SectionData, LaTeXBlock,
    CompileResult, BuildResult, GateReport, Diagnostic, DiagnosticSeverity,
)
from .template_engine import (
    BaseTemplate, ResolvedTemplate, PackageSpec,
    TemplateRegistry, NeurIPS2024Template, ICML2025Template, IEEETemplate,
)
from .latex_compiler import LaTeXCompiler, LaTeXStaticChecker, CompilationError
from .assembler import LaTeXAssembler
from .checker import LaTeXChecker, LaTeXError, LaTeXErrorType, LaTeXStaticChecker as CheckerStaticChecker
from .retryer import CompilationRetryer, CompileResult as RetryCompileResult, CompilationError as RetryCompilationError
from .formatting import (
    FormatSpec, FormatSpecParser, DifferentiatedRenderer,
    PRESET_FORMATS, register_preset, parse_format_from_docx, parse_format_from_dict,
)
from .word_builder import WordDocumentBuilder, WordFormatRenderer
from .formula_engine import FormulaEngine, OutputMode, FormulaContext, DOIVerifier
from .quality_validator import QualityValidator, ValidationResult, Issue, IssueType, IssueSeverity
from .converter import Converter, ConversionConfig, ConversionResult as ConverterConversionResult, convert
from .nl_intake import (
    NLIntake, OpenAILLM, MockLLM,
    IntakeParseError, IntakeValidationError,
    INTAKE_SYSTEM_PROMPT,
)
from .llm_factory import create_llm_from_env, describe_config, LLMConfigError
from .utils import find_miktex_path, MikTeXResolver