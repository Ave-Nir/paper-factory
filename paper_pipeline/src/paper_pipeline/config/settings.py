"""
配置中心 —— 所有参数统一收敛，禁止任何散点硬编码

加载优先级（从高到低）：
  1. 统一API配置中心（api_config.py）
  2. 环境变量（运行时覆盖）
  3. YAML 配置文件
  4. 默认值（仅用于开发调试，生产环境必须显式配置）

原则：
- 禁止硬编码任何 API key、路径、阈值
- 禁止魔法数字
- 所有可配置参数必须在配置中心声明
- API配置统一从 api_config.py 读取
"""
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List

# 确保项目根目录在path中，以便导入api_config
_project_root = str(Path(__file__).resolve().parents[4])  # paper-factory 根目录
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from api_config import LLM_API, IMAGE_API
from ..exceptions import ConfigurationError


@dataclass(frozen=True)
class ApiConfig:
    """API 配置 —— 从统一配置中心读取"""
    llm_api_key: str
    image_api_key: str
    image_base_url: str
    image_model: str
    llm_base_url: str
    llm_model: str
    image_timeout: int = 300
    image_max_retries: int = 3
    image_total_timeout: int = 900


@dataclass(frozen=True)
class PathConfig:
    """路径配置"""
    paper2diagram_dir: Path
    paperforge_dir: Path
    work_dir: Path
    diagrams_dir: Path
    build_dir: Path
    miktex_bin: Path


@dataclass(frozen=True)
class DiagramConfig:
    """生图配置 —— S0-S5 流程参数"""
    s2_count: int = 4           # R1 探索候选数量
    s5_count: int = 4           # R2 正式候选数量
    palettes: List[str] = field(default_factory=lambda: [
        "ocean_breeze", "forest_green", "summer_beach", "fresh_holiday"
    ])
    image_size: str = "1792x1024"
    skip_existing: bool = True
    image_gen_interval_sec: int = 2
    min_image_file_size: int = 1024


@dataclass(frozen=True)
class TypesetConfig:
    """排版配置"""
    template: str = "auto"
    generate_word: bool = False
    xelatex_timeout: int = 600


@dataclass(frozen=True)
class InsertionConfig:
    """插入配置"""
    target_keywords: List[str] = field(default_factory=lambda: [
        # 中文关键词
        "研究方法", "技术路线", "计算流程", "方法论",
        "研究设计", "实验方法", "算法流程", "系统设计",
        "方案设计", "整体方案", "实施步骤", "工作流程",
        "设计流程", "硬件设计", "软件设计",
        # 英文关键词（不区分大小写匹配）
        "method", "methodology", "approach",
        "research design", "materials and methods",
        "system design", "design flow", "algorithm",
        "proposed method", "our approach",
    ])
    image_width_inches: float = 5.5
    caption_text: str = "图 研究方法技术路线图"


# ============================================================
# 模板排版标准（用于 Gate5 动态阈值调整）
# ============================================================
TEMPLATE_STANDARDS = {
    # 中文学位论文/期刊模板（字号偏大、边距较宽、1.5倍行距）
    "renai":    {"body_font_pt": 12.0, "heading2_font_pt": 14.0, "margin_top_mm": 25.4, "margin_bottom_mm": 25.4, "margin_left_mm": 31.7, "margin_right_mm": 31.7, "line_spacing": 1.5},
    "thesis":   {"body_font_pt": 12.0, "heading2_font_pt": 14.0, "margin_top_mm": 25.4, "margin_bottom_mm": 25.4, "margin_left_mm": 31.7, "margin_right_mm": 31.7, "line_spacing": 1.5},
    "humanities": {"body_font_pt": 12.0, "heading2_font_pt": 14.0, "margin_top_mm": 25.4, "margin_bottom_mm": 25.4, "margin_left_mm": 31.7, "margin_right_mm": 31.7, "line_spacing": 1.5},
    "nsfc":     {"body_font_pt": 12.0, "heading2_font_pt": 14.0, "margin_top_mm": 25.4, "margin_bottom_mm": 25.4, "margin_left_mm": 31.7, "margin_right_mm": 31.7, "line_spacing": 1.5},
    "sci":      {"body_font_pt": 12.0, "heading2_font_pt": 14.0, "margin_top_mm": 25.4, "margin_bottom_mm": 25.4, "margin_left_mm": 31.7, "margin_right_mm": 31.7, "line_spacing": 1.5},
    # 英文会议论文模板（字号偏小、边距紧凑、单倍行距）
    "ieee":     {"body_font_pt": 10.0, "heading2_font_pt": 12.0, "margin_top_mm": 19.0, "margin_bottom_mm": 19.0, "margin_left_mm": 19.0, "margin_right_mm": 19.0, "line_spacing": 1.0},
    "icml2025": {"body_font_pt": 10.0, "heading2_font_pt": 12.0, "margin_top_mm": 25.4, "margin_bottom_mm": 25.4, "margin_left_mm": 25.4, "margin_right_mm": 25.4, "line_spacing": 1.0},
    "cvpr2024": {"body_font_pt": 10.0, "heading2_font_pt": 12.0, "margin_top_mm": 25.4, "margin_bottom_mm": 25.4, "margin_left_mm": 25.4, "margin_right_mm": 25.4, "line_spacing": 1.0},
    "neurips2024": {"body_font_pt": 10.0, "heading2_font_pt": 12.0, "margin_top_mm": 25.4, "margin_bottom_mm": 25.4, "margin_left_mm": 25.4, "margin_right_mm": 25.4, "line_spacing": 1.0},
    "acl2024":  {"body_font_pt": 11.0, "heading2_font_pt": 13.0, "margin_top_mm": 25.4, "margin_bottom_mm": 25.4, "margin_left_mm": 25.4, "margin_right_mm": 25.4, "line_spacing": 1.0},
}


@dataclass(frozen=True)
class Settings:
    """全局配置聚合"""
    api: ApiConfig
    paths: PathConfig
    diagram: DiagramConfig
    typeset: TypesetConfig
    insertion: InsertionConfig


def _require_env(name: str) -> str:
    """强制要求环境变量存在，否则抛出 ConfigurationError"""
    value = os.environ.get(name)
    if not value:
        raise ConfigurationError(
            message=f"必需环境变量未设置: {name}",
            stage="CONFIG",
            context={"env_var": name},
        )
    return value


def _get_env(name: str, default: str) -> str:
    """读取环境变量，不存在则使用默认值"""
    return os.environ.get(name, default)


def _get_env_int(name: str, default: int) -> int:
    """读取整数型环境变量"""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as e:
        raise ConfigurationError(
            message=f"环境变量 {name} 必须为整数",
            stage="CONFIG",
            context={"env_var": name, "raw_value": raw},
            cause=e,
        )


def get_settings(
    work_dir: Optional[Path] = None,
    paper_file: Optional[Path] = None,
) -> Settings:
    """
    构建全局配置实例

    API配置从统一配置中心（api_config.py）读取。
    路径优先级：
      1. 显式传入的 work_dir 参数
      2. 环境变量 PAPER_PIPELINE_HOME / PAPER2DIAGRAM_HOME / PAPERFORGE_HOME / MIKTEK_BIN
      3. 基于当前文件位置的相对路径（<项目根>/paper_pipeline, paper2diagram-skill, paperforge）
    """
    # API 配置 —— 运行时从环境变量读取（fail-closed），
    # 端点/模型等非敏感项以统一配置中心 api_config 的默认值兜底
    api = ApiConfig(
        llm_api_key=_require_env("LLM_API_KEY"),
        image_api_key=_require_env("IMAGE_API_KEY"),
        image_base_url=_get_env("IMAGE_BASE_URL", IMAGE_API.base_url),
        image_model=_get_env("IMAGE_MODEL", IMAGE_API.model),
        llm_base_url=_get_env("LLM_BASE_URL", LLM_API.base_url),
        llm_model=_get_env("LLM_MODEL", LLM_API.model),
        image_timeout=_get_env_int("IMAGE_TIMEOUT", IMAGE_API.timeout),
        image_max_retries=_get_env_int("IMAGE_MAX_RETRIES", IMAGE_API.max_retries),
        image_total_timeout=900,
    )

    # 路径解析 —— 优先级：参数 > 环境变量 > 相对项目根的相对路径
    # 项目根 = settings.py 的 4 级父目录 (paper_pipeline/src/paper_pipeline/config/settings.py)
    _project_root = Path(__file__).resolve().parents[4]  # paper-factory/

    if work_dir:
        base = Path(work_dir)
    elif env_work_dir := os.environ.get("PAPER_PIPELINE_HOME"):
        base = Path(env_work_dir)
    else:
        base = _project_root / "paper_pipeline"

    paper2diagram_dir = (
        Path(os.environ["PAPER2DIAGRAM_HOME"])
        if os.environ.get("PAPER2DIAGRAM_HOME")
        else _project_root / "paper2diagram-skill"
    )
    paperforge_dir = (
        Path(os.environ["PAPERFORGE_HOME"])
        if os.environ.get("PAPERFORGE_HOME")
        else _project_root / "paperforge"
    )
    miktex_bin = (
        Path(os.environ["MIKTEX_BIN"])
        if os.environ.get("MIKTEX_BIN")
        else _project_root / "tools" / "miktex" / "bin"
    )

    paths = PathConfig(
        paper2diagram_dir=paper2diagram_dir,
        paperforge_dir=paperforge_dir,
        work_dir=base,
        diagrams_dir=base / "diagrams",
        build_dir=base / "build",
        miktex_bin=miktex_bin,
    )

    # 生图配置 —— 可从环境变量覆盖
    diagram = DiagramConfig(
        s2_count=_get_env_int("DIAGRAM_S2_COUNT", 4),
        s5_count=_get_env_int("DIAGRAM_S5_COUNT", 4),
        palettes=_get_env("DIAGRAM_PALETTES", "ocean_breeze,forest_green,summer_beach,fresh_holiday").split(","),
        image_size=_get_env("IMAGE_SIZE", "1792x1024"),
        skip_existing=_get_env("DIAGRAM_SKIP_EXISTING", "true").lower() == "true",
    )

    # 排版配置
    typeset = TypesetConfig(
        template=_get_env("TYPESET_TEMPLATE", "auto"),
        generate_word=_get_env("TYPESET_GENERATE_WORD", "false").lower() == "true",
        xelatex_timeout=_get_env_int("TYPESET_XELATEX_TIMEOUT", 600),
    )

    # 插入配置
    insertion = InsertionConfig()

    return Settings(api=api, paths=paths, diagram=diagram, typeset=typeset, insertion=insertion)
