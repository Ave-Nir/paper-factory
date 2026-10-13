"""
Section Composer 抽象基类 —— 所有章节编写器的基类。

设计原则：
- compose() 是 final 的，保证 pre/post-validation 始终执行
- 子类只实现 _render()，接收结构化数据，输出 LaTeX 字符串
- 使用 Jinja2 模板渲染，避免字符串拼接
"""

from abc import ABC, abstractmethod
from typing import Optional
import re

from core.types import (
    SectionData, LaTeXBlock, Diagnostic, DiagnosticSeverity,
    GateReport, IntroductionData, RelatedWorkData, MethodData,
    ExperimentData, ConclusionData, AbstractData,
)
from core.template_engine import BaseTemplate, ResolvedTemplate


# ============================================================================
# LaTeX 工具函数
# ============================================================================

LATEX_SPECIAL_CHARS = {
    "&": "\\&", "%": "\\%", "$": "\\$", "#": "\\#",
    "_": "\\_", "{": "\\{", "}": "\\}", "~": "\\textasciitilde{}",
    "^": "\\textasciicircum{}", "\\": "\\textbackslash{}",
}

GREEK_UNICODE_MAP = {
    # 小写希腊字母
    "\u03b1": "$\\alpha$",  # α
    "\u03b2": "$\\beta$",   # β
    "\u03b3": "$\\gamma$",  # γ
    "\u03b4": "$\\delta$",  # δ
    "\u03b5": "$\\epsilon$",  # ε
    "\u03b6": "$\\zeta$",   # ζ
    "\u03b7": "$\\eta$",    # η
    "\u03b8": "$\\theta$",  # θ
    "\u03b9": "$\\iota$",   # ι
    "\u03ba": "$\\kappa$",  # κ
    "\u03bb": "$\\lambda$", # λ
    "\u03bc": "$\\mu$",     # μ
    "\u03bd": "$\\nu$",     # ν
    "\u03be": "$\\xi$",     # ξ
    "\u03bf": "$o$",        # ο
    "\u03c0": "$\\pi$",     # π
    "\u03c1": "$\\rho$",    # ρ
    "\u03c2": "$\\sigma$",  # ς
    "\u03c3": "$\\sigma$",  # σ
    "\u03c4": "$\\tau$",    # τ
    "\u03c5": "$\\upsilon$",  # υ
    "\u03c6": "$\\phi$",    # φ
    "\u03c7": "$\\chi$",    # χ
    "\u03c8": "$\\psi$",    # ψ
    "\u03c9": "$\\omega$",  # ω
    # 大写希腊字母
    "\u0391": "$A$",        # Α
    "\u0392": "$B$",        # Β
    "\u0393": "$\\Gamma$",  # Γ
    "\u0394": "$\\Delta$",  # Δ
    "\u0395": "$E$",        # Ε
    "\u0396": "$Z$",        # Ζ
    "\u0397": "$H$",        # Η
    "\u0398": "$\\Theta$",  # Θ
    "\u0399": "$I$",        # Ι
    "\u039a": "$K$",        # Κ
    "\u039b": "$\\Lambda$", # Λ
    "\u039c": "$M$",        # Μ
    "\u039d": "$N$",        # Ν
    "\u039e": "$\\Xi$",     # Ξ
    "\u039f": "$O$",        # Ο
    "\u03a0": "$\\Pi$",     # Π
    "\u03a1": "$P$",        # Ρ
    "\u03a3": "$\\Sigma$",  # Σ
    "\u03a4": "$T$",        # Τ
    "\u03a5": "$\\Upsilon$",  # Υ
    "\u03a6": "$\\Phi$",    # Φ
    "\u03a7": "$X$",        # Χ
    "\u03a8": "$\\Psi$",    # Ψ
    "\u03a9": "$\\Omega$",  # Ω
}


def escape_latex(text: str) -> str:
    """转义 LaTeX 特殊字符 + 希腊字母 Unicode 映射
    
    关键流程：
    1. 先用占位符替换希腊字母，防止其内部字符被误转义
    2. 用正则一次性转义所有 LaTeX 特殊字符
    3. 还原希腊字母占位符为最终 LaTeX 数学模式命令
    """
    if not text:
        return ""
    
    result = text
    
    # 步骤 1：用唯一占位符替换希腊字母
    placeholders: dict[str, str] = {}
    for i, (unicode_char, latex_cmd) in enumerate(GREEK_UNICODE_MAP.items()):
        if unicode_char in result:
            token = f"\x00GREEK{i}\x00"
            result = result.replace(unicode_char, token)
            placeholders[token] = latex_cmd
    
    # 步骤 2：转义 LaTeX 特殊字符（正则单次替换，避免二次转义）
    latex_replace = {
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
        "\\": r"\textbackslash{}",
    }
    pattern = "|".join(re.escape(c) for c in latex_replace.keys())
    result = re.sub(pattern, lambda m: latex_replace[m.group(0)], result)
    
    # 步骤 3：还原希腊字母占位符
    for token, latex_cmd in placeholders.items():
        result = result.replace(token, latex_cmd)
    
    return result


def escape_latex_math(text: str) -> str:
    """处理数学模式内容 —— 不转义下划线和花括号"""
    special_for_math = {"&", "%", "$", "#", "~"}
    result = text
    for ch in special_for_math:
        result = result.replace(ch, LATEX_SPECIAL_CHARS[ch])
    return result


def wrap_figure(key: str, path: str, caption: str, 
                placement: str = "t", width: str = "0.8\\textwidth") -> str:
    """生成标准 LaTeX figure 环境"""
    return f"""\\begin{{figure}}[{placement}]
  \\centering
  \\includegraphics[width={width}]{{{path}}}
  \\caption{{{escape_latex(caption)}}}
  \\label{{fig:{key}}}
\\end{{figure}}"""


def wrap_table(key: str, caption: str, headers: list[str],
               rows: list[list[str]], placement: str = "t",
               column_format: Optional[str] = None) -> str:
    """生成标准 LaTeX table 环境"""
    n_cols = len(headers)
    if column_format is None:
        column_format = "l" + "c" * (n_cols - 1)
    
    header_line = " & ".join(escape_latex(h) for h in headers) + " \\\\"
    row_lines = [
        " & ".join(escape_latex(str(c)) for c in row) + " \\\\"
        for row in rows
    ]
    
    return f"""\\begin{{table}}[{placement}]
  \\centering
  \\caption{{{escape_latex(caption)}}}
  \\label{{tab:{key}}}
  \\begin{{tabular}}{{{column_format}}}
    \\toprule
    {header_line}
    \\midrule
    {chr(10).join("    " + rl for rl in row_lines)}
    \\bottomrule
  \\end{{tabular}}
\\end{{table}}"""


def wrap_equation(key: str, latex: str, description: str = "") -> str:
    """生成标准 LaTeX equation 环境"""
    desc_comment = f"  % {escape_latex(description)}" if description else ""
    return f"""\\begin{{equation}}
  \\label{{eq:{key}}}
  {latex}{desc_comment}
\\end{{equation}}"""


# ============================================================================
# 抽象基类
# ============================================================================

class BaseSectionComposer(ABC):
    """所有章节编写器的基类
    
    compose() 方法是 final 的，子类不能覆盖，保证验证流程一致。
    子类只需实现 _render() 方法。
    """
    
    section_name: str = ""  # 子类必须定义
    
    def __init__(self, template: ResolvedTemplate):
        self.template = template
    
    def compose(self, data: SectionData) -> LaTeXBlock:
        """主流程（final —— 子类不可覆盖）"""
        # 1. 前置验证
        pre_issues = self._pre_validate(data)
        if any(d.severity == DiagnosticSeverity.ERROR for d in pre_issues):
            raise SectionValidationError(self.section_name, pre_issues)
        
        # 2. 渲染
        latex = self._render(data)
        
        # 3. 后置验证
        post_issues = self._post_validate(latex)
        if any(d.severity == DiagnosticSeverity.ERROR for d in post_issues):
            raise SectionValidationError(self.section_name, post_issues)
        
        # 4. 估算页数
        est_pages = self._estimate_pages(latex)
        
        return LaTeXBlock(
            content=latex,
            section_name=self.section_name,
            estimated_pages=est_pages,
        )
    
    @abstractmethod
    def _render(self, data: SectionData) -> str:
        """子类实现：将结构化数据渲染为 LaTeX 字符串"""
        ...
    
    def _pre_validate(self, data: SectionData) -> list[Diagnostic]:
        """前置验证：检查输入数据完整性"""
        return []
    
    def _post_validate(self, latex: str) -> list[Diagnostic]:
        """后置验证：检查 LaTeX 输出合法性"""
        issues = []
        
        # 检查不完整环境
        env_pattern = r"\\(begin|end)\{(\w+)\}"
        begins = re.findall(r"\\begin\{(\w+)\}", latex)
        ends = re.findall(r"\\end\{(\w+)\}", latex)
        
        from collections import Counter
        begin_counts = Counter(begins)
        end_counts = Counter(ends)
        
        for env_name in set(list(begin_counts.keys()) + list(end_counts.keys())):
            diff = begin_counts.get(env_name, 0) - end_counts.get(env_name, 0)
            if diff > 0:
                issues.append(Diagnostic(
                    severity=DiagnosticSeverity.ERROR,
                    location=f"{self.section_name}:env:{env_name}",
                    message=f"Unclosed environment: {env_name} ({diff} unclosed)",
                    fix_suggestion=f"Add \\end{{{env_name}}}",
                ))
        
        # 检查未闭合的花括号
        brace_count = 0
        for ch in latex:
            if ch == "{":
                brace_count += 1
            elif ch == "}":
                brace_count -= 1
        if brace_count != 0:
            issues.append(Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                location=self.section_name,
                message=f"Unbalanced braces ({brace_count} unmatched)",
            ))
        
        return issues
    
    def _estimate_pages(self, latex: str) -> float:
        """粗略估算页数：约 3000 字符 = 1 页（单栏），1500 字符 = 1 页（双栏）"""
        char_per_page = 1500 if self.template.column_layout == "double" else 3000
        return len(latex) / char_per_page


class SectionValidationError(Exception):
    def __init__(self, section_name: str, diagnostics: list[Diagnostic]):
        self.section_name = section_name
        self.diagnostics = diagnostics
        msg = f"Validation failed for section '{section_name}':\n"
        msg += "\n".join(f"  [{d.severity.value}] {d.location}: {d.message}" 
                        for d in diagnostics)
        super().__init__(msg)


# ============================================================================
# 具体 Composer 示例 —— Introduction
# ============================================================================

class IntroductionComposer(BaseSectionComposer):
    section_name = "introduction"
    
    def _render(self, data: SectionData) -> str:
        assert isinstance(data, dict), "IntroductionData expected"
        
        lines = []
        lines.append("\\section{Introduction}")
        lines.append("\\label{sec:introduction}")
        
        # Background
        background = data.get("background", [])
        if background:
            for i, claim in enumerate(background):
                citations = ",".join(claim.get("citation_keys", []))
                cite_cmd = f" \\cite{{{citations}}}" if citations else "\\todo{missing citation}"
                lines.append(f"{escape_latex(claim['text'])}{cite_cmd}")
        
        # Problem statement
        if data.get("problem_statement"):
            lines.append(f"\n{escape_latex(data['problem_statement'])}")
        
        # Research gap
        if data.get("research_gap"):
            lines.append(f"\n{escape_latex(data['research_gap'])}")
        
        # Contributions
        contributions = data.get("contributions", [])
        if contributions:
            lines.append("\nOur main contributions are as follows:")
            lines.append("\\begin{enumerate}")
            for contrib in contributions:
                lines.append(
                    f"  \\item \\textbf{{{escape_latex(contrib['text'])}}}. "
                    f"{escape_latex(contrib.get('evidence', ''))}"
                )
            lines.append("\\end{enumerate}")
        
        # Paper structure
        structure = data.get("paper_structure", [])
        if structure:
            lines.append("\\subsection{Paper Organization}")
            lines.append(
                "The remainder of this paper is organized as follows. "
                + " ".join(escape_latex(s) for s in structure)
            )
        
        return "\n".join(lines)
    
    def _pre_validate(self, data: SectionData) -> list[Diagnostic]:
        issues = []
        
        # 检查每个 background claim 是否有引用
        background = data.get("background", [])
        for i, claim in enumerate(background):
            if not claim.get("citation_keys"):
                issues.append(Diagnostic(
                    severity=DiagnosticSeverity.WARNING,
                    location=f"introduction.background[{i}]",
                    message="Claim has no citation_keys (orphan claim)",
                    fix_suggestion="Add at least one citation key if available",
                ))
        
        # 检查贡献是否非空
        contributions = data.get("contributions", [])
        if not contributions:
            issues.append(Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                location="introduction.contributions",
                message="No contributions defined",
            ))
        
        return issues


class RelatedWorkComposer(BaseSectionComposer):
    section_name = "related_work"
    
    def _render(self, data: SectionData) -> str:
        lines = [
            "\\section{Related Work}",
            "\\label{sec:related_work}",
        ]
        
        subsections = data.get("subsections", [])
        for sub in subsections:
            topic = escape_latex(sub.get("topic", "Untitled"))
            lines.append(f"\\subsection{{{topic}}}")
            
            for work in sub.get("works", []):
                citations = ",".join(work.get("citation_keys", []))
                cite_cmd = f" \\cite{{{citations}}}" if citations else ""
                lines.append(f"{escape_latex(work['text'])}{cite_cmd}")
        
        return "\n".join(lines)


class MethodComposer(BaseSectionComposer):
    section_name = "method"
    
    def _render(self, data: SectionData) -> str:
        lines = [
            "\\section{Method}",
            "\\label{sec:method}",
        ]
        
        if data.get("overview"):
            lines.append(escape_latex(data["overview"]))
        
        subsections = data.get("subsections", [])
        for sub in subsections:
            title = escape_latex(sub.get("title", "Untitled"))
            lines.append(f"\\subsection{{{title}}}")
            
            if sub.get("content"):
                lines.append(escape_latex(sub["content"]))
            
            for eq in sub.get("equations", []):
                lines.append(wrap_equation(eq["key"], eq["latex"], eq.get("description", "")))
            
            for fig in sub.get("figures", []):
                lines.append(wrap_figure(
                    fig["key"], fig["path"], fig["caption"],
                    fig.get("placement", "t"), fig.get("width", "0.8\\textwidth"),
                ))
        
        # Algorithms
        algorithms = data.get("algorithms", [])
        for alg in algorithms:
            lines.append(f"\\begin{{algorithm}}[t]")
            lines.append(f"  \\caption{{{escape_latex(alg['caption'])}}}")
            lines.append(f"  \\label{{alg:{alg['key']}}}")
            lines.append(f"  \\textbf{{Input:}} {escape_latex(alg.get('input_desc', ''))} \\\\")
            lines.append(f"  \\textbf{{Output:}} {escape_latex(alg.get('output_desc', ''))} \\\\")
            for step in alg["steps"]:
                lines.append(f"  {escape_latex(step)} \\\\")
            lines.append(f"\\end{{algorithm}}")
        
        return "\n".join(lines)


class ExperimentsComposer(BaseSectionComposer):
    section_name = "experiments"
    
    def _render(self, data: SectionData) -> str:
        lines = [
            "\\section{Experiments}",
            "\\label{sec:experiments}",
        ]
        
        subsections = data.get("subsections", [])
        for sub in subsections:
            title = escape_latex(sub.get("title", "Untitled"))
            lines.append(f"\\subsection{{{title}}}")
            
            if sub.get("description"):
                lines.append(escape_latex(sub["description"]))
            
            for tbl in sub.get("tables", []):
                lines.append(wrap_table(
                    tbl["key"], tbl["caption"], tbl["headers"], tbl["rows"],
                    tbl.get("placement", "t"), tbl.get("column_format"),
                ))
            
            for fig in sub.get("figures", []):
                lines.append(wrap_figure(
                    fig["key"], fig["path"], fig["caption"],
                    fig.get("placement", "t"), fig.get("width", "0.8\\textwidth"),
                ))
            
            findings = sub.get("findings", [])
            if findings:
                for finding in findings:
                    citations = ",".join(finding.get("citation_keys", []))
                    cite_cmd = f" \\cite{{{citations}}}" if citations else ""
                    lines.append(f"{escape_latex(finding['text'])}{cite_cmd}")
        
        return "\n".join(lines)


class ConclusionComposer(BaseSectionComposer):
    section_name = "conclusion"
    
    def _render(self, data: SectionData) -> str:
        lines = [
            "\\section{Conclusion}",
            "\\label{sec:conclusion}",
        ]
        
        if data.get("summary"):
            lines.append(escape_latex(data["summary"]))
        
        limitations = data.get("limitations", [])
        if limitations:
            lines.append("\\subsection{Limitations}")
            lines.append("\\begin{itemize}")
            for lim in limitations:
                lines.append(f"  \\item {escape_latex(lim)}")
            lines.append("\\end{itemize}")
        
        future_work = data.get("future_work", [])
        if future_work:
            lines.append("\\subsection{Future Work}")
            lines.append("\\begin{itemize}")
            for fw in future_work:
                lines.append(f"  \\item {escape_latex(fw)}")
            lines.append("\\end{itemize}")
        
        return "\n".join(lines)


class AbstractComposer(BaseSectionComposer):
    section_name = "abstract"
    
    def _render(self, data: SectionData) -> str:
        parts = []
        if data.get("context"):
            parts.append(escape_latex(data["context"]))
        if data.get("problem"):
            parts.append(escape_latex(data["problem"]))
        if data.get("approach"):
            parts.append(escape_latex(data["approach"]))
        if data.get("results"):
            parts.append(escape_latex(data["results"]))
        if data.get("impact"):
            parts.append(escape_latex(data["impact"]))
        
        content = " ".join(parts)
        return f"\\begin{{abstract}}\n  {content}\n\\end{{abstract}}"


# ============================================================================
# 中文 Composers —— NSFC（面上/地区/青年项目）/ SCI 期刊 / 学位论文
# ============================================================================

class ChineseAbstractComposer(BaseSectionComposer):
    """中文摘要（NSFC/学位论文通用）"""
    section_name = "chinese_abstract"

    def _render(self, data: SectionData) -> str:
        title = data.get("title", "")
        content = data.get("content", "")
        keywords = data.get("keywords", [])
        lines = []
        if title:
            lines.append(f"\\section*{{{title}}}")
        lines.append(f"\\label{{sec:{self.section_name}}}")
        if content:
            lines.append(content)
        if keywords:
            kw_str = "、".join(keywords)
            lines.append(f"\\par\\textbf{{关键词：}}{kw_str}")
        return "\n".join(lines)


class ChineseIntroductionComposer(BaseSectionComposer):
    """中文引言（人文学科论文，标题中文）"""
    section_name = "introduction_cn"

    def _render(self, data: SectionData) -> str:
        lines = [
            "\\section{引言}",
            "\\label{sec:introduction_cn}",
        ]
        # 选题背景
        background = data.get("background", "")
        if background:
            lines.append(f"\\subsection{{选题背景}}")
            lines.append(background)
        # 问题提出
        problem = data.get("problem_statement", "")
        if problem:
            lines.append(f"\\subsection{{问题提出}}")
            lines.append(problem)
        # 研究意义/创新点
        significance = data.get("significance", "")
        if significance:
            lines.append(f"\\subsection{{研究意义}}")
            lines.append(significance)
        # 论文结构
        structure = data.get("paper_structure", [])
        if structure:
            lines.append(f"\\subsection{{论文结构}}")
            lines.append("本文共分为以下几个部分：")
            lines.append("\\begin{enumerate}")
            for s in structure:
                lines.append(f"  \\item {s}")
            lines.append("\\end{enumerate}")
        return "\n".join(lines)

    def _pre_validate(self, data: SectionData) -> list:
        issues = []
        # 引言三要素必须至少有一个
        if not (data.get("background") or data.get("problem_statement") or data.get("significance")):
            issues.append(Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                location="introduction_cn",
                message="引言为空，建议补充选题背景/问题提出/研究意义",
            ))
        return issues


class ChineseRelatedWorkComposer(BaseSectionComposer):
    """国内外研究现状（NSFC 特有）"""
    section_name = "related_work_cn"

    def _render(self, data: SectionData) -> str:
        lines = [
            "\\section{国内外研究现状}",
            "\\label{sec:related_work_cn}",
        ]
        subsections = data.get("subsections", [])
        for sub in subsections:
            title = sub.get("title", "")
            if title:
                lines.append(f"\\subsection{{{title}}}")
            for item in sub.get("works", []):
                citations = ",".join(item.get("citation_keys", []))
                cite_cmd = f" \\cite{{{citations}}}" if citations else ""
                text = item.get("text", "")
                lines.append(f"{text}{cite_cmd}")
        return "\n".join(lines)


class ChineseResearchContentComposer(BaseSectionComposer):
    """研究内容（NSFC 特有）"""
    section_name = "research_content"

    def _render(self, data: SectionData) -> str:
        lines = [
            "\\section{主要研究内容}",
            "\\label{sec:research_content}",
        ]
        if data.get("overview"):
            lines.append(data["overview"])
        items = data.get("items", [])
        for i, item in enumerate(items, 1):
            title = item.get("title", "")
            detail = item.get("detail", "")
            lines.append(f"\\subsection{{{i}. {title}}}")
            if detail:
                lines.append(detail)
        return "\n".join(lines)


class ChineseResearchBasisComposer(BaseSectionComposer):
    """研究基础与可行性分析（NSFC 特有）"""
    section_name = "research_basis"

    def _render(self, data: SectionData) -> str:
        lines = [
            "\\section{研究基础与可行性分析}",
            "\\label{sec:research_basis}",
        ]
        subsections = data.get("subsections", [])
        for sub in subsections:
            title = sub.get("title", "")
            if title:
                lines.append(f"\\subsection{{{title}}}")
            content = sub.get("content", "")
            if content:
                lines.append(content)
        return "\n".join(lines)


class ChineseFiguresTablesComposer(BaseSectionComposer):
    """中文图表/技术路线"""
    section_name = "figures_tables_cn"

    def _render(self, data: SectionData) -> str:
        lines = []
        figures = data.get("figures", [])
        for fig in figures:
            lines.append(wrap_figure(
                fig["key"], fig.get("path", ""),
                fig.get("caption", ""),
                fig.get("placement", "t"),
                fig.get("width", "0.8\\textwidth"),
            ))
        tables = data.get("tables", [])
        for tbl in tables:
            lines.append(wrap_table(
                tbl["key"], tbl.get("caption", ""),
                tbl.get("headers", []),
                tbl.get("rows", []),
                tbl.get("placement", "t"),
                tbl.get("column_format"),
            ))
        return "\n\n".join(lines)


class ChineseConclusionComposer(BaseSectionComposer):
    """中文结论 / 预期成效"""
    section_name = "conclusion_cn"

    def _render(self, data: SectionData) -> str:
        lines = [
            "\\section{预期成效与创新点}",
            "\\label{sec:conclusion_cn}",
        ]
        if data.get("summary"):
            lines.append(data["summary"])
        innovations = data.get("innovations", [])
        if innovations:
            lines.append("\\subsection{主要创新点}")
            lines.append("\\begin{enumerate}")
            for inn in innovations:
                lines.append(f"  \\item {inn}")
            lines.append("\\end{enumerate}")
        outcomes = data.get("expected_outcomes", [])
        if outcomes:
            lines.append("\\subsection{预期成果}")
            lines.append("\\begin{itemize}")
            for out in outcomes:
                lines.append(f"  \\item {out}")
            lines.append("\\end{itemize}")
        return "\n".join(lines)


class EnglishAbstractComposer(BaseSectionComposer):
    """英文摘要（中文论文双语摘要）"""
    section_name = "english_abstract"

    def _render(self, data: SectionData) -> str:
        title = data.get("title", "")
        content = data.get("content", "")
        keywords = data.get("keywords", [])
        lines = []
        if title:
            lines.append(f"\\section*{{{title}}}")
        lines.append(f"\\label{{sec:{self.section_name}}}")
        if content:
            lines.append(content)
        if keywords:
            kw_str = ", ".join(keywords)
            lines.append(f"\\par\\textbf{{Keywords:}} {kw_str}")
        return "\n".join(lines)


class ChineseAcknowledgementComposer(BaseSectionComposer):
    """致谢（中文论文）"""
    section_name = "acknowledgement_cn"

    def _render(self, data: SectionData) -> str:
        content = data.get("content", "")
        if not content:
            return ""
        lines = [
            "\\section*{致谢}",
            "\\label{sec:acknowledgement_cn}",
            content,
        ]
        return "\n".join(lines)


class ChineseReferencesComposer(BaseSectionComposer):
    """参考文献（中文项目使用 gbt7714-nsfc 样式）"""
    section_name = "references_cn"

    def _render(self, data: SectionData) -> str:
        bib_path = data.get("bib_path", "references")
        style = data.get("style", "gbt7714-nsfc")
        return f"\\bibliographystyle{{{style}}}\n\\bibliography{{{bib_path}}}"


# ============================================================================
# SCI 期刊论文 Composers（中英文双语）
# ============================================================================

class SciAbstractChineseComposer(BaseSectionComposer):
    """SCI 中文摘要"""
    section_name = "sci_abstract_zh"

    def _render(self, data: SectionData) -> str:
        lines = ["\\begin{abstract}"]
        if data.get("content"):
            lines.append(f"  {data['content']}")
        lines.append("\\end{abstract}")
        return "\n".join(lines)


class SciIntroductionComposer(BaseSectionComposer):
    """SCI 引言"""
    section_name = "sci_introduction"

    def _render(self, data: SectionData) -> str:
        lines = [
            "\\section{引言}",
            "\\label{sec:sci_intro}",
        ]
        background = data.get("background", [])
        for bg in background:
            citations = ",".join(bg.get("citation_keys", []))
            cite_cmd = f" \\cite{{{citations}}}" if citations else ""
            lines.append(f"{bg.get('text', '')}{cite_cmd}")
        if data.get("problem"):
            lines.append(data["problem"])
        return "\n".join(lines)


class SciMethodComposer(BaseSectionComposer):
    """SCI 方法"""
    section_name = "sci_method"

    def _render(self, data: SectionData) -> str:
        lines = [
            "\\section{研究方法}",
            "\\label{sec:sci_method}",
        ]
        if data.get("overview"):
            lines.append(data["overview"])
        for sub in data.get("subsections", []):
            if sub.get("title"):
                lines.append(f"\\subsection{{{sub['title']}}}")
            if sub.get("content"):
                lines.append(sub["content"])
            for fig in sub.get("figures", []):
                lines.append(wrap_figure(
                    fig["key"], fig.get("path", ""), fig.get("caption", "")))
        return "\n".join(lines)


class SciResultsComposer(BaseSectionComposer):
    """SCI 结果 / 实验"""
    section_name = "sci_results"

    def _render(self, data: SectionData) -> str:
        lines = [
            "\\section{实验结果}",
            "\\label{sec:sci_results}",
        ]
        for sub in data.get("subsections", []):
            if sub.get("title"):
                lines.append(f"\\subsection{{{sub['title']}}}")
            if sub.get("content"):
                lines.append(sub["content"])
            for tbl in sub.get("tables", []):
                lines.append(wrap_table(
                    tbl["key"], tbl.get("caption", ""),
                    tbl.get("headers", []), tbl.get("rows", []),
                    tbl.get("placement", "t"), tbl.get("column_format"),
                ))
        return "\n".join(lines)


class SciDiscussionComposer(BaseSectionComposer):
    """SCI 讨论"""
    section_name = "sci_discussion"

    def _render(self, data: SectionData) -> str:
        lines = [
            "\\section{讨论}",
            "\\label{sec:sci_discussion}",
        ]
        if data.get("content"):
            lines.append(data["content"])
        return "\n".join(lines)


class SciConclusionComposer(BaseSectionComposer):
    """SCI 结论"""
    section_name = "sci_conclusion"

    def _render(self, data: SectionData) -> str:
        lines = [
            "\\section{结论}",
            "\\label{sec:sci_conclusion}",
        ]
        if data.get("content"):
            lines.append(data["content"])
        return "\n".join(lines)


# ============================================================================
# 学位论文 Composers
# ============================================================================

class ThesisIntroComposer(BaseSectionComposer):
    """学位论文第一章 绪论"""
    section_name = "thesis_intro"

    def _render(self, data: SectionData) -> str:
        lines = [
            "\\chapter{绪论}",
            "\\label{ch:intro}",
        ]
        if data.get("background"):
            lines.append("\\section{研究背景}")
            lines.append(data["background"])
        if data.get("significance"):
            lines.append("\\section{研究意义}")
            lines.append(data["significance"])
        if data.get("content"):
            lines.append("\\section{研究内容与组织结构}")
            lines.append(data["content"])
        return "\n".join(lines)


class ThesisLitReviewComposer(BaseSectionComposer):
    """学位论文 文献综述"""
    section_name = "thesis_literature"

    def _render(self, data: SectionData) -> str:
        lines = [
            "\\chapter{文献综述}",
            "\\label{ch:literature}",
        ]
        for sub in data.get("subsections", []):
            if sub.get("title"):
                lines.append(f"\\section{{{sub['title']}}}")
            for work in sub.get("works", []):
                citations = ",".join(work.get("citation_keys", []))
                cite_cmd = f" \\cite{{{citations}}}" if citations else ""
                lines.append(f"{work.get('text', '')}{cite_cmd}")
        return "\n".join(lines)


class ThesisMainBodyComposer(BaseSectionComposer):
    """学位论文主体章节（可复用于多个研究章节）"""
    section_name = "thesis_chapter"

    def _render(self, data: SectionData) -> str:
        title = data.get("title", "未命名章节")
        lines = [
            f"\\chapter{{{title}}}",
            f"\\label{{ch:thesis_body}}",
        ]
        if data.get("intro"):
            lines.append(data["intro"])
        for sub in data.get("sections", []):
            if sub.get("title"):
                lines.append(f"\\section{{{sub['title']}}}")
            if sub.get("content"):
                lines.append(sub["content"])
        return "\n".join(lines)


class ThesisConclusionComposer(BaseSectionComposer):
    """学位论文 结论与展望"""
    section_name = "thesis_conclusion"

    def _render(self, data: SectionData) -> str:
        lines = [
            "\\chapter{结论与展望}",
            "\\label{ch:conclusion}",
        ]
        if data.get("summary"):
            lines.append(data["summary"])
        if data.get("innovations"):
            lines.append("\\section{主要创新点}")
            for i, inn in enumerate(data["innovations"], 1):
                lines.append(f"{i}. {inn}")
        if data.get("future_work"):
            lines.append("\\section{研究展望}")
            lines.append(data["future_work"])
        return "\n".join(lines)


# ============================================================================
# Chinese Composer 注册表 —— template_engine 可以根据 section_name 查找
# ============================================================================

CHINESE_COMPOSERS = {
    # NSFC / Thesis
    "chinese_abstract": ChineseAbstractComposer,
    "english_abstract": EnglishAbstractComposer,
    "related_work_cn": ChineseRelatedWorkComposer,
    "research_content": ChineseResearchContentComposer,
    "research_basis": ChineseResearchBasisComposer,
    "figures_tables_cn": ChineseFiguresTablesComposer,
    "conclusion_cn": ChineseConclusionComposer,
    "acknowledgement_cn": ChineseAcknowledgementComposer,
    "references_cn": ChineseReferencesComposer,
    # SCI
    "sci_abstract_zh": SciAbstractChineseComposer,
    "sci_introduction": SciIntroductionComposer,
    "sci_method": SciMethodComposer,
    "sci_results": SciResultsComposer,
    "sci_discussion": SciDiscussionComposer,
    "sci_conclusion": SciConclusionComposer,
    # Thesis
    "thesis_intro": ThesisIntroComposer,
    "thesis_literature": ThesisLitReviewComposer,
    "thesis_chapter": ThesisMainBodyComposer,
    "thesis_conclusion": ThesisConclusionComposer,
}