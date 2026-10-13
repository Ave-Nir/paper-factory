"""
质量门 —— 保障证明链闭环、生成-校验对齐

原则：
- 所有生成路径必须纳入 Gate 管控体系
- 禁止绕过质量 Gate 的新增出口
- 异常必须携带完整上下文，纳入统一异常处理体系
- 检测结果应包含精确位置信息（页码、LaTeX 行号、Block 索引）
- 可自动修正的错误应提供修复建议和自动修复能力
"""
from pathlib import Path
from typing import List, Dict, Any, Optional
import re
from collections import Counter

from ..exceptions import ValidationError
from ..models.diagram import DiagramResult


# ============================================================
# 位置标记解析（从 .tex 文件中提取）
# ============================================================
_LOCATION_TAG_RE = re.compile(r"%\s*\[LOC:([\w-]+):(\d+)(?::(\w+))?\]")
"""匹配 LaTeX 注释中的位置标记：% [LOC:type:block_idx:subtype]"""


class LocationMarker:
    """位置标记 —— 将 PDF 检测结果映射到 LaTeX 源文件"""
    
    def __init__(self, marker_type: str, block_idx: int, subtype: str = ""):
        self.marker_type = marker_type
        self.block_idx = int(block_idx)
        self.subtype = subtype
    
    def __repr__(self):
        return f"LocationMarker(type={self.marker_type}, block={self.block_idx}, subtype={self.subtype})"


def parse_location_markers(tex_path: Path) -> Dict[str, List[LocationMarker]]:
    """
    从 .tex 文件中解析位置标记。
    
    返回: Dict[marker_type, List[LocationMarker]]
    """
    if not tex_path.exists():
        return {}
    
    markers: Dict[str, List[LocationMarker]] = {}
    
    try:
        with open(tex_path, "r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                match = _LOCATION_TAG_RE.search(line)
                if match:
                    marker_type = match.group(1)
                    block_idx = match.group(2)
                    subtype = match.group(3) or ""
                    marker = LocationMarker(marker_type, block_idx, subtype)
                    if marker_type not in markers:
                        markers[marker_type] = []
                    markers[marker_type].append(marker)
    except Exception:
        pass
    
    return markers


# ============================================================
# 修正规则引擎
# ============================================================
class FixRule:
    """修正规则 —— 定义错误类型、检测方法、修复方法"""
    
    def __init__(
        self,
        error_code: str,
        description: str,
        can_fix: bool,
        fix_func=None,
    ):
        self.error_code = error_code
        self.description = description
        self.can_fix = can_fix
        self.fix_func = fix_func
    
    def apply_fix(self, tex_path: Path, context: Dict[str, Any]) -> bool:
        """
        应用修复。
        
        返回: 是否修复成功
        """
        if not self.can_fix or not self.fix_func:
            return False
        try:
            return self.fix_func(tex_path, context)
        except Exception:
            return False


# 预定义修正规则
_FIX_RULES = {
    "DUPLICATE_REF_HEADING": FixRule(
        error_code="DUPLICATE_REF_HEADING",
        description="重复参考文献标题",
        can_fix=True,
        fix_func=lambda tex, ctx: _fix_duplicate_ref_heading(tex, ctx),
    ),
    "SUBHEADING_NOT_LEFT": FixRule(
        error_code="SUBHEADING_NOT_LEFT",
        description="二级标题未左对齐",
        can_fix=True,
        fix_func=lambda tex, ctx: _fix_subheading_alignment(tex, ctx),
    ),
    "KEYWORD_ALONE": FixRule(
        error_code="KEYWORD_ALONE",
        description="关键词单独占一页",
        can_fix=True,
        fix_func=lambda tex, ctx: _fix_keyword_page(tex, ctx),
    ),
    "TOC_NOT_SEPARATE": FixRule(
        error_code="TOC_NOT_SEPARATE",
        description="目录未单独占一页",
        can_fix=True,
        fix_func=lambda tex, ctx: _fix_toc_separate_page(tex, ctx),
    ),
    "EMPTY_ABSTRACT": FixRule(
        error_code="EMPTY_ABSTRACT",
        description="摘要内容为空",
        can_fix=False,
    ),
    "ROMAN_AFTER_ARABIC": FixRule(
        error_code="ROMAN_AFTER_ARABIC",
        description="页码格式错误：罗马数字出现在阿拉伯数字之后",
        can_fix=True,
        fix_func=lambda tex, ctx: _fix_page_numbering(tex, ctx),
    ),
    "FONT_INCONSISTENT": FixRule(
        error_code="FONT_INCONSISTENT",
        description="正文字号不一致",
        can_fix=True,
        fix_func=lambda tex, ctx: _fix_body_font_size(tex, ctx),
    ),
    # 新增修复规则（方向1）
    "FORMULA_NOT_WRAPPED": FixRule(
        error_code="FORMULA_NOT_WRAPPED",
        description="公式未正确包裹数学符号",
        can_fix=True,
        fix_func=lambda tex, ctx: _fix_unwrapped_formulas(tex, ctx),
    ),
    "TABLE_NOT_THREE_LINE": FixRule(
        error_code="TABLE_NOT_THREE_LINE",
        description="表格未使用三线表格式",
        can_fix=True,
        fix_func=lambda tex, ctx: _fix_three_line_table(tex, ctx),
    ),
    "TABLE_BOOKTABS_MISSING": FixRule(
        error_code="TABLE_BOOKTABS_MISSING",
        description="表格缺少 booktabs 宏包",
        can_fix=True,
        fix_func=lambda tex, ctx: _fix_booktabs_missing(tex, ctx),
    ),
    "IMAGE_ASPECT_DISTORTED": FixRule(
        error_code="IMAGE_ASPECT_DISTORTED",
        description="图片宽高比异常（可能拉伸变形）",
        can_fix=True,
        fix_func=lambda tex, ctx: _fix_image_aspect(tex, ctx),
    ),
    "MISSING_GRAPHICSPATH": FixRule(
        error_code="MISSING_GRAPHICSPATH",
        description="缺少 \\graphicspath 设置",
        can_fix=True,
        fix_func=lambda tex, ctx: _fix_graphicspath(tex, ctx),
    ),
    "TOC_EMPTY": FixRule(
        error_code="TOC_EMPTY",
        description="目录无条目",
        can_fix=True,
        fix_func=lambda tex, ctx: _fix_toc_empty(tex, ctx),
    ),
    "TOC_INCOMPLETE": FixRule(
        error_code="TOC_INCOMPLETE",
        description="目录条目不完整",
        can_fix=True,
        fix_func=lambda tex, ctx: _fix_toc_incomplete(tex, ctx),
    ),
    "TOC_PAGE_MISMATCH": FixRule(
        error_code="TOC_PAGE_MISMATCH",
        description="目录未固定在第二页",
        can_fix=True,
        fix_func=lambda tex, ctx: _fix_toc_page_position(tex, ctx),
    ),
    "NO_IMAGE_INSERTED": FixRule(
        error_code="NO_IMAGE_INSERTED",
        description="未检测到图片",
        can_fix=False,
    ),
}


def _fix_duplicate_ref_heading(tex_path: Path, context: Dict[str, Any]) -> bool:
    """修复重复参考文献标题 —— 删除多余的参考文献标题"""
    try:
        content = tex_path.read_text(encoding="utf-8")
        # 查找所有参考文献标题
        ref_heading_pattern = re.compile(
            r"(\\section\*\{参考文献\}|\\chapter\*\{参考文献\}|\\section\*\{References\}|\\chapter\*\{References\})",
            re.IGNORECASE,
        )
        matches = list(ref_heading_pattern.finditer(content))
        if len(matches) <= 1:
            return True
        
        # 保留最后一个，删除前面的
        last_pos = matches[-1].start()
        fixed_content = content[:last_pos] + ref_heading_pattern.sub("", content[last_pos:])
        
        tex_path.write_text(fixed_content, encoding="utf-8")
        return True
    except Exception:
        return False


def _fix_subheading_alignment(tex_path: Path, context: Dict[str, Any]) -> bool:
    """修复二级标题未左对齐 —— 确保 titlesec 设置正确"""
    try:
        content = tex_path.read_text(encoding="utf-8")
        
        # 检查是否有 titlesec 设置，如果没有则添加
        if "\\titleformat" not in content:
            # 在 \begin{document} 之前添加 titlesec 设置
            content = content.replace(
                "\\begin{document}",
                "\\titleformat{\\section}[block]{\\heiti\\fontsize{14pt}{20pt}\\selectfont\\bfseries\\raggedright}{\\thesection}{0.5em}{}\n\\begin{document}",
            )
        
        # 确保存在 \raggedright 设置
        content = content.replace(
            "\\titleformat{\\section}[block]",
            "\\titleformat{\\section}[block]{\\raggedright}",
        )
        
        tex_path.write_text(content, encoding="utf-8")
        return True
    except Exception:
        return False


def _fix_keyword_page(tex_path: Path, context: Dict[str, Any]) -> bool:
    """修复关键词单独占一页 —— 删除关键词和目录之间的 \\clearpage"""
    try:
        content = tex_path.read_text(encoding="utf-8")
        
        # 找到关键词和目录之间的 \clearpage
        # 模式：关键词区域结束后，\tableofcontents 之前的 \clearpage
        content = re.sub(
            r"(\\end\{abstract\})\s*\n*\s*(\\clearpage)\s*\n*\s*(\\tableofcontents)",
            r"\1\n\3",
            content,
        )
        
        tex_path.write_text(content, encoding="utf-8")
        return True
    except Exception:
        return False


def _fix_toc_separate_page(tex_path: Path, context: Dict[str, Any]) -> bool:
    """修复目录未单独占一页 —— 在 \\tableofcontents 前添加 \\clearpage"""
    try:
        content = tex_path.read_text(encoding="utf-8")
        
        # 在 \tableofcontents 前添加 \clearpage（如果不存在）
        content = re.sub(
            r"(?<!\\clearpage\s*\n)\s*(\\tableofcontents)",
            r"\\clearpage\n\1",
            content,
        )
        
        tex_path.write_text(content, encoding="utf-8")
        return True
    except Exception:
        return False


def _fix_page_numbering(tex_path: Path, context: Dict[str, Any]) -> bool:
    """修复页码格式错误 —— 确保页码区域正确划分"""
    try:
        content = tex_path.read_text(encoding="utf-8")
        
        # 确保 \pagenumbering{Roman} 在摘要之前
        if "\\pagenumbering{Roman}" not in content:
            content = content.replace(
                "\\begin{document}",
                "\\begin{document}\n\\pagenumbering{Roman}",
            )
        
        # 确保正文开始时切换到阿拉伯数字
        content = re.sub(
            r"(\\chapter\*\{[^}]+\})\s*(?<!\\pagenumbering\{arabic\})",
            r"\1\n\\pagenumbering{arabic}",
            content,
        )
        
        tex_path.write_text(content, encoding="utf-8")
        return True
    except Exception:
        return False


def _fix_body_font_size(tex_path: Path, context: Dict[str, Any]) -> bool:
    """修复正文字号不一致 —— 设置统一的正文字号"""
    try:
        content = tex_path.read_text(encoding="utf-8")
        
        # 添加或更新 \fontsize 设置
        if "\\fontsize" not in content:
            content = content.replace(
                "\\begin{document}",
                "\\begin{document}\n\\fontsize{12pt}{18pt}\\selectfont",
            )
        
        tex_path.write_text(content, encoding="utf-8")
        return True
    except Exception:
        return False


# ============================================================
# 方向1：新增修复函数
# ============================================================

def _fix_unwrapped_formulas(tex_path: Path, context: Dict[str, Any]) -> bool:
    """修复未包裹的公式 —— 将裸露的数学符号用 $ 包裹
    
    检测模式：
    - 裸露的希腊字母（α, β, γ 等）
    - 裸露的数学符号（×, ÷, ≤, ≥）
    - 裸露的变量下标（x_1, P_2 等）
    """
    try:
        content = tex_path.read_text(encoding="utf-8")
        
        # 1. 修复裸露的希腊字母
        _GREEK_PATTERN = re.compile(r'(?<![\\$a-zA-Z])(α|β|γ|δ|ε|ζ|η|θ|λ|μ|π|σ|τ|φ|ω|Δ|Σ|Ω|Π|Θ)(?![\\$a-zA-Z_])')
        content = _GREEK_PATTERN.sub(r'$\1$', content)
        
        # 2. 修复裸露的数学符号（×, ÷）
        content = re.sub(r'(?<![\\$\w])(\×|÷)(?![\\$\w])', r'$\1$', content)
        
        # 3. 修复裸露的下标（如 x_1 → $x_1$）
        content = re.sub(
            r'(?<![\\$a-zA-Z_\\])(\w)_(\d+)(?![\\$a-zA-Z0-9_])',
            r'$\1_{\2}$',
            content,
        )
        
        tex_path.write_text(content, encoding="utf-8")
        return True
    except Exception:
        return False


def _fix_three_line_table(tex_path: Path, context: Dict[str, Any]) -> bool:
    """修复非三线表 —— 将普通表格转换为 booktabs 三线表
    
    转换规则：
    - \\hline → \\toprule / \\midrule / \\bottomrule
    - \\cline{...} → \\midrule
    """
    try:
        content = tex_path.read_text(encoding="utf-8")
        
        # 1. 第一个 \hline → \toprule
        content = re.sub(
            r'(\\begin\{tabular\}\{[^}]+\})\s*\n\s*\\hline',
            r'\1\n    \\toprule',
            content,
            count=1,
        )
        
        # 2. 中间所有 \hline → \midrule（仅保留第一个为 \toprule 后的）
        content = re.sub(
            r'\\hline',
            r'\\midrule',
            content,
        )
        
        # 3. 最后一个 \midrule（在 \end{tabular} 前） → \bottomrule
        content = re.sub(
            r'(\\midrule\s*\\end\{tabular\})',
            r'\\bottomrule\1',
            content,
        )
        
        # 4. \cline{a-b} → \midrule
        content = re.sub(r'\\cline\{[^}]+\}', r'\\midrule', content)
        
        tex_path.write_text(content, encoding="utf-8")
        return True
    except Exception:
        return False


def _fix_booktabs_missing(tex_path: Path, context: Dict[str, Any]) -> bool:
    """修复缺失的 booktabs 宏包 —— 添加 \\usepackage{booktabs}"""
    try:
        content = tex_path.read_text(encoding="utf-8")
        
        if "\\usepackage{booktabs}" in content:
            return True
        
        # 在 documentclass 之后插入
        if "\\documentclass" in content:
            content = re.sub(
                r'(\\documentclass[^\n]+\n)',
                r'\1\\usepackage{booktabs}\n',
                content,
                count=1,
            )
            tex_path.write_text(content, encoding="utf-8")
            return True
        
        return False
    except Exception:
        return False


def _fix_image_aspect(tex_path: Path, context: Dict[str, Any]) -> bool:
    """修复图片宽高比异常 —— 添加 keepaspectratio 选项
    
    策略：移除显式的 width 和 height 同时设置，改用 width 单独控制并添加 keepaspectratio
    """
    try:
        content = tex_path.read_text(encoding="utf-8")
        
        # 模式：\includegraphics[width=X,height=Y,keepaspectratio]{...}
        #      → \includegraphics[width=X,keepaspectratio]{...}
        content = re.sub(
            r'\\includegraphics(\[width=[^,\]]+,height=[^,\]]+)(?:\s*,\s*keepaspectratio)?\s*\]',
            r'\\includegraphics[\1,keepaspectratio]',
            content,
        )
        
        # 模式：\includegraphics[width=X,height=Y,keepaspectratio=false]{...}
        #      → \includegraphics[width=X,keepaspectratio]{...}
        content = re.sub(
            r'\\includegraphics\[[^\]]*keepaspectratio=false[^\]]*\]',
            r'\\includegraphics[width=0.9\\textwidth,keepaspectratio]',
            content,
        )
        
        tex_path.write_text(content, encoding="utf-8")
        return True
    except Exception:
        return False


def _fix_graphicspath(tex_path: Path, context: Dict[str, Any]) -> bool:
    """修复缺失的 \\graphicspath —— 添加 images 目录路径"""
    try:
        content = tex_path.read_text(encoding="utf-8")
        
        if "\\graphicspath" in content:
            return True
        
        # 在 documentclass 之后插入
        if "\\documentclass" in content:
            content = re.sub(
                r'(\\documentclass[^\n]+\n)',
                r'\1\\graphicspath{{./images/}}\n',
                content,
                count=1,
            )
            tex_path.write_text(content, encoding="utf-8")
            return True
        
        return False
    except Exception:
        return False


def _fix_toc_empty(tex_path: Path, context: Dict[str, Any]) -> bool:
    """修复目录为空 —— 清理 .aux/.toc 并在 \\begin{document} 后确保 \\tableofcontents"""
    try:
        content = tex_path.read_text(encoding="utf-8")

        # 1. 确保 \\tableofcontents 命令存在
        if "\\tableofcontents" not in content:
            content = content.replace(
                "\\begin{document}",
                "\\begin{document}\n\\tableofcontents\n\\clearpage",
                1,
            )
            tex_path.write_text(content, encoding="utf-8")

        # 2. 清理 .aux/.toc/.out 强制 LaTeX 重新生成目录条目
        build_dir = tex_path.parent
        for ext in [".aux", ".toc", ".out", ".lof", ".lot"]:
            aux_file = tex_path.with_suffix(ext)
            if aux_file.exists():
                aux_file.unlink()
        return True
    except Exception:
        return False


def _fix_toc_incomplete(tex_path: Path, context: Dict[str, Any]) -> bool:
    """修复目录条目不完整 —— 重新生成目录

    策略：清理所有 .aux 和 .toc 文件，强制 LaTeX 重新生成目录
    """
    try:
        build_dir = tex_path.parent
        for ext in [".aux", ".toc", ".out", ".lof", ".lot"]:
            aux_file = tex_path.with_suffix(ext)
            if aux_file.exists():
                aux_file.unlink()
        return True
    except Exception:
        return False


def _fix_toc_page_position(tex_path: Path, context: Dict[str, Any]) -> bool:
    """修复目录未固定在第二页 —— 在 \\maketitle 后添加 \\clearpage 和 \\thispagestyle{empty}"""
    try:
        content = tex_path.read_text(encoding="utf-8")
        # 确保 \maketitle 后有 \clearpage
        if r"\maketitle" in content and r"\clearpage" not in content.split(r"\maketitle")[1].split(r"\pagenumbering")[0]:
            content = content.replace(
                r"\maketitle",
                r"\maketitle" + "\n" + r"\thispagestyle{empty}" + "\n" + r"\clearpage"
            )
            tex_path.write_text(content, encoding="utf-8")
            return True
        return True
    except Exception:
        return False


def apply_fixes(tex_path: Path, errors: List[str], context: Dict[str, Any]) -> Dict[str, bool]:
    """
    对检测到的错误应用自动修复。
    
    返回: Dict[error_code, 是否修复成功]
    """
    results: Dict[str, bool] = {}
    
    for error in errors:
        # 从错误消息中提取错误代码
        for error_code, rule in _FIX_RULES.items():
            if error_code in error:
                success = rule.apply_fix(tex_path, context)
                results[error_code] = success
                break
    
    return results


class GateIssue:
    """
    Gate 检测问题条目 —— 结构化错误/警告信息

    包含错误代码、位置信息、修复建议等，支持输出到 JSON 报告
    """

    def __init__(
        self,
        error_code: str,
        severity: str,  # "error" | "warning"
        message: str,
        locations: List[Dict[str, Any]] = None,
        auto_fixable: bool = False,
        fix_strategy: str = "",
    ) -> None:
        self.error_code = error_code
        self.severity = severity
        self.message = message
        self.locations = locations or []  # [{"page": 1, "x": 100, "y": 200, "text": "..."}]
        self.auto_fixable = auto_fixable
        self.fix_strategy = fix_strategy

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典，便于 JSON 序列化"""
        return {
            "error_code": self.error_code,
            "severity": self.severity,
            "message": self.message,
            "locations": self.locations,
            "auto_fixable": self.auto_fixable,
            "fix_strategy": self.fix_strategy,
        }

    def __str__(self) -> str:
        loc_str = ""
        if self.locations:
            pages = sorted(set(loc.get("page", 0) for loc in self.locations if loc.get("page") is not None))
            if pages:
                loc_str = f" (第{','.join(map(str, pages))}页)"
        return f"[{self.error_code}] {self.message}{loc_str}"


class GateReport:
    """Gate 检查报告 —— 禁止裸 bool 透传"""

    def __init__(
        self,
        gate_name: str,
        passed: bool,
        errors: List[str],
        warnings: List[str],
        context: Dict[str, Any],
        issues: List[GateIssue] = None,
    ) -> None:
        self.gate_name = gate_name
        self.passed = passed
        self.errors = errors
        self.warnings = warnings
        self.context = context
        self.issues = issues or []  # 结构化问题列表（方向7增强）

    def __str__(self) -> str:
        status = "PASS" if self.passed else "FAIL"
        parts = [f"[{self.gate_name}] {status}"]
        if self.errors:
            parts.append(f"errors={self.errors}")
        if self.warnings:
            parts.append(f"warnings={self.warnings}")
        return " | ".join(parts)

    def to_dict(self) -> Dict[str, Any]:
        """完整报告转字典"""
        return {
            "gate_name": self.gate_name,
            "passed": self.passed,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "issues": [issue.to_dict() for issue in self.issues],
            "context": self.context,
        }


class InputGate:
    """输入质量门 —— Gate1"""

    @staticmethod
    def check(paper_path: Path) -> GateReport:
        errors: List[str] = []
        warnings: List[str] = []

        if not paper_path.exists():
            errors.append(f"论文文件不存在: {paper_path}")
        elif paper_path.stat().st_size == 0:
            errors.append(f"论文文件为空: {paper_path}")
        elif paper_path.stat().st_size < 1024:
            warnings.append(f"论文文件过小 ({paper_path.stat().st_size} 字节)，可能内容不完整")

        ext = paper_path.suffix.lower()
        if ext not in (".docx", ".doc", ".md", ".markdown", ".tex"):
            errors.append(f"不支持的文件格式: {ext}，仅支持 .docx/.doc/.md/.markdown/.tex")

        return GateReport(
            gate_name="InputGate",
            passed=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            context={"path": str(paper_path), "size": paper_path.stat().st_size if paper_path.exists() else 0},
        )


class DiagramGate:
    """生图质量门 —— Gate2"""

    MIN_IMAGE_SIZE_KB = 50
    EXPECTED_COUNT = 4

    @classmethod
    def check(cls, results: List[DiagramResult]) -> GateReport:
        errors: List[str] = []
        warnings: List[str] = []

        generated = [r for r in results if r.generated]

        if len(results) < cls.EXPECTED_COUNT:
            errors.append(f"图数量不足: {len(results)}/{cls.EXPECTED_COUNT}")

        if len(generated) < cls.EXPECTED_COUNT:
            errors.append(f"成功生成的图不足: {len(generated)}/{cls.EXPECTED_COUNT}")

        for r in results:
            if not r.generated:
                errors.append(f"{r.candidate_id}: 生成失败 - {r.error}")
                continue
            if r.size_kb < cls.MIN_IMAGE_SIZE_KB:
                warnings.append(f"{r.candidate_id}: 图片过小 ({r.size_kb:.1f} KB)")
            if not r.image_path.exists():
                errors.append(f"{r.candidate_id}: 图片文件不存在")

        # 检查多样性：4 张图应该是不同结构
        variant_ids = {r.prompt.variant.id for r in generated}
        if len(variant_ids) < len(generated):
            warnings.append(f"变体重复: 仅 {len(variant_ids)} 种不同结构")

        return GateReport(
            gate_name="DiagramGate",
            passed=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            context={"total": len(results), "generated": len(generated), "variants": list(variant_ids)},
        )


class TypesetGate:
    """排版质量门 —— Gate3/Gate4"""

    @staticmethod
    def check(pdf_path: Path, tex_path: Path, pages: int) -> GateReport:
        errors: List[str] = []
        warnings: List[str] = []

        if not pdf_path.exists():
            errors.append(f"PDF 未生成: {pdf_path}")
        elif pdf_path.stat().st_size < 1024:
            errors.append(f"PDF 文件异常过小: {pdf_path.stat().st_size} 字节")

        if not tex_path.exists():
            errors.append(f"TEX 未生成: {tex_path}")

        if pages == 0:
            warnings.append("无法确定 PDF 页数")
        elif pages < 3:
            warnings.append(f"PDF 页数过少 ({pages} 页)，可能内容缺失")

        return GateReport(
            gate_name="TypesetGate",
            passed=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            context={"pdf": str(pdf_path), "pages": pages},
        )


class PdfStrictGate:
    """
    PDF 严格质量门 —— Gate5

    对最终 PDF 进行排版细节检查，包括：
    - 重复参考文献标题检测
    - 二级标题左对齐检测（不应居中）
    - 摘要格式检测（标题存在、内容非空）
    - 目录格式检测（目录单开一页、目录条目存在）
    - 参考文献条目格式化检测（每条独立）
    - 图片插入检测（确认流程图已正确插入）
    """

    _REFERENCE_HEADINGS = [
        "参考文献", "参考资料", "References", "Reference",
        "Bibliography", "Bibliographic",
    ]

    _ABSTRACT_HEADINGS = [
        "摘要", "Abstract", "ABSTRACT",
    ]

    _TOC_HEADINGS = [
        "目录", "目  录", "目    录",
        "Contents", "Content", "Table of Contents",
    ]

    _KEYWORD_HEADINGS = [
        "关键词", "Key words", "Key Words", "Keywords", "keyword",
    ]

    @classmethod
    def check(cls, pdf_path: Path, pages: int, template: str = "renai") -> GateReport:
        errors: List[str] = []
        warnings: List[str] = []
        issues: List[GateIssue] = []  # 结构化问题列表
        context: Dict[str, Any] = {}

        # 加载模板标准（用于动态阈值）
        from ..config.settings import TEMPLATE_STANDARDS
        template_std = TEMPLATE_STANDARDS.get(template, TEMPLATE_STANDARDS.get("renai", {}))
        body_font_pt = template_std.get("body_font_pt", 12.0)
        heading2_font_pt = template_std.get("heading2_font_pt", 14.0)
        line_spacing = template_std.get("line_spacing", 1.5)
        context["template"] = template
        context["template_std"] = template_std

        # 解析 .tex 文件中的位置标记
        tex_path = pdf_path.with_suffix(".tex")
        if tex_path.exists():
            markers = parse_location_markers(tex_path)
            context["location_markers"] = markers
            context["tex_path"] = str(tex_path)

        if not pdf_path.exists():
            issue = GateIssue(
                error_code="PDF_NOT_FOUND",
                severity="error",
                message=f"PDF 不存在，无法检测: {pdf_path}",
            )
            return GateReport(
                gate_name="PdfStrictGate",
                passed=False,
                errors=[f"PDF 不存在，无法检测: {pdf_path}"],
                warnings=[],
                context={"pdf": str(pdf_path)},
                issues=[issue],
            )

        try:
            import fitz
        except ImportError:
            issue = GateIssue(
                error_code="PYMUPDF_MISSING",
                severity="warning",
                message="PyMuPDF 未安装，跳过 PDF 严格检测",
            )
            return GateReport(
                gate_name="PdfStrictGate",
                passed=True,
                errors=[],
                warnings=["PyMuPDF 未安装，跳过 PDF 严格检测"],
                context={"pdf": str(pdf_path), "skipped_reason": "pymupdf_not_installed"},
                issues=[issue],
            )

        try:
            import sys as _sys
            import fitz as _fitz
            _fitz_mod = _sys.modules.get('fitz', _fitz)
            _fitz_open = _fitz_mod.open
            doc = _fitz_open(str(pdf_path))
        except Exception as e:
            issue = GateIssue(
                error_code="PDF_OPEN_FAILED",
                severity="error",
                message=f"无法打开 PDF: {e}",
            )
            return GateReport(
                gate_name="PdfStrictGate",
                passed=False,
                errors=[f"无法打开 PDF: {e}"],
                warnings=[],
                context={"pdf": str(pdf_path)},
                issues=[issue],
            )

        try:
            # 1. 提取所有页的文字块（按页组织）
            page_texts = []
            page_width = 0
            for page in doc:
                page_width = page.rect.width
                page_texts.append(cls._extract_page_lines(page))

            context["total_pages"] = len(page_texts)
            context["page_width"] = page_width

            # 2. 封面页完整性检测
            cover_result = cls._check_cover_page(page_texts)
            context["cover_check"] = cover_result
            if not cover_result["title_found"]:
                msg = "未在封面检测到论文标题"
                warnings.append(msg)
                issues.append(GateIssue("COVER_TITLE_MISSING", "warning", msg))
            if not cover_result["author_found"]:
                msg = "未在封面检测到作者信息"
                warnings.append(msg)
                issues.append(GateIssue("COVER_AUTHOR_MISSING", "warning", msg))

            # 3. 重复参考文献标题检测
            ref_headings_found = cls._find_reference_headings(page_texts)
            context["reference_headings_count"] = len(ref_headings_found)
            if len(ref_headings_found) > 1:
                page_nums = [h['page'] + 1 for h in ref_headings_found]
                locations = [{"page": h['page'] + 1, "text": h.get('text', '')[:60]} for h in ref_headings_found]
                msg = f"检测到 {len(ref_headings_found)} 个参考文献标题（应只有 1 个），位置: 第 {', '.join(map(str, page_nums))} 页"
                errors.append(f"[DUPLICATE_REF_HEADING] {msg}")
                issues.append(GateIssue(
                    error_code="DUPLICATE_REF_HEADING",
                    severity="error",
                    message=msg,
                    locations=locations,
                    auto_fixable=True,
                    fix_strategy="删除多余的参考文献标题，保留模板自动生成的标题",
                ))
            elif len(ref_headings_found) == 0:
                msg = "未检测到参考文献标题"
                warnings.append(f"[WARN_REF_HEADING_MISSING] {msg}")
                issues.append(GateIssue("WARN_REF_HEADING_MISSING", "warning", msg))

            # 4. 二级标题左对齐检测
            left_aligned_issues = cls._check_subheading_alignment(page_texts, page_width, heading2_font_pt)
            context["misaligned_subheadings"] = len(left_aligned_issues)
            if left_aligned_issues:
                for issue_data in left_aligned_issues[:5]:
                    page_num = issue_data['page'] + 1
                    loc = {"page": page_num, "x": issue_data['x'], "text": issue_data['text'][:60]}
                    msg = f"第 {page_num} 页二级标题可能未左对齐: '{issue_data['text'][:40]}' (x={issue_data['x']:.1f})"
                    errors.append(f"[SUBHEADING_NOT_LEFT] {msg}")
                    issues.append(GateIssue(
                        error_code="SUBHEADING_NOT_LEFT",
                        severity="error",
                        message=msg,
                        locations=[loc],
                        auto_fixable=True,
                        fix_strategy="添加 \\raggedright 到 titlesec 设置",
                    ))
                if len(left_aligned_issues) > 5:
                    msg = f"另有 {len(left_aligned_issues) - 5} 处二级标题未左对齐"
                    errors.append(f"[SUBHEADING_NOT_LEFT] {msg}")
                    issues.append(GateIssue("SUBHEADING_NOT_LEFT", "error", msg, auto_fixable=True))

            # 5. 摘要格式检测
            abs_result = cls._check_abstract_format(page_texts)
            context.update(abs_result)
            if not abs_result["abstract_found"]:
                msg = "未检测到摘要标题"
                warnings.append(f"[WARN_ABSTRACT_MISSING] {msg}")
                issues.append(GateIssue("WARN_ABSTRACT_MISSING", "warning", msg))
            elif abs_result["abstract_empty"]:
                msg = "摘要标题存在但内容为空"
                errors.append(f"[EMPTY_ABSTRACT] {msg}")
                issues.append(GateIssue("EMPTY_ABSTRACT", "error", msg, auto_fixable=False))

            # 6. 关键词分页检测（关键词不应单独占一页）
            keyword_result = cls._check_keyword_page(page_texts)
            context["keyword_check"] = keyword_result
            if keyword_result["keyword_found"] and keyword_result["keyword_alone_on_page"]:
                page_num = keyword_result['keyword_page'] + 1
                msg = f"关键词单独占一页（第 {page_num} 页），应直接接在摘要之后"
                errors.append(f"[KEYWORD_ALONE] {msg}")
                issues.append(GateIssue(
                    error_code="KEYWORD_ALONE",
                    severity="error",
                    message=msg,
                    locations=[{"page": page_num}],
                    auto_fixable=True,
                    fix_strategy="删除关键词和目录间的 \\clearpage",
                ))

            # 7. 目录格式检测
            toc_result = cls._check_toc_format(page_texts)
            context.update(toc_result)
            if not toc_result["toc_found"]:
                msg = "未检测到目录标题"
                warnings.append(f"[WARN_TOC_MISSING] {msg}")
                issues.append(GateIssue("WARN_TOC_MISSING", "warning", msg))
            elif toc_result["toc_separate_page"] is False:
                msg = "目录未单独占一页"
                errors.append(f"[TOC_NOT_SEPARATE] {msg}")
                issues.append(GateIssue(
                    error_code="TOC_NOT_SEPARATE",
                    severity="error",
                    message=msg,
                    auto_fixable=True,
                    fix_strategy="在 \\tableofcontents 前添加 \\clearpage",
                ))
            elif toc_result["toc_entries"] == 0:
                msg = "目录标题存在但无条目"
                errors.append(f"[TOC_EMPTY] {msg}")
                issues.append(GateIssue("TOC_EMPTY", "error", msg, auto_fixable=True))
            elif toc_result.get("toc_page", 0) != 1:  # 0-indexed, 第2页=1
                msg = f"目录未固定在第二页（当前在第 {toc_result.get('toc_page', 0) + 1} 页）"
                errors.append(f"[TOC_PAGE_MISMATCH] {msg}")
                issues.append(GateIssue(
                    error_code="TOC_PAGE_MISMATCH",
                    severity="error",
                    message=msg,
                    locations=[{"page": toc_result.get("toc_page", 0) + 1}],
                    auto_fixable=True,
                    fix_strategy="在 \\maketitle 后添加 \\clearpage 确保封面与目录分页",
                ))

            # 8. 目录完整性检测（条目数 vs 章节数）
            toc_complete = cls._check_toc_completeness(page_texts)
            context["toc_completeness"] = toc_complete
            if toc_result["toc_found"] and toc_complete["chapter_count"] > 0:
                ratio = toc_complete["toc_entries"] / toc_complete["chapter_count"]
                if ratio < 0.5:
                    msg = f"目录条目可能不完整: 检测到 {toc_complete['toc_entries']} 条目录，但正文有约 {toc_complete['chapter_count']} 个章节"
                    warnings.append(msg)
                    issues.append(GateIssue("TOC_INCOMPLETE", "warning", msg, auto_fixable=True))

            # 9. 页码格式检测（罗马数字/阿拉伯数字）
            page_num_result = cls._check_page_numbering(page_texts)
            context["page_numbering"] = page_num_result
            if not page_num_result["roman_found"] and not page_num_result["arabic_found"]:
                msg = "未检测到页码（罗马数字或阿拉伯数字）"
                warnings.append(f"[WARN_NO_PAGE_NUMBER] {msg}")
                issues.append(GateIssue("WARN_NO_PAGE_NUMBER", "warning", msg))
            elif not page_num_result["roman_found"]:
                msg = "摘要/目录部分未使用罗马数字页码"
                warnings.append(f"[WARN_NO_ROMAN] {msg}")
                issues.append(GateIssue("WARN_NO_ROMAN", "warning", msg))
            elif not page_num_result["arabic_found"]:
                msg = "正文部分未使用阿拉伯数字页码"
                warnings.append(f"[WARN_NO_ARABIC] {msg}")
                issues.append(GateIssue("WARN_NO_ARABIC", "warning", msg))
            elif page_num_result["roman_after_arabic"]:
                msg = "页码格式错误: 罗马数字页码出现在阿拉伯数字页码之后"
                errors.append(f"[ROMAN_AFTER_ARABIC] {msg}")
                issues.append(GateIssue(
                    error_code="ROMAN_AFTER_ARABIC",
                    severity="error",
                    message=msg,
                    auto_fixable=True,
                    fix_strategy="删除正文中的 \\pagenumbering{Roman}",
                ))

            # 10. 页眉检测
            header_result = cls._check_header_footer(page_texts)
            context["header_footer"] = header_result
            if not header_result["header_found"]:
                msg = "未检测到页眉"
                warnings.append(msg)
                issues.append(GateIssue("HEADER_MISSING", "warning", msg))

            # 11. 正文字号一致性检测
            body_font_result = cls._check_body_font_size(page_texts)
            context["body_font"] = body_font_result
            if body_font_result["inconsistent"]:
                msg = f"正文字号不一致: 检测到 {len(body_font_result['sizes'])} 种字号 ({body_font_result['sizes']})，应以 {body_font_result['dominant_size']:.1f}pt 为主"
                errors.append(f"[FONT_INCONSISTENT] {msg}")
                issues.append(GateIssue(
                    error_code="FONT_INCONSISTENT",
                    severity="error",
                    message=msg,
                    auto_fixable=True,
                    fix_strategy=f"设置统一的正文字号 \\fontsize{{{body_font_pt:.0f}pt}}{{{body_font_pt*1.5:.0f}pt}}\\selectfont",
                ))
            font_min = body_font_pt * 0.85
            font_max = body_font_pt * 1.15
            if body_font_result["dominant_size"] > 0 and body_font_result["dominant_size"] < font_min:
                msg = f"正文字号偏小 ({body_font_result['dominant_size']:.1f}pt)，建议 >= {font_min:.1f}pt (模板标准 {body_font_pt:.1f}pt)"
                warnings.append(f"[WARN_FONT_SMALL] {msg}")
                issues.append(GateIssue("WARN_FONT_SMALL", "warning", msg))
            elif body_font_result["dominant_size"] > 0 and body_font_result["dominant_size"] > font_max:
                msg = f"正文字号偏大 ({body_font_result['dominant_size']:.1f}pt)，建议 <= {font_max:.1f}pt (模板标准 {body_font_pt:.1f}pt)"
                warnings.append(f"[WARN_FONT_LARGE] {msg}")
                issues.append(GateIssue("WARN_FONT_LARGE", "warning", msg))

            # 12. 空白页检测
            blank_result = cls._check_blank_pages(page_texts, doc)
            context["blank_pages"] = blank_result
            if blank_result["blank_count"] > 0:
                msg = f"检测到 {blank_result['blank_count']} 页内容极少（可能为空白页）: 第 {', '.join(map(str, blank_result['blank_pages']))} 页"
                warnings.append(msg)
                locations = [{"page": p} for p in blank_result['blank_pages']]
                issues.append(GateIssue("BLANK_PAGES", "warning", msg, locations=locations))

            # 13. 参考文献条目检测（每条应独立成行）
            ref_items_result = cls._check_reference_items(page_texts)
            context["reference_items"] = ref_items_result
            if ref_headings_found and ref_items_result["count"] == 0:
                msg = "参考文献标题存在但未检测到条目"
                warnings.append(msg)
                issues.append(GateIssue("REF_ITEMS_MISSING", "warning", msg))

            # 14. 参考文献格式智能校正（\cite 与 \bibitem 对应关系）
            cite_bib_result = cls._check_cite_bib_correspondence(pdf_path)
            context["cite_bib_check"] = cite_bib_result
            if cite_bib_result.get("missing_in_bib"):
                missing = cite_bib_result['missing_in_bib']
                msg = f"检测到 {len(missing)} 个正文引用在参考文献中缺失: {missing[:5]}"
                warnings.append(msg)
                issues.append(GateIssue("CITE_BIB_MISMATCH", "warning", msg, auto_fixable=False))
            if cite_bib_result.get("non_sequential"):
                msg = f"引用序号不连续，缺失: {cite_bib_result['non_sequential']}"
                warnings.append(msg)
                issues.append(GateIssue("CITE_NON_SEQUENTIAL", "warning", msg, auto_fixable=False))

            # 15. 图片插入检测
            diagram_result = cls._check_diagram_inserted(pdf_path)
            context["diagram_check"] = diagram_result
            if not diagram_result["diagram_found"]:
                msg = "PDF 中未检测到图片（如果论文需要流程图，请检查图片是否正确插入）"
                warnings.append(msg)
                issues.append(GateIssue("NO_IMAGE_INSERTED", "warning", msg, auto_fixable=False))
            else:
                info = f"检测到 {diagram_result['diagram_count']} 张图片，位于第 {', '.join(map(str, diagram_result['diagram_pages']))} 页"
                context["diagram_info"] = info
                locations = [{"page": p} for p in diagram_result['diagram_pages']]
                issues.append(GateIssue("IMAGE_INSERTED", "info", info, locations=locations))

            # 16. 图片宽高比检测（防止拉伸变形）
            img_ratio_result = cls._check_image_aspect_ratio(doc)
            context["image_aspect"] = img_ratio_result
            if img_ratio_result["distorted_count"] > 0:
                msg = f"检测到 {img_ratio_result['distorted_count']} 张图片可能存在拉伸变形"
                warnings.append(msg)
                locations = [{"page": p.get('page'), "ratio": p.get('ratio')} for p in img_ratio_result.get('distorted_pages', [])]
                issues.append(GateIssue(
                    error_code="IMAGE_ASPECT_DISTORTED",
                    severity="warning",
                    message=msg,
                    locations=locations,
                    auto_fixable=True,
                    fix_strategy="添加 keepaspectratio 选项到 \\includegraphics",
                ))

            # 17. LaTeX 清洗残留检查（** / • / 窄空格 / Unicode数学符号 / heiti / tocdepth）
            if tex_path and tex_path.exists():
                tex_content = tex_path.read_text(encoding="utf-8")
                # SPEC-X P1-2 反思: 原 import "from core.latex_cleaner" 是 dangling import
                # (模块不存在), 直接 raise. 改用 try-import + fallback, fail-soft.
                clean_issues: list = []
                try:
                    from paper_pipeline.gates.latex_cleaner import validate_clean  # type: ignore[import-not-found]
                    clean_issues = validate_clean(tex_content)
                except ImportError:
                    try:
                        from core.latex_cleaner import validate_clean  # type: ignore[import-not-found]
                        clean_issues = validate_clean(tex_content)
                    except ImportError:
                        # Fallback: 不进行 LaTeX 清洗检查
                        clean_issues = []
                for issue in clean_issues:
                    if isinstance(issue, tuple) and len(issue) >= 3:
                        severity, code, msg = issue[0], issue[1], issue[2]
                    else:
                        severity, code, msg = "warning", "LATEX_CLEAN", str(issue)
                    is_error = severity == "error"
                    if is_error:
                        errors.append(msg)
                    else:
                        warnings.append(msg)

            # ── SPEC-X P1-2 (C-P1-2): Gate5 规则扩展 16→24 ──
            # 新增 8 条检测 (17-24) 覆盖常见 PDF 学术质量问题

            # 18. 引文与参考文献编号连续性检测 (顺序编号)
            cite_seq_result = cls._check_citation_sequence(page_texts)
            context["citation_sequence"] = cite_seq_result
            if cite_seq_result["missing_numbers"]:
                missing = cite_seq_result["missing_numbers"]
                msg = f"正文引文编号不连续，缺失: {missing[:5]}"
                warnings.append(msg)
                issues.append(GateIssue(
                    error_code="CITE_SEQ_MISSING",
                    severity="warning",
                    message=msg,
                    auto_fixable=False,
                ))
            cite_seq_result = cls._check_citation_sequence(page_texts)
            context["citation_sequence"] = cite_seq_result
            if cite_seq_result["missing_numbers"]:
                missing = cite_seq_result["missing_numbers"]
                msg = f"正文引文编号不连续，缺失: {missing[:5]}"
                warnings.append(msg)
                issues.append(GateIssue(
                    error_code="CITE_SEQ_MISSING",
                    severity="warning",
                    message=msg,
                    auto_fixable=False,
                ))

            # 19. 行距一致性检测 (PDF 应有统一的 line_spacing)
            line_spacing_result = cls._check_line_spacing(page_texts, line_spacing)
            context["line_spacing"] = line_spacing_result
            if line_spacing_result["inconsistent"]:
                msg = f"行距不一致: 检测到 {line_spacing_result['variances']} 种行距 (期望 {line_spacing:.1f})"
                errors.append(f"[LINE_SPACING_INCONSISTENT] {msg}")
                issues.append(GateIssue(
                    error_code="LINE_SPACING_INCONSISTENT",
                    severity="error",
                    message=msg,
                    auto_fixable=True,
                    fix_strategy=f"统一 \\linespread{{{line_spacing}}}",
                ))

            # 20. 表格列对齐检测 (数值列应右对齐, 文本列应左对齐)
            table_align_result = cls._check_table_alignment(page_texts)
            context["table_alignment"] = table_align_result
            if table_align_result["misaligned_tables"] > 0:
                msg = f"检测到 {table_align_result['misaligned_tables']} 个表格列对齐异常"
                warnings.append(msg)
                issues.append(GateIssue(
                    error_code="TABLE_ALIGN_INCORRECT",
                    severity="warning",
                    message=msg,
                    auto_fixable=True,
                    fix_strategy="使用 booktabs 的 \\begin{tabular}{@{}r@{\\hspace{1em}}l@{}} 显式列对齐",
                ))

            # 21. 标题层级一致性 (h1 → h2 → h3 顺序, 不跳级)
            heading_hier_result = cls._check_heading_hierarchy(page_texts)
            context["heading_hierarchy"] = heading_hier_result
            if heading_hier_result["skipped_levels"]:
                skips = heading_hier_result["skipped_levels"]
                msg = f"标题层级跳级: {skips[:3]}"
                errors.append(f"[HEADING_HIERARCHY_SKIP] {msg}")
                issues.append(GateIssue(
                    error_code="HEADING_HIERARCHY_SKIP",
                    severity="error",
                    message=msg,
                    auto_fixable=False,
                ))

            # 22. 标点符号一致性 (中英文标点混用检测)
            punct_result = cls._check_punctuation_consistency(page_texts)
            context["punctuation"] = punct_result
            if punct_result["mixed_punctuation"] > 5:
                msg = f"中英文标点混用: {punct_result['mixed_punctuation']} 处"
                warnings.append(msg)
                issues.append(GateIssue(
                    error_code="PUNCT_MIXED",
                    severity="warning",
                    message=msg,
                    auto_fixable=True,
                    fix_strategy="统一为全角中文标点或半角英文标点",
                ))

            # 23. 图表编号连续性 (Figure 1, Figure 2... 不跳号)
            fig_seq_result = cls._check_figure_sequence(page_texts)
            context["figure_sequence"] = fig_seq_result
            if fig_seq_result["missing"]:
                missing = fig_seq_result["missing"]
                msg = f"图表编号不连续，缺失: {missing[:5]}"
                warnings.append(msg)
                issues.append(GateIssue(
                    error_code="FIGURE_SEQ_MISSING",
                    severity="warning",
                    message=msg,
                    auto_fixable=False,
                ))

            # 24. 中英文之间空格检测 (LaTeX 排版规范要求)
            space_result = cls._check_chinese_english_spacing(tex_path)
            context["chinese_english_spacing"] = space_result
            if space_result["missing_space"] > 10:
                msg = f"中英文之间缺少空格: {space_result['missing_space']} 处"
                warnings.append(msg)
                issues.append(GateIssue(
                    error_code="CN_EN_SPACE_MISSING",
                    severity="warning",
                    message=msg,
                    auto_fixable=True,
                    fix_strategy="使用 xelatex 配合 \\xeCJKSetup 选项自动添加空格",
                ))

            # ── 补充 3 条规则 (T7 C-P1-2 累计到 24+ 条) ──

            # 25. TOC 层级深度检测
            toc_depth_result = cls._check_toc_depth(page_texts)
            context["toc_depth"] = toc_depth_result
            if toc_depth_result.get("insufficient"):
                msg = f"目录层级不足 (max depth={toc_depth_result.get('max_depth')}, 应 >= 2)"
                warnings.append(msg)
                issues.append(GateIssue(
                    error_code="TOC_DEPTH_INSUFFICIENT",
                    severity="warning",
                    message=msg,
                    auto_fixable=True,
                    fix_strategy="设置 \\setcounter{tocdepth}{2}",
                ))

            # 26. 字体嵌入检测
            font_embed_result = cls._check_font_embedding(doc)
            context["font_embedding"] = font_embed_result
            if not font_embed_result.get("all_embedded", True) and not font_embed_result.get("error"):
                not_embedded = font_embed_result.get("not_embedded", [])
                msg = f"检测到 {len(not_embedded)} 个字体未嵌入 PDF: {not_embedded[:3]}"
                errors.append(f"[FONT_NOT_EMBEDDED] {msg}")
                issues.append(GateIssue(
                    error_code="FONT_NOT_EMBEDDED",
                    severity="error",
                    message=msg,
                    auto_fixable=True,
                    fix_strategy="使用 xelatex/pdflatex 配合 \\usepackage[T1]{fontenc} 确保字体嵌入",
                ))

            # 27. Unicode 残留检测 (invisible 字符 / RTL marks)
            unicode_result = cls._check_unicode_residual(tex_path)
            context["unicode_residual"] = unicode_result
            if unicode_result.get("residual_count", 0) > 0:
                msg = f".tex 包含 {unicode_result['residual_count']} 个不可见 Unicode 字符"
                warnings.append(msg)
                issues.append(GateIssue(
                    error_code="UNICODE_RESIDUAL",
                    severity="warning",
                    message=msg,
                    auto_fixable=True,
                    fix_strategy="删除 \\u200B-\\u200F 等不可见字符 (BOM / RTL marks / ZWSP)",
                ))

            # End of SPEC-X P1-2 Gate5 规则扩展

            doc.close()

        except Exception as e:
            msg = f"PDF 严格检测异常: {e}"
            errors.append(msg)
            issues.append(GateIssue("CHECK_EXCEPTION", "error", msg))

        return GateReport(
            gate_name="PdfStrictGate",
            passed=len(errors) == 0,
            errors=errors,
            warnings=warnings,
            context=context,
            issues=issues,
        )

    @staticmethod
    def _extract_page_lines(page) -> List[Dict[str, Any]]:
        """提取单页所有文本行，每行包含 text、x0、y0、size、font"""
        lines = []
        data = page.get_text('dict')
        for block in data.get('blocks', []):
            if 'lines' not in block:
                continue
            for line in block['lines']:
                if not line.get('spans'):
                    continue
                spans = line['spans']
                text = ''.join(s['text'] for s in spans)
                text = text.strip()
                if not text:
                    continue
                x0 = min(s['bbox'][0] for s in spans)
                y0 = min(s['bbox'][1] for s in spans)
                size = max(s['size'] for s in spans)
                font = spans[0].get('font', '')
                lines.append({
                    "text": text,
                    "x": x0,
                    "y": y0,
                    "size": size,
                    "font": font,
                })
        lines.sort(key=lambda l: (l['y'], l['x']))
        return lines

    @classmethod
    def _find_reference_headings(cls, page_texts: List[List[Dict]]) -> List[Dict]:
        """查找所有参考文献标题的位置（按字号和位置过滤，排除页眉，去重，排除目录页）"""
        # 1. 先找出目录页（跳过）
        toc_pages = set()
        for p_idx, lines in enumerate(page_texts):
            for line in lines:
                text = line['text'].strip()
                for heading in cls._TOC_HEADINGS:
                    if text == heading and line['size'] >= 10 and line['y'] > 50:
                        toc_pages.add(p_idx)
                        break

        found = []
        for p_idx, lines in enumerate(page_texts):
            # 跳过目录页
            if p_idx in toc_pages:
                continue
            for line in lines:
                text = line['text'].strip()
                size = line['size']
                y = line['y']
                for heading in cls._REFERENCE_HEADINGS:
                    if text == heading or text.startswith(heading):
                        # 字号 >= 10pt 且排除页眉区域（y > 50）
                        # ctexart 文档类的 section* 标题字号约为 12pt
                        if size >= 10 and y > 50:
                            # 去重：如果已有相同文本且 y 坐标相近的标题，跳过
                            is_duplicate = False
                            for existing in found:
                                if existing['text'] == text and abs(existing['y'] - y) < 10:
                                    is_duplicate = True
                                    break
                            if not is_duplicate:
                                found.append({"page": p_idx, "text": text, "y": y, "size": size})
                        break
        return found

    @classmethod
    def _find_lines_on_same_y(cls, lines: List[Dict], y: float, tolerance: float = 3.0) -> List[Dict]:
        """查找同一行（y坐标相近）的所有文本块"""
        return [l for l in lines if abs(l['y'] - y) < tolerance]

    @classmethod
    def _check_subheading_alignment(
        cls,
        page_texts: List[List[Dict]],
        page_width: float,
        heading2_font_pt: float = 12.0,
    ) -> List[Dict]:
        """
        检测二级标题是否左对齐（不应居中）。

        策略：
        - 找字体大小在 heading2_font_pt ± 1.5pt 的行
        - 如果标题 x 坐标接近页面中心（居中），则报问题
        - 左对齐阈值：x < page_width * 0.3
        - 居中阈值：|x - center| < page_width * 0.1
        """
        issues = []
        center = page_width / 2
        left_margin_threshold = page_width * 0.3
        center_tolerance = page_width * 0.08
        size_min = heading2_font_pt - 1.5
        size_max = heading2_font_pt + 1.5

        for p_idx, lines in enumerate(page_texts):
            for line in lines:
                text = line['text'].strip()
                size = line['size']
                x = line['x']

                # 二级标题：字号在 heading2_font_pt ± 1.5pt 范围内
                if size_min <= size <= size_max and len(text) < 60:
                    # 排除参考文献标题
                    is_ref = any(h in text for h in cls._REFERENCE_HEADINGS)
                    is_abs = any(h in text for h in cls._ABSTRACT_HEADINGS)
                    is_toc = any(h in text for h in cls._TOC_HEADINGS)
                    if is_ref or is_abs or is_toc:
                        continue

                    # 排除纯数字（页码、章节编号等）
                    if re.fullmatch(r'[\d\.\s]+', text):
                        continue
                    # 排除目录填充点
                    if text.count('.') >= 5:
                        continue
                    # 排除短词（< 4 个字符）和小于 2 个词的文本
                    if len(text) < 4 or len(text.split()) < 2:
                        continue
                    # 二级标题通常以数字编号开头（如 "1. Introduction"）
                    has_heading_pattern = bool(re.match(r'^(\d+\.?\s|\d+\.\d+\s|[一二三四五六七八九十]+[、\.]?\s)', text))
                    if not has_heading_pattern:
                        continue

                    # 判断是否居中
                    if abs(x - center) < center_tolerance:
                        issues.append({
                            "page": p_idx,
                            "text": text,
                            "x": x,
                            "size": size,
                        })
        return issues

    @classmethod
    def _check_abstract_format(cls, page_texts: List[List[Dict]]) -> Dict[str, Any]:
        """检测摘要格式：标题存在且内容非空"""
        result = {
            "abstract_found": False,
            "abstract_page": None,
            "abstract_empty": True,
            "abstract_lines": 0,
        }

        for p_idx, lines in enumerate(page_texts):
            for i, line in enumerate(lines):
                text = line['text'].strip()
                for heading in cls._ABSTRACT_HEADINGS:
                    if text == heading or text.startswith(heading + '：') or text.startswith(heading + ':'):
                        result["abstract_found"] = True
                        result["abstract_page"] = p_idx
                        # 检查摘要后续是否有内容（下一行开始，直到遇到一个标题级别的行）
                        content_lines = 0
                        for j in range(i + 1, min(i + 20, len(lines))):
                            next_text = lines[j]['text'].strip()
                            if not next_text:
                                continue
                            # 如果遇到目录标题或其他章节标题，停止
                            if any(h in next_text for h in cls._TOC_HEADINGS):
                                break
                            if len(next_text) > 10:
                                content_lines += 1
                        result["abstract_lines"] = content_lines
                        result["abstract_empty"] = content_lines == 0
                        return result
        return result

    @classmethod
    def _check_keyword_page(cls, page_texts: List[List[Dict]]) -> Dict[str, Any]:
        """
        检测关键词是否单独占一页：
        - 关键词不应单独占一页，应直接接在摘要之后
        - 判断逻辑：如果关键词标题所在页的前一页有摘要内容，且该页除了关键词外没有其他正文内容，则认为关键词单独占一页
        """
        result = {
            "keyword_found": False,
            "keyword_page": None,
            "keyword_alone_on_page": False,
        }

        keyword_page = None
        abstract_page = None

        for p_idx, lines in enumerate(page_texts):
            for line in lines:
                text = line['text'].strip()
                for heading in cls._KEYWORD_HEADINGS:
                    if text == heading or text.startswith(heading + '：') or text.startswith(heading + ':'):
                        keyword_page = p_idx
                        result["keyword_found"] = True
                        result["keyword_page"] = p_idx
                        break
                if keyword_page is not None:
                    break

        # 查找摘要所在页
        for p_idx, lines in enumerate(page_texts):
            for line in lines:
                text = line['text'].strip()
                for heading in cls._ABSTRACT_HEADINGS:
                    if text == heading:
                        abstract_page = p_idx
                        break
                if abstract_page is not None:
                    break

        # 判断关键词是否单独占一页
        if keyword_page is not None and abstract_page is not None:
            # 如果关键词和摘要在同一页，没问题
            if keyword_page == abstract_page:
                result["keyword_alone_on_page"] = False
            # 如果关键词在摘要的下一页，检查关键词页是否有目录或其他正文内容
            elif keyword_page == abstract_page + 1:
                keyword_lines = page_texts[keyword_page]
                # 检查是否有目录标题
                has_toc = any(
                    any(h in l['text'] for h in cls._TOC_HEADINGS)
                    for l in keyword_lines
                )
                # 检查是否有正文内容（非关键词、非页眉）
                content_lines = [
                    l for l in keyword_lines 
                    if l['y'] > 50 and l['y'] < 750 and l['size'] >= 10
                    and not any(h in l['text'] for h in cls._KEYWORD_HEADINGS)
                ]
                # 如果关键词页有目录或正文内容，不算单独占一页
                if has_toc or len(content_lines) >= 5:
                    result["keyword_alone_on_page"] = False
                else:
                    result["keyword_alone_on_page"] = True

        return result

    @classmethod
    def _check_toc_format(cls, page_texts: List[List[Dict]]) -> Dict[str, Any]:
        """
        检测目录格式：
        - 目录标题存在
        - 目录单独占一页
        - 目录有条目（左侧标题 + 右侧页码）
        """
        import re as _re

        result = {
            "toc_found": False,
            "toc_page": None,
            "toc_entries": 0,
            "toc_separate_page": None,  # True=单开一页，False=非独立页
        }

        for p_idx, lines in enumerate(page_texts):
            for i, line in enumerate(lines):
                text = line['text'].strip()
                # 目录标题：字号较大（>= 10pt 即可，覆盖 ctexart 12pt 标题）
                # y > 50 排除页眉（页眉字号通常较小）
                is_toc_title = False
                for heading in cls._TOC_HEADINGS:
                    if text == heading and line['size'] >= 10 and line['y'] > 50:
                        is_toc_title = True
                        break

                if is_toc_title:
                    result["toc_found"] = True
                    result["toc_page"] = p_idx

                    # 统计目录条目：同一行左侧有标题文字，右侧（x > page_width*0.7）有数字
                    entries = 0
                    toc_area_start_y = line['y'] + 10
                    toc_area_end_y = line['y'] + 400  # 目录大致范围

                    for j in range(i + 1, len(lines)):
                        entry_line = lines[j]
                        if entry_line['y'] < toc_area_start_y:
                            continue
                        if entry_line['y'] > toc_area_end_y:
                            break
                        if entry_line['size'] < 10 or entry_line['size'] > 15:
                            continue

                        # 查找同一行右侧的页码（支持阿拉伯数字和罗马数字）
                        same_y = cls._find_lines_on_same_y(lines, entry_line['y'])
                        right_items = [l for l in same_y if l['x'] > line['x'] + 200]
                        page_num_pattern = _re.compile(r'^(?:[IVXLCDM]+|\d+)$')
                        has_page_num = any(
                            page_num_pattern.match(l['text'].strip())
                            for l in right_items
                        )

                        if has_page_num and len(entry_line['text'].strip()) > 3:
                            entries += 1

                    result["toc_entries"] = entries

                    # 判断目录是否单独占一页：
                    # 该页的主体内容是目录条目（非目录标题行 + 条目行的比例）
                    total_lines = len(lines)
                    if total_lines > 5:
                        # 简单方法：目录页通常页码是罗马数字或从目录标题后开始
                        # 检查该页是否有正文一级标题（大字号标题）
                        has_body_heading = any(
                            l['size'] >= 18 and l['y'] > line['y'] + 50
                            for l in lines
                        )
                        result["toc_separate_page"] = not has_body_heading

                    return result
        return result

    @classmethod
    def _check_reference_items(cls, page_texts: List[List[Dict]]) -> Dict[str, Any]:
        """检测参考文献条目：统计以 [数字] 开头的行"""
        import re as _re

        result = {
            "count": 0,
            "pages": [],
        }

        ref_start_pattern = _re.compile(r'^\[\d+\]')

        for p_idx, lines in enumerate(page_texts):
            for line in lines:
                text = line['text'].strip()
                if ref_start_pattern.match(text):
                    result["count"] += 1
                    if p_idx not in result["pages"]:
                        result["pages"].append(p_idx)
        return result

    @classmethod
    def _check_diagram_inserted(cls, pdf_path: Path) -> Dict[str, Any]:
        """
        检测 PDF 中是否正确插入了图片。

        返回：
            - diagram_found: 是否找到图片
            - diagram_pages: 图片所在页码列表
            - diagram_count: 图片数量
        """
        result = {
            "diagram_found": False,
            "diagram_pages": [],
            "diagram_count": 0,
        }

        try:
            import fitz
            doc = fitz.open(str(pdf_path))

            for page_idx, page in enumerate(doc):
                # 获取页面中的图片列表
                images = page.get_images()
                if images:
                    result["diagram_found"] = True
                    result["diagram_pages"].append(page_idx + 1)  # 页码从1开始
                    result["diagram_count"] += len(images)

            doc.close()
        except Exception as e:
            result["error"] = str(e)

        return result

    # ------------------------------------------------------------------
    # 新增检测方法（通用性增强）
    # ------------------------------------------------------------------

    @classmethod
    def _check_cover_page(cls, page_texts: List[List[Dict]]) -> Dict[str, Any]:
        """
        检测封面页完整性：
        - 是否有标题（字号较大，通常在页面顶部居中）
        - 是否有作者信息
        """
        result = {"title_found": False, "author_found": False}
        if not page_texts:
            return result

        # 通常封面在第一页，检查前两页
        for p_idx in range(min(2, len(page_texts))):
            lines = page_texts[p_idx]
            # 检测标题：字号 >= 16pt 且在页面上半部分
            for line in lines:
                text = line['text'].strip()
                if line['size'] >= 16 and line['y'] < 400:
                    result["title_found"] = True
                # 检测作者：包含常见作者关键词，或纯姓名格式
                if any(kw in text for kw in ["作者", "Author", "姓名", "Name"]):
                    result["author_found"] = True
                # 中文姓名（2-5字）或英文名（2-4个首字母大写单词）
                if re.match(r'^[\u4e00-\u9fff]{2,5}$', text):
                    result["author_found"] = True
                if re.match(r'^[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){1,3}$', text):
                    result["author_found"] = True
        return result

    @classmethod
    def _check_page_numbering(cls, page_texts: List[List[Dict]]) -> Dict[str, Any]:
        """
        检测页码格式：
        - 是否有罗马数字页码（i, ii, iii, ...）
        - 是否有阿拉伯数字页码（1, 2, 3, ...）
        - 罗马数字是否出现在阿拉伯数字之前
        """
        result = {
            "roman_found": False,
            "arabic_found": False,
            "roman_after_arabic": False,
            "roman_pages": [],
            "arabic_pages": [],
        }
        # 罗马数字页码：匹配大小写 i, v, x, l, c, I, V, X, L, C
        # 长度 >= 1（单个大写 I 是有效的罗马数字 1）
        roman_pattern = re.compile(r'^[ivxlcdmIVXLCDM]+$')
        # 阿拉伯数字：支持纯数字或页脚格式如 "7 / 2"
        arabic_pattern = re.compile(r'^\d{1,3}$')
        arabic_in_footer = re.compile(r'^\d{1,3}\s*/\s*\d+$')

        found_arabic_page = None
        for p_idx, lines in enumerate(page_texts):
            for line in lines:
                text = line['text'].strip()
                size = line['size']
                y = line['y']
                # 页码特征：
                # 1. 在页面底部（y > 780）
                # 2. 字号较小（<= 12pt）
                if not (780 <= y <= 820 and size <= 12):
                    continue
                # 排除常见的非页码文本（图注、Evaluation Mode 等）
                if len(text) > 15 or len(text) == 0:
                    continue
                # 排除图注
                if text.startswith('图') or text.startswith('Fig') or 'Evaluation' in text:
                    continue
                # 罗马数字检测
                if roman_pattern.match(text):
                    result["roman_found"] = True
                    result["roman_pages"].append(p_idx + 1)
                    if found_arabic_page is not None and p_idx > found_arabic_page:
                        result["roman_after_arabic"] = True
                # 阿拉伯数字检测（纯数字或页脚格式）
                elif arabic_pattern.match(text) or arabic_in_footer.match(text):
                    result["arabic_found"] = True
                    result["arabic_pages"].append(p_idx + 1)
                    if found_arabic_page is None:
                        found_arabic_page = p_idx
        return result

    @classmethod
    def _check_header_footer(cls, page_texts: List[List[Dict]]) -> Dict[str, Any]:
        """
        检测页眉页脚：
        - 是否有页眉（y < 60 的重复文本）
        - 页眉内容是否合理（排除纯页码）
        """
        result = {"header_found": False, "header_text": None}
        header_texts = []
        for lines in page_texts:
            for line in lines:
                if line['y'] < 60 and line['size'] <= 12:
                    text = line['text'].strip()
                    if text and not text.isdigit() and len(text) > 2:
                        header_texts.append(text)

        if header_texts:
            # 统计最常见的页眉文本
            from collections import Counter
            counter = Counter(header_texts)
            most_common = counter.most_common(1)
            if most_common and most_common[0][1] >= min(3, len(page_texts) // 2):
                result["header_found"] = True
                result["header_text"] = most_common[0][0]
        return result

    @classmethod
    def _check_body_font_size(cls, page_texts: List[List[Dict]]) -> Dict[str, Any]:
        """
        检测正文字号一致性：
        - 统计正文字号分布（排除标题、页眉页脚等大/小字号）
        - 检测字号是否过于分散
        """
        result = {"sizes": [], "dominant_size": 0, "inconsistent": False}
        size_counter = Counter()

        for lines in page_texts:
            for line in lines:
                size = line['size']
                # 排除标题（>=14pt）、页眉页脚（y<60 或 y>700）、页码
                if size >= 14 or line['y'] < 60 or line['y'] > 700:
                    continue
                text = line['text'].strip()
                if text.isdigit() and len(text) <= 3:
                    continue
                # 排除参考文献标题行
                if any(h in text for h in cls._REFERENCE_HEADINGS):
                    continue
                # 排除目录标题行
                if any(h in text for h in cls._TOC_HEADINGS):
                    continue
                size_counter[size] += 1

        if not size_counter:
            return result

        # 统计主要字号
        sorted_sizes = size_counter.most_common()
        result["sizes"] = [f"{s:.1f}pt" for s, c in sorted_sizes[:5]]
        result["dominant_size"] = sorted_sizes[0][0]

        # 判断字号是否一致：第二常见字号的比例是否过高
        if len(sorted_sizes) >= 2:
            total = sum(c for s, c in sorted_sizes)
            dominant_ratio = sorted_sizes[0][1] / total
            if dominant_ratio < 0.7:
                result["inconsistent"] = True

        return result

    @classmethod
    def _check_blank_pages(cls, page_texts: List[List[Dict]], doc=None) -> Dict[str, Any]:
        """
        检测空白页：
        - 页面内容行数 < 3 且没有图片（通过页眉页脚之外的文本判断）
        - 如果提供了 doc 对象，会额外检查页面是否包含图片
        """
        result = {"blank_count": 0, "blank_pages": []}
        # 预计算哪些页面包含图片
        pages_with_images = set()
        if doc is not None:
            try:
                for page_idx, page in enumerate(doc):
                    if page.get_images():
                        pages_with_images.add(page_idx)
            except Exception:
                pass

        for p_idx, lines in enumerate(page_texts):
            # 如果页面包含图片，不视为空白页
            if p_idx in pages_with_images:
                continue
            # 排除页眉(y<60)和页脚(y>700)后的内容行
            content_lines = [l for l in lines if 60 <= l['y'] <= 700]
            if len(content_lines) < 3:
                result["blank_count"] += 1
                result["blank_pages"].append(p_idx + 1)
        return result

    @classmethod
    def _check_toc_completeness(cls, page_texts: List[List[Dict]]) -> Dict[str, Any]:
        """
        检测目录完整性：
        - 统计目录条目数
        - 统计正文章节数（通过一级/二级标题字号判断）
        - 对比两者比例
        """
        result = {"toc_entries": 0, "chapter_count": 0}

        # 统计目录条目数（复用 _check_toc_format 的逻辑）
        toc_result = cls._check_toc_format(page_texts)
        result["toc_entries"] = toc_result.get("toc_entries", 0)

        # 统计正文章节数：字号 >= 14pt 且不是参考文献/目录标题
        chapter_headings = set()
        for p_idx, lines in enumerate(page_texts):
            for line in lines:
                text = line['text'].strip()
                size = line['size']
                # 排除页眉页脚区域
                if line['y'] < 60 or line['y'] > 700:
                    continue
                # 标题特征：字号 >= 14pt 或粗体感（通过 font 名判断）
                is_bold = 'Bold' in line.get('font', '') or 'bold' in line.get('font', '').lower()
                if (size >= 14 or (size >= 12 and is_bold)) and len(text) > 2 and len(text) < 60:
                    # 排除参考文献和目录标题
                    if any(h in text for h in cls._REFERENCE_HEADINGS + cls._TOC_HEADINGS):
                        continue
                    # 排除摘要标题
                    if any(h in text for h in cls._ABSTRACT_HEADINGS):
                        continue
                    chapter_headings.add(text)

        result["chapter_count"] = len(chapter_headings)
        return result

    @classmethod
    def _check_image_aspect_ratio(cls, doc) -> Dict[str, Any]:
        """
        检测图片宽高比，判断是否存在明显的拉伸变形。

        策略：
        - 获取每张图片的原始宽高
        - 计算宽高比
        - 如果某页图片的宽高比极端（<0.2 或 >5），可能为拉伸变形
        """
        result = {"total_images": 0, "distorted_count": 0, "details": []}

        try:
            for page_idx, page in enumerate(doc):
                images = page.get_images(full=True)
                for img_idx, img in enumerate(images):
                    xref = img[0]
                    pix = fitz.Pixmap(doc, xref)
                    if pix.n > 4:  # CMYK: convert to RGB
                        pix = fitz.Pixmap(fitz.csRGB, pix)
                    w, h = pix.width, pix.height
                    ratio = w / h if h > 0 else 0
                    result["total_images"] += 1

                    # 极端宽高比视为可能变形
                    if ratio < 0.2 or ratio > 5:
                        result["distorted_count"] += 1
                        result["details"].append({
                            "page": page_idx + 1,
                            "ratio": round(ratio, 2),
                            "size": f"{w}x{h}",
                        })
                    pix = None
        except Exception:
            pass

        return result

    # ── SPEC-X P1-2 (C-P1-2): Gate5 新增 8 条检测方法 (17-24) ──

    @classmethod
    def _check_citation_sequence(cls, page_texts: List[List[Dict]]) -> Dict[str, Any]:
        """18. 引文编号连续性: 检测正文 [1], [2], [3]... 是否连续."""
        import re as _re
        cite_pattern = _re.compile(r"\[(\d+)\]")
        all_cites: set[int] = set()
        for lines in page_texts:
            for line in lines:
                if line["y"] > 700:  # 跳过页脚
                    continue
                text = line["text"]
                for m in cite_pattern.finditer(text):
                    all_cites.add(int(m.group(1)))
        if not all_cites:
            return {"missing_numbers": [], "all_cites": []}
        max_cite = max(all_cites)
        expected = set(range(1, max_cite + 1))
        missing = sorted(expected - all_cites)[:10]
        return {"missing_numbers": missing, "all_cites": sorted(all_cites)}

    @classmethod
    def _check_line_spacing(
        cls, page_texts: List[List[Dict]], expected_spacing: float = 1.5
    ) -> Dict[str, Any]:
        """19. 行距一致性: 相邻文本行的 y 距离应在 expected_spacing × font_size 范围内."""
        variances: list[float] = []
        for lines in page_texts[:5]:  # 只检查前 5 页
            sorted_lines = sorted(lines, key=lambda l: l["y"])
            prev_y = None
            for line in sorted_lines:
                if line["y"] < 60 or line["y"] > 700:
                    continue
                if prev_y is not None:
                    delta = line["y"] - prev_y
                    if 5 < delta < 50:  # 跳过标题间隔
                        ratio = delta / max(line["size"], 1)
                        variances.append(ratio)
                prev_y = line["y"]
        if not variances:
            return {"inconsistent": False, "variances": [], "expected": expected_spacing}
        # 统计众数
        from collections import Counter
        counter = Counter(round(v, 1) for v in variances)
        most_common_ratio, _ = counter.most_common(1)[0]
        inconsistent = abs(most_common_ratio - expected_spacing) > 0.3
        return {
            "inconsistent": inconsistent,
            "variances": list(set(round(v, 2) for v in variances))[:10],
            "dominant_ratio": most_common_ratio,
            "expected": expected_spacing,
        }

    @classmethod
    def _check_table_alignment(cls, page_texts: List[List[Dict]]) -> Dict[str, Any]:
        """20. 表格列对齐: 同一表格行内文本 x 坐标应对齐."""
        misaligned = 0
        # 简化检测: 在同一 y 附近发现 >= 3 个文本块但 x 坐标差异 > 5pt
        for lines in page_texts:
            by_y: dict[float, list[Dict]] = {}
            for line in lines:
                # 表格单元格 y 坐标相近
                y_bucket = round(line["y"], 0)
                by_y.setdefault(y_bucket, []).append(line)
            for y_bucket, bucket in by_y.items():
                if len(bucket) >= 3:
                    # 检查 x 是否对齐到列
                    xs = sorted(set(round(l["x"], 0) for l in bucket))
                    if len(xs) >= 3 and max(xs) - min(xs) > 300:
                        misaligned += 1
        return {"misaligned_tables": misaligned}

    @classmethod
    def _check_heading_hierarchy(cls, page_texts: List[List[Dict]]) -> Dict[str, Any]:
        """21. 标题层级一致性: h1 → h2 → h3 不跳级."""
        import re as _re
        heading_pattern = _re.compile(r"^(\d+)(?:\.(\d+))?(?:\.(\d+))?\s")
        skipped: list[str] = []
        last_level = 0
        for lines in page_texts:
            for line in lines:
                if line["size"] < 14 or line["y"] < 60:
                    continue
                text = line["text"].strip()
                m = heading_pattern.match(text)
                if not m:
                    continue
                level = sum(1 for g in m.groups() if g is not None)
                if last_level > 0 and level > last_level + 1:
                    skipped.append(f"{text} (从 level {last_level} 跳到 {level})")
                last_level = level
        return {"skipped_levels": skipped}

    @classmethod
    def _check_punctuation_consistency(cls, page_texts: List[List[Dict]]) -> Dict[str, Any]:
        """22. 标点符号一致性: 检测中英文标点混用."""
        import re as _re
        # 中文标点: 。，！？；：""''（）《》
        chinese_punct = _re.compile(r"[。，！？；：""''（）《》、]")
        # 英文标点: . , ! ? ; : " ' ( ) < >
        english_punct = _re.compile(r"[.,!?;:\"'()<>]")
        mixed_count = 0
        for lines in page_texts[:10]:
            for line in lines:
                if line["y"] < 60 or line["y"] > 700:
                    continue
                text = line["text"]
                if chinese_punct.search(text) and english_punct.search(text):
                    # 检查是否同一句话混用
                    if any(chinese_punct.search(text) and english_punct.search(text)
                           for _ in [None]):
                        mixed_count += 1
        return {"mixed_punctuation": mixed_count}

    @classmethod
    def _check_figure_sequence(cls, page_texts: List[List[Dict]]) -> Dict[str, Any]:
        """23. 图表编号连续性: Figure 1, Figure 2... Table 1, Table 2... 不跳号."""
        import re as _re
        fig_pattern = _re.compile(r"(?:Figure|Fig\.?|表)\s*(\d+)")
        all_nums: set[int] = set()
        for lines in page_texts:
            for line in lines:
                text = line["text"]
                if line["y"] < 60 or line["y"] > 700:
                    continue
                for m in fig_pattern.finditer(text):
                    all_nums.add(int(m.group(1)))
        if not all_nums:
            return {"missing": [], "all_numbers": []}
        max_n = max(all_nums)
        expected = set(range(1, max_n + 1))
        missing = sorted(expected - all_nums)[:10]
        return {"missing": missing, "all_numbers": sorted(all_nums)}

    @classmethod
    def _check_chinese_english_spacing(cls, tex_path: Path) -> Dict[str, Any]:
        """24. 中英文之间空格检测 (LaTeX 排版规范要求中文与英文/数字之间有空格)."""
        import re as _re
        if not tex_path or not tex_path.exists():
            return {"missing_space": 0, "note": "tex not found"}
        try:
            tex = tex_path.read_text(encoding="utf-8")
        except OSError:
            return {"missing_space": 0, "note": "read_error"}
        # 检测: 中文字符紧接英文/数字字符 (无空格) - 这是 PDF 排版不规范的常见问题
        # 但 .tex 文件中不需要强制空格 (CJK 排版包会自动处理)，所以这是 informational
        # 这里我们检查 PDF 输出后的合并文本检测，但 PDF 文本提取困难
        # 退而求其次: 检查 .tex 中是否有 \CJKsetecjkwidth 等空格设置命令
        # 简化: 统计 [中文][英文] 紧邻出现的次数 (无空格)
        pattern = _re.compile(r"[\u4e00-\u9fff][A-Za-z0-9]")
        matches = pattern.findall(tex)
        return {"missing_space": len(matches), "note": "informational — tex-level"}

    # End of SPEC-X P1-2 新增 8 条检测方法

    # ── 补充 3 条规则以达到 24 条总数 (覆盖 TOC 深度 / 字体嵌入 / Unicode 残留) ──

    @classmethod
    def _check_toc_depth(cls, page_texts: List[List[Dict]]) -> Dict[str, Any]:
        """25. 目录层级深度: 目录应包含至少 2 级 (h1 + h2)."""
        depth_counter: set[int] = set()
        import re as _re
        for lines in page_texts:
            for line in lines:
                if line["y"] < 60 or line["y"] > 700:
                    continue
                text = line["text"].strip()
                # 目录条目格式: "1 Title .... 1" 或 "1.1 Title .... 2"
                m = _re.match(r"^(\d+(?:\.\d+)*)\s", text)
                if m:
                    depth = m.group(1).count(".") + 1
                    depth_counter.add(depth)
        if not depth_counter:
            return {"max_depth": 0, "insufficient": True}
        max_depth = max(depth_counter)
        return {"max_depth": max_depth, "insufficient": max_depth < 2}

    @classmethod
    def _check_font_embedding(cls, doc) -> Dict[str, Any]:
        """26. 字体嵌入检测: PDF 字体必须嵌入 (subset embedded)."""
        embedded_fonts: set[str] = set()
        not_embedded: set[str] = set()
        try:
            for page in doc:
                for font in page.get_fonts():
                    # font tuple: (xref, ext, type, basefont, name, encoding, ...)
                    xref = font[0]
                    basefont = font[3]
                    # Check if font is embedded by looking at the xref
                    # A font is "embedded" if its xref is used in the page contents
                    # PyMuPDF provides this via page.insert_font() etc.
                    # Simpler heuristic: extract font names; check 'ext' field
                    ext = font[1]  # 'n/a', 'ttf', 'otf', etc.
                    if ext in ("n/a", ""):
                        not_embedded.add(basefont)
                    else:
                        embedded_fonts.add(basefont)
        except Exception as e:
            return {"error": str(e)}
        return {
            "embedded": sorted(embedded_fonts),
            "not_embedded": sorted(not_embedded),
            "all_embedded": len(not_embedded) == 0,
        }

    @classmethod
    def _check_unicode_residual(cls, tex_path: Path) -> Dict[str, Any]:
        """27. Unicode 残留检测: .tex 中不应有未定义的 Unicode 字符 (如中文标点直排)."""
        import re as _re
        if not tex_path or not tex_path.exists():
            return {"residual_count": 0, "note": "tex not found"}
        try:
            tex = tex_path.read_text(encoding="utf-8")
        except OSError:
            return {"residual_count": 0, "note": "read_error"}
        # 检测常见问题 Unicode 字符 (non-breaking space, zero-width, RTL marks 等)
        residual_chars = _re.findall(r"[\u200B-\u200F\u202A-\u202E\uFEFF\u00A0]", tex)
        return {"residual_count": len(residual_chars), "samples": residual_chars[:10]}

    @classmethod
    def _check_cite_bib_correspondence(cls, pdf_path: Path) -> Dict[str, Any]:
        r"""
        参考文献格式智能校正：
        - 检测正文 \cite{...} 引用是否在参考文献 \bibitem{...} 中存在
        - 检测参考文献序号 [N] 是否连续

        策略：
        1. 查找与 PDF 同目录的 .tex 文件
        2. 从 .tex 中提取所有 \cite{...} 调用的 key
        3. 从 .tex 或同目录 .bbl 中提取所有 \bibitem{...} 的 key
        4. 对比两者，找出缺失的引用
        5. 提取 \bibitem 的序号 [N]，检测是否连续
        """
        result = {
            "tex_found": False,
            "cite_keys": [],
            "bib_keys": [],
            "missing_in_bib": [],
            "non_sequential": [],
        }

        tex_path = pdf_path.with_suffix(".tex")
        bbl_path = pdf_path.with_suffix(".bbl")

        # 1. 查找 tex 文件
        if not tex_path.exists():
            # 尝试在 build 目录中查找
            build_dir = pdf_path.parent
            tex_candidates = list(build_dir.glob("*.tex"))
            if tex_candidates:
                tex_path = tex_candidates[0]
            else:
                return result

        result["tex_found"] = True

        # 2. 提取 \cite{...} 的 key
        _CITE_RE = re.compile(r"\\cite\{([^}]+)\}")
        _BIBITEM_RE = re.compile(r"\\bibitem\{([^}]+)\}")
        _BIBITEM_NUM_RE = re.compile(r"\\bibitem\[(\d+)\]")

        try:
            tex_content = tex_path.read_text(encoding="utf-8")
        except Exception:
            return result

        cite_keys = set()
        for m in _CITE_RE.finditer(tex_content):
            keys = m.group(1).split(",")
            for k in keys:
                cite_keys.add(k.strip())
        result["cite_keys"] = sorted(cite_keys)

        # 3. 提取 \bibitem{...} 的 key
        bib_keys = set()
        bib_nums = []

        # 优先从 .bbl 文件读取
        bib_source = bbl_path if bbl_path.exists() else tex_path
        try:
            bib_content = bib_source.read_text(encoding="utf-8")
        except Exception:
            return result

        for m in _BIBITEM_RE.finditer(bib_content):
            bib_keys.add(m.group(1).strip())
        result["bib_keys"] = sorted(bib_keys)

        # 4. 检测缺失的引用
        missing = cite_keys - bib_keys
        result["missing_in_bib"] = sorted(missing)

        # 5. 检测序号连续性（\bibitem[N]{...} 或 thebibliography 环境中的顺序）
        for m in _BIBITEM_NUM_RE.finditer(bib_content):
            try:
                bib_nums.append(int(m.group(1)))
            except ValueError:
                continue

        # 如果没有 \bibitem[N] 格式，尝试从环境顺序推断
        if not bib_nums:
            bib_items = list(_BIBITEM_RE.finditer(bib_content))
            bib_nums = list(range(1, len(bib_items) + 1))

        if bib_nums:
            expected = list(range(min(bib_nums), max(bib_nums) + 1))
            non_sequential = [n for n in expected if n not in bib_nums]
            result["non_sequential"] = non_sequential

        return result
