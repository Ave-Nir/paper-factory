# -*- coding: utf-8 -*-
r"""
通用 LaTeX 组装器（核心 skill 组件）

支持的 block 类型及其渲染：
  title            → \title{...}
  heading          → \chapter / \section / \subsection / \subparagraph
  abstract         → \begin{abstract} ... \end{abstract}
  abstract-en      → \chapter*{Abstract} + 正文
  keywords         → \noindent \textbf{关键词：} ...
  text             → 普通段落（自动转义 + 数学识别）
  image            → \begin{figure} ... \includegraphics{path} \caption{...}
  table            → \begin{table} ... \begin{tabular} ... \bottomrule \caption{...}
  references-heading → \chapter*{参考文献}
  reference-item     → \bibitem{refXX} ...

设计原则：
  1. 按原文顺序输出，不打乱结构
  2. 内容完整：不丢弃任何字符
  3. 合理转义：特殊字符 → LaTeX 安全格式
"""

import re
from typing import List, Optional, Dict, Any


# ============================================================
# 转义规则
# ============================================================
# 基础 LaTeX 特殊字符
_ESCAPE_MAP = {
    "&": r"\&",
    "%": r"\%",
    "#": r"\#",
    "_": r"\_",
    "$": r"\$",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}

# 数学识别：T_core, P_eff 等科学记号
_MATH_SUBSCRIPT_RE = re.compile(
    r"\b([A-Za-z])_(core|eff|max|min|std|mean|avg|base|measured|th)\b",
    re.IGNORECASE,
)

# OMML 公式占位符：在 document_reader.py 中检测到 <m:oMath> 后生成
_OMML_PLACEHOLDER_RE = re.compile(r"\[MATH_OMML:([^\]]+)\]")

# 希腊字母映射（常见希腊字母 Unicode → LaTeX）
_GREEK_MAP = {
    "α": r"\alpha", "β": r"\beta", "γ": r"\gamma", "δ": r"\delta",
    "ε": r"\varepsilon", "ζ": r"\zeta", "η": r"\eta", "θ": r"\theta",
    "ι": r"\iota", "κ": r"\kappa", "λ": r"\lambda", "μ": r"\mu",
    "ν": r"\nu", "ξ": r"\xi", "ο": r"o", "π": r"\pi",
    "ρ": r"\rho", "σ": r"\sigma", "τ": r"\tau", "υ": r"\upsilon",
    "φ": r"\varphi", "χ": r"\chi", "ψ": r"\psi", "ω": r"\omega",
    "Γ": r"\Gamma", "Δ": r"\Delta", "Θ": r"\Theta", "Λ": r"\Lambda",
    "Ξ": r"\Xi", "Π": r"\Pi", "Σ": r"\Sigma", "Φ": r"\Phi",
    "Ψ": r"\Psi", "Ω": r"\Omega",
}

# 数学符号映射（Unicode → LaTeX）
_MATH_SYMBOL_MAP = {
    "±": r"\pm", "×": r"\times", "÷": r"\div", "≤": r"\leq",
    "≥": r"\geq", "≠": r"\neq", "≈": r"\approx", "∞": r"\infty",
    "∂": r"\partial", "∫": r"\int", "∑": r"\sum", "∏": r"\prod",
    "√": r"\sqrt", "→": r"\rightarrow", "←": r"\leftarrow",
    "↔": r"\leftrightarrow", "⇒": r"\Rightarrow", "⇐": r"\Leftarrow",
    "…": r"\ldots", "⋯": r"\cdots", "·": r"\cdot", "°": r"^\circ",
    "′": r"'", "″": r"''", "∈": r"\in", "∉": r"\notin",
    "⊂": r"\subset", "⊃": r"\supset", "∪": r"\cup", "∩": r"\cap",
    "∀": r"\forall", "∃": r"\exists", "∇": r"\nabla", "∝": r"\propto",
    "‰": r"\permil",
}


def escape_text(text: str) -> str:
    """基础转义：不含数学识别。用于 caption 等需要谨慎处理的地方。"""
    if not text:
        return ""
    out = []
    for ch in text:
        out.append(_ESCAPE_MAP.get(ch, ch))
    return "".join(out)


def _convert_greek_and_symbols(text: str) -> str:
    """将文本中的希腊字母和数学符号转换为 LaTeX 命令。"""
    result = []
    i = 0
    while i < len(text):
        ch = text[i]
        # 希腊字母
        if ch in _GREEK_MAP:
            result.append(_GREEK_MAP[ch])
            i += 1
            continue
        # 数学符号
        if ch in _MATH_SYMBOL_MAP:
            result.append(_MATH_SYMBOL_MAP[ch])
            i += 1
            continue
        result.append(ch)
        i += 1
    return "".join(result)


def _wrap_simple_formulas(text: str) -> str:
    """启发式识别简单公式并包裹为 $...$。

    识别的模式：
    - 包含希腊字母的单词/短语
    - 包含数学符号的表达式
    - 科学计数法（1.23e-4）
    - 简单的等式（A = B + C）
    """
    # 模式1: 等号连接的科学表达式（如 E = mc^2, α + β = γ）
    # 模式2: 包含希腊字母和运算符的片段
    # 模式3: 科学计数法
    # 由于精确识别容易过度匹配，我们采用保守策略：
    # 只对明确的公式模式加 $，其余保持原文

    # 替换科学计数法：1.23×10^5 → $1.23 \times 10^{5}$
    text = re.sub(
        r"(\d+\.?\d*)\s*[×xX]\s*10\^(\-?\d+)",
        r"$\1 \\times 10^{\2}$",
        text,
    )

    # 替换简单的上标数字（如 m², cm³）→ $m^2$, $cm^3$
    text = re.sub(
        r"([a-zA-Z]+)([²³¹⁰⁴⁵⁶⁷⁸⁹])",
        lambda m: f"${m.group(1)}^{{_SUPERSCRIPT_MAP.get(m.group(2), m.group(2))}}$",
        text,
    )

    return text


# 上标数字 Unicode → 普通数字
_SUPERSCRIPT_MAP = {
    "⁰": "0", "¹": "1", "²": "2", "³": "3", "⁴": "4",
    "⁵": "5", "⁶": "6", "⁷": "7", "⁸": "8", "⁹": "9",
    "⁻": "-",
}


def math_aware_escape(text: str) -> str:
    """对正文段落：转义 + 启发式数学识别。

    V7.5 修复：保护已有的 $...$ 和 $$...$$ 数学模式，避免
    escape_text() 破坏内部 LaTeX 命令。
    """
    import re as _re

    # Step 0: 保护已有的数学模式
    _math_protected = {}
    _math_counter = [0]

    def _protect_math(m):
        key = f"MAEMATH{_math_counter[0]}"
        _math_protected[key] = m.group(0)
        _math_counter[0] += 1
        return key

    # 先保护 $$...$$（显示公式），再保护 $...$（行内公式）
    text = _re.sub(r'\$\$.+?\$\$', _protect_math, text, flags=_re.DOTALL)
    text = _re.sub(r'\$.+?\$', _protect_math, text)

    # 1. 处理 OMML 公式占位符（优先级最高）
    def _omml_sub(m):
        formula = m.group(1)
        formula = _convert_greek_and_symbols(formula)
        return f"${formula}$"

    text = _OMML_PLACEHOLDER_RE.sub(_omml_sub, text)

    # 2. 基础转义
    text = escape_text(text)

    # 3. 希腊字母和数学符号转换
    text = _convert_greek_and_symbols(text)

    # 4. 把 T\_core 还原为 $T_{core}$
    def _sub(m):
        base = m.group(1)
        sub = m.group(2)
        return f"${base}_{{{sub}}}$"

    text = _MATH_SUBSCRIPT_RE.sub(_sub, text)

    # 5. 简单公式包裹（科学计数法等）
    text = _wrap_simple_formulas(text)

    # Step 6: 还原保护的数学模式
    for key, original in _math_protected.items():
        text = text.replace(key, original)

    return text


def escape_table_cell(text: str) -> str:
    """对表格单元格进行安全转义，保护已有的 LaTeX 数学模式。

    问题背景：
        escape_text() 不转义反斜杠，当表格单元格内包含 LaTeX 数学模式
        （如 \\(\\{P_1\\}\\)）时，转义 \\{ → \\{ 但 \\ 保持原样，
        产生 \\\\{ 序列，LaTeX 将 \\\\ 解释为表格行分隔符
        → "Misplaced alignment tab character &" × 139。

    策略：
        1. 保护已有的 $...$, \\(...\\), \\[...\\] 数学模式
        2. 对剩余纯文本调用 escape_text()
        3. 还原数学模式（保持其内部 LaTeX 命令原样）

    V7.7: 在处理前将 Markdown **bold** 语法转换为 LaTeX \\textbf{bold}
    """
    import re as _re
    if not text:
        return ""

    # V7.7: 将 Markdown **bold** 语法转换为 LaTeX \textbf{bold}
    text = _re.sub(r'\*\*([^*]+?)\*\*', r'\\textbf{\1}', text)

    # Step 1: 保护已有的 LaTeX 数学模式
    # 使用不含 _ 等可转义字符的占位符，避免 escape_text() 破坏还原
    _protected = {}
    _counter = [0]

    def _protect(m):
        key = f"TBLMATHPLACEHOLDER{_counter[0]}"
        _protected[key] = m.group(0)
        _counter[0] += 1
        return key

    # 注意：r'\\\(' 在 regex 中 = \\ 匹配字面 \，\( 匹配字面 (
    # 所以匹配文本中的 \(...\)
    text = _re.sub(r'\\\(.+?\\\)', _protect, text)               # \(...\)
    text = _re.sub(r'\\\[.+?\\\]', _protect, text, flags=_re.DOTALL)  # \[...\]
    text = _re.sub(r'\$.+?\$', _protect, text)                   # $...$

    # V7.6: 保护 LaTeX 特殊字符转义（\{、\}、\$、\#、\&、\%、\_）
    # 避免 \{P1\} 被二次转义成 \\{P1\\} → LaTeX 将 \\ 解释为表格行分隔符
    text = _re.sub(r'\\[{}&#$_]', _protect, text)
    # V7.6: 保护 \textbf{...} 等 LaTeX 命令
    text = _re.sub(r'\\(?:textbf|textit|emph|underline|texttt|textsf|textsc)\{[^}]*\}', _protect, text)

    # Step 2: 对剩余纯文本进行转义
    text = escape_text(text)

    # Step 3: 还原数学模式（内部 LaTeX 命令保持原样）
    for key, original in _protected.items():
        text = text.replace(key, original)

    return text


def _is_standalone_formula(text: str) -> bool:
    """
    判断一行文本是否为独立的数学公式（未用 $...$ 包裹）。

    启发规则：
    - 包含等号 '=' 或赋值关系
    - 包含数学专用符号（希腊字母、∥、½、Σ、∫、∂、∞、√ 等）
    - 包含函数名（exp、log、sin、cos、max、min、D_KL 等）
    - 行长度适中（非大段文字）
    - 中文字符占比低（< 30%）
    """
    if not text or len(text) > 200:
        return False

    # 已包裹的公式不处理
    if text.startswith("$") and text.endswith("$"):
        return False
    if text.startswith("$$") and text.endswith("$$"):
        return False

    # 数学符号集合
    math_symbols = set("=+-*/^_{}()[]|∥½¼¾¹²³⁰⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉αβγδεζηθικλμνξοπρστυφχψωΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ∑∏∫∂√∞≈≠≤≥±×÷·∂∇⊗⊕∧∨¬∃∀∈∉⊂⊃⊆⊇∪∩∅→←↑↓↔⇒⇔≡≜≝≞")
    math_functions = ["exp", "log", "ln", "sin", "cos", "tan", "max", "min", "arg", "sup", "inf", "lim", "sum", "prod", "int", "det", "tr", "rank", "var", "cov", "std", "mean", "median", "mode", "D_KL", "JSD", "KL", "N(", "K /", "t₀", "r₀"]

    has_math_symbol = any(c in math_symbols for c in text)
    has_math_func = any(func in text for func in math_functions)

    # 必须有等号或数学符号/函数
    if not ("=" in text or has_math_symbol or has_math_func):
        return False

    # 中文字符占比应较低
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    if chinese_chars > 0 and chinese_chars / len(text) > 0.3:
        return False

    # 排除普通 URL、文件名等
    if text.startswith("http") or text.startswith("www"):
        return False

    return True


# ============================================================
# 智能布局决策（双列模板）
# ============================================================
def _should_figure_span_two_columns(
    width: int,
    height: int,
    format_spec=None,
) -> bool:
    """
    判断图片是否应占双列。
    
    决策规则：
    - 宽高比 >= image_aspect_threshold 时占双列（横宽图）
    - 无尺寸信息时默认单列
    """
    if width <= 0 or height <= 0:
        return False
    
    threshold = getattr(format_spec, "image_aspect_threshold", 1.5) if format_spec else 1.5
    aspect_ratio = width / height
    return aspect_ratio >= threshold


def _should_table_span_two_columns(
    n_cols: int,
    format_spec=None,
) -> bool:
    """
    判断表格是否应占双列。
    
    决策规则：
    - 列数 >= table_column_threshold 时占双列（宽表）
    """
    threshold = getattr(format_spec, "table_column_threshold", 4) if format_spec else 4
    return n_cols >= threshold


# ============================================================
# 片段渲染
# ============================================================
def _render_figure(block: Dict[str, Any], images_map: Dict[int, Any], format_spec=None, is_double_column: bool = False) -> List[str]:
    idx = block.get("idx", 0)
    data = block.get("data") or {}
    caption = data.get("caption", "") or ""
    path = None
    img_obj = data.get("image_obj")
    img_width_px = 0
    img_height_px = 0
    
    if img_obj is not None and hasattr(img_obj, "extracted_path"):
        path = img_obj.extracted_path
        img_width_px = getattr(img_obj, "width", 0)
        img_height_px = getattr(img_obj, "height", 0)
    if path is None and idx in images_map:
        img = images_map[idx]
        if hasattr(img, "extracted_path"):
            path = img.extracted_path
        img_width_px = getattr(img, "width", 0)
        img_height_px = getattr(img, "height", 0)
    if path is None:
        path = f"images/image{idx:02d}.png"

    fig_cap_pos = getattr(format_spec, "figure_caption_position", "bottom") if format_spec else "bottom"
    
    # 智能布局决策：双列模板中根据宽高比决定单列或双列
    use_double_column = False
    if is_double_column:
        use_double_column = _should_figure_span_two_columns(img_width_px, img_height_px, format_spec)
    
    figure_env = "figure*" if use_double_column else "figure"
    img_width = "0.9\\textwidth" if use_double_column else (
        getattr(format_spec, "image_width", "0.9\\textwidth") if format_spec else "0.9\\textwidth"
    )

    lines = [
        f"\\begin{{{figure_env}}}[htbp]",
        "  \\centering",
    ]
    if fig_cap_pos == "top":
        lines.append(f"  \\caption{{{escape_text(caption)}}}")
        lines.append(f"  \\label{{fig:{idx}}}")
    lines.append(f"  \\includegraphics[width={img_width}]{{{path}}}")
    if fig_cap_pos == "bottom":
        lines.append(f"  \\caption{{{escape_text(caption)}}}")
        lines.append(f"  \\label{{fig:{idx}}}")
    lines.append(f"\\end{{{figure_env}}}")
    return lines


def _infer_column_alignments(headers: List[str], rows: List[List[str]], n_cols: int) -> str:
    """根据每列内容推断最佳对齐方式。

    策略：
    - 如果某列 >= 60% 的单元格是纯数字（含小数、百分比），右对齐 (r)
    - 否则如果某列 >= 60% 的单元格是短文本（<= 10 字符），居中 (c)
    - 否则左对齐 (l)
    """
    _NUM_RE = re.compile(r"^\s*[\+\-]?\d+(?:\.\d+)?(?:\s*%)?\s*$")
    aligns = []
    for col_idx in range(n_cols):
        numeric_count = 0
        short_text_count = 0
        total = 0
        for row in rows:
            if col_idx < len(row):
                cell = row[col_idx].strip()
                if cell:
                    total += 1
                    if _NUM_RE.match(cell):
                        numeric_count += 1
                    if len(cell) <= 10:
                        short_text_count += 1
        if total == 0:
            aligns.append("l")
            continue
        if numeric_count / total >= 0.6:
            aligns.append("r")
        elif short_text_count / total >= 0.6:
            aligns.append("c")
        else:
            aligns.append("l")
    return "".join(aligns)


def _render_table(block: Dict[str, Any], tables_map: Dict[int, Any], format_spec=None, is_double_column: bool = False) -> List[str]:
    idx = block.get("idx", 0)
    data = block.get("data") or {}
    caption = data.get("caption", "") or f"Table {idx}"
    headers = None
    rows = None

    tbl_obj = data.get("table_obj")
    if tbl_obj is not None:
        headers = getattr(tbl_obj, "headers", None)
        rows = getattr(tbl_obj, "rows", None)
    if (not headers or not rows) and idx in tables_map:
        t = tables_map[idx]
        headers = getattr(t, "headers", None) or []
        rows = getattr(t, "rows", None) or []

    if not headers or not rows:
        return [f"% table {idx} missing data"]

    n_cols = len(headers)
    # 智能列对齐 + 表头加粗
    col_fmt = _infer_column_alignments(headers, rows, n_cols)
    header_tex = " & ".join(f"\\textbf{{{escape_table_cell(h)}}}" for h in headers) + " \\\\"

    row_lines = []
    for row in rows:
        padded = list(row) + [""] * (n_cols - len(row))
        row_lines.append(
            "    " + " & ".join(escape_table_cell(c) for c in padded) + " \\\\"
        )

    tbl_cap_pos = getattr(format_spec, "table_caption_position", "top") if format_spec else "top"
    
    # 智能布局决策：双列模板中根据列数决定单列或双列
    use_double_column = False
    if is_double_column:
        use_double_column = _should_table_span_two_columns(n_cols, format_spec)
    
    table_env = "table*" if use_double_column else (
        getattr(format_spec, "table_env", "table") if format_spec else "table"
    )

    lines = [
        f"\\begin{{{table_env}}}[htbp]",
        "  \\centering",
    ]
    if tbl_cap_pos == "top":
        lines.append(f"  \\caption{{{escape_text(caption)}}}")
        lines.append(f"  \\label{{tab:{idx}}}")
    lines.extend([
        f"  \\begin{{tabular}}{{{col_fmt}}}",
        "    \\toprule",
        f"    {header_tex}",
        "    \\midrule",
    ])
    lines.extend(row_lines)
    lines.extend([
        "    \\bottomrule",
        "  \\end{tabular}",
    ])
    if tbl_cap_pos == "bottom":
        lines.append(f"  \\caption{{{escape_text(caption)}}}")
        lines.append(f"  \\label{{tab:{idx}}}")
    lines.append(f"\\end{{{table_env}}}")
    return lines


def _level_to_command(level: int) -> str:
    mapping = {1: "chapter", 2: "section", 3: "subsection", 4: "paragraph"}
    return mapping.get(level, "section")


def _strip_chapter_number(title: str) -> str:
    """'1 引言' → '引言'，但 '1.1 小节标题' 保留原样（因为 section 会自动编号）。"""
    m = re.match(r"^(\d+(?:\.\d+){0,3})\s+(.+)$", title.strip())
    if m:
        return m.group(2).strip()
    return title.strip()


# ============================================================
# 主渲染函数：从 blocks → 完整 .tex
# ============================================================
def render_document(
    blocks: List[Any],
    title: Optional[str] = None,
    author: str = "",
    images_map: Optional[Dict[int, Any]] = None,
    tables_map: Optional[Dict[int, Any]] = None,
    template: str = "nsfc",
    format_spec=None,
    is_double_column: bool = False,
) -> str:
    images_map = images_map or {}
    tables_map = tables_map or {}

    # --- 预扫描：如果有 title block，优先用它 ---
    extracted_title = None
    for b in blocks:
        t = b.type if hasattr(b, "type") else (b.get("type") if hasattr(b, "get") else "")
        if t == "title":
            content = b.content if hasattr(b, "content") else (b.get("content") or "")
            title_attr = b.title if hasattr(b, "title") else (b.get("title") or "")
            # 同时支持 content 和 title 字段
            extracted_title = content or title_attr
            if extracted_title:
                break

    final_title = title or extracted_title or "Untitled Document"

    # --- 语言检测：根据所有 block 内容判断是否为中文文档 ---
    def _detect_language(blks):
        for b in blks:
            text = ""
            if hasattr(b, "content") and isinstance(b.content, str):
                text += b.content
            if hasattr(b, "title") and isinstance(b.title, str):
                text += b.title
            for ch in text:
                if '\u4e00' <= ch <= '\u9fff':
                    return "zh"
        return "en"
    doc_lang = _detect_language(blocks)

    # --- 颜色定义收集器 ---
    color_defs: List[str] = []
    color_defs_set: set = set()

    # --- 开始生成 .tex ---
    out = [
        "\\documentclass[12pt,a4paper]{report}",
        "\\usepackage[UTF8]{ctex}",
        "\\usepackage{fontspec}",
        "\\usepackage{graphicx}",
        "\\usepackage{amsmath,amssymb}",
        "\\usepackage{booktabs}",
        "\\usepackage{geometry}",
        "\\usepackage{hyperref}",
        "\\usepackage{xcolor}",  # 富文本颜色支持
        "\\geometry{a4paper, margin=2.5cm}",
        "\\graphicspath{{./images/}}",
        "",
        f"\\title{{{escape_text(final_title)}}}",
        f"\\author{{{author}}}",
        "\\date{}",
        "",
        "\\begin{document}",
        "\\maketitle",
        "\\tableofcontents",
        "",
    ]

    # --- 状态机追踪 ---
    in_abstract_env = False     # 是否已经打开了 abstract 环境
    abstract_pending: List[str] = []  # 累积 abstract 正文
    in_abstract_en_env = False
    abstract_en_pending: List[str] = []
    in_bibliography_env = False
    bibliography_lines: List[str] = []

    def _flush_abstract():
        nonlocal in_abstract_env, abstract_pending
        if in_abstract_env and abstract_pending:
            out.append("\\begin{abstract}")
            for line in abstract_pending:
                out.append(line)
            out.append("\\end{abstract}")
            out.append("")
        in_abstract_env = False
        abstract_pending = []

    def _flush_abstract_en():
        nonlocal in_abstract_en_env, abstract_en_pending
        if in_abstract_en_env and abstract_en_pending:
            out.append("\\chapter*{Abstract}")
            out.append("\\markboth{Abstract}{Abstract}")
            for line in abstract_en_pending:
                out.append(line)
            out.append("")
        in_abstract_en_env = False
        abstract_en_pending = []

    def _flush_bibliography():
        nonlocal in_bibliography_env, bibliography_lines
        if in_bibliography_env and bibliography_lines:
            bib_title = "参考文献" if doc_lang == "zh" else "References"
            out.append("\\clearpage")
            out.append(f"\\section*{{{bib_title}}}")
            out.append(f"\\addcontentsline{{toc}}{{section}}{{{bib_title}}}")
            out.append("\\begin{thebibliography}{99}")
            for i, ref_line in enumerate(bibliography_lines):
                out.append(ref_line)
                # 在每个参考文献之间添加空行（最后一个除外）
                if i < len(bibliography_lines) - 1:
                    out.append("")
            out.append("\\end{thebibliography}")
            out.append("")
        in_bibliography_env = False
        bibliography_lines = []

    for idx, b in enumerate(blocks):
        btype = getattr(b, "type", "") or ""
        # 支持两种 blocks：document_reader (用 content/title) 和 _add_sec (用 _content_attr/_title_attr)
        content = getattr(b, "_content_attr", "") or getattr(b, "content", "") or ""
        blevel = getattr(b, "level", 0) or 0
        btitle = getattr(b, "_title_attr", "") or getattr(b, "title", "") or ""
        data = getattr(b, "data", {}) or {}
        bidx = getattr(b, "idx", 0) or 0

        # --- title block：只在文件开头出现一次，已在 \title 中使用 ---
        if btype == "title":
            continue

        # --- heading 章节标题 ---
        if btype == "heading":
            # 遇到新章节，先刷新 pending 环境
            _flush_abstract()
            _flush_abstract_en()
            _flush_bibliography()
            level = int(blevel or 1)
            cmd = _level_to_command(level)
            clean_title = _strip_chapter_number(btitle)
            out.append(f"\\{cmd}{{{escape_text(clean_title)}}}")
            out.append("")
            continue

        # --- abstract 中文摘要 ---
        if btype == "abstract":
            # 如果之前在英文摘要模式，先 flush
            _flush_abstract_en()
            text = content.strip()
            # 如果是单纯的 "摘要" 标题行，不加入正文
            if re.match(r"^\s*摘\s*要\s*$", text):
                in_abstract_env = True
                continue
            if in_abstract_env:
                abstract_pending.append(math_aware_escape(text))
                abstract_pending.append("")
            else:
                # 独立的摘要内容行，直接输出
                in_abstract_env = True
                abstract_pending.append(math_aware_escape(text))
                abstract_pending.append("")
            continue

        # --- abstract-en 英文摘要 ---
        if btype == "abstract-en":
            _flush_abstract()
            text = content.strip()
            if re.match(r"^\s*Abstract\s*[:：]?\s*$", text, re.IGNORECASE):
                in_abstract_en_env = True
                continue
            if in_abstract_en_env:
                abstract_en_pending.append(math_aware_escape(text))
                abstract_en_pending.append("")
            else:
                in_abstract_en_env = True
                abstract_en_pending.append(math_aware_escape(text))
                abstract_en_pending.append("")
            continue

        # --- keywords 关键词 ---
        if btype == "keywords":
            _flush_abstract()
            _flush_abstract_en()
            kw_text = content.strip()
            out.append("\\noindent\\textbf{Keywords:} " + escape_text(kw_text))
            out.append("")
            continue

        # --- references-heading 参考文献标题 ---
        if btype == "references-heading":
            _flush_abstract()
            _flush_abstract_en()
            # 如果之前不在参考文献区，先 flush 旧的 bibliography
            if not in_bibliography_env:
                _flush_bibliography()
            # 进入参考文献模式（即使标题为空也进入，确保后续 reference-item 被正确处理）
            in_bibliography_env = True
            bibliography_lines = []
            continue

        # --- reference-item 参考文献条目 ---
        def _flush_ref_line(ref_num: int, ref_body: str, bl: List[str]):
            """向 bibliography_lines 追加一个带编号的 bibitem，自动处理重名编号。"""
            ref_body = escape_text(ref_body)
            base_key = f"ref{ref_num}"
            key = base_key
            counter = 1
            existing_keys = set()
            for ln in bl:
                m2 = re.search(r"\\bibitem\{([^}]+)\}", ln)
                if m2:
                    existing_keys.add(m2.group(1))
            while key in existing_keys:
                key = f"ref{ref_num}_{counter}"
                counter += 1
            bl.append(f"\\bibitem{{{key}}} {ref_body}")

        if btype == "reference-item":
            m = re.match(r"^\s*\[(\d+)\]\s*(.+)$", content)
            if m:
                ref_num = int(m.group(1))
                ref_body = m.group(2).strip()
                _flush_ref_line(ref_num, ref_body, bibliography_lines)
            else:
                ref_body = escape_text(content.strip())
                bibliography_lines.append(f"\\bibitem{{ref{len(bibliography_lines)+1}}} {ref_body}")
            continue

        # --- image 图片 ---
        if btype == "image":
            _flush_abstract()
            _flush_abstract_en()
            lines = _render_figure(
                {"idx": bidx, "data": data},
                images_map,
                format_spec=format_spec,
                is_double_column=is_double_column,
            )
            out.extend(lines)
            out.append("")
            continue

        # --- table 表格 ---
        if btype == "table":
            _flush_abstract()
            _flush_abstract_en()
            lines = _render_table(
                {"idx": bidx, "data": data},
                tables_map,
                format_spec=format_spec,
                is_double_column=is_double_column,
            )
            out.extend(lines)
            out.append("")
            continue

        # --- text 普通段落 ---
        if btype == "text":
            if in_abstract_env:
                abstract_pending.append(math_aware_escape(content))
                abstract_pending.append("")
                continue
            if in_abstract_en_env:
                abstract_en_pending.append(math_aware_escape(content))
                abstract_en_pending.append("")
                continue
            if in_bibliography_env:
                # 参考文献区内的 text：
                # 1. 按换行拆分（应对 Word/LLM 整段传入的情况）
                # 2. 非编号行合并到上一个条目末尾（处理软换行导致的一条文献分多行）
                raw = content.strip()
                lines = raw.split("\n")
                i = 0
                while i < len(lines):
                    line = lines[i].strip()
                    if not line:
                        i += 1
                        continue
                    # 检测是否是带编号的文献行（如 [1] 或 [10]）
                    m = re.match(r"^\[(\d+)\]\s*(.+)$", line)
                    if m:
                        ref_num = int(m.group(1))
                        ref_body = m.group(2).strip()
                        _flush_ref_line(ref_num, ref_body, bibliography_lines)
                    else:
                        # 续行：合并到上一个条目
                        if bibliography_lines:
                            bibliography_lines[-1] = (
                                bibliography_lines[-1].rstrip(" .。") + " " + escape_text(line)
                            )
                        else:
                            # 没有前驱，作为无编号条目处理
                            bibliography_lines.append(escape_text(line))
                    i += 1
                continue

            # 将内容按行拆分，逐行检测独立公式行
            def _process_normal_text_block(normal_content):
                """处理普通文本块（不含独立公式行）"""
                # 整个段落的后备检测
                para_raw = normal_content.strip()
                if _is_standalone_formula(para_raw):
                    out.append("")
                    out.append(f"$$\\displaystyle {math_aware_escape(para_raw)}$$")
                    out.append("")
                    return

                # 普通正文：段落内可能有 [IMAGE:N] / [TABLE:N] 占位符（旧格式兼容）
                para = math_aware_escape(normal_content)
                image_matches = list(re.finditer(r"\[IMAGE:(\d+)\]", para))
                table_matches = list(re.finditer(r"\[TABLE:(\d+)\]", para))

                if not image_matches and not table_matches:
                    # 检查是否有富文本格式（颜色/bold/italic等）
                    rich_segments = b.data.get("rich_segments", [])
                    if rich_segments:
                        # 延迟导入避免循环依赖
                        from core.latex_builder_v2 import render_rich_segments
                        rendered_text, new_color_defs = render_rich_segments(rich_segments)
                        # 将颜色定义添加到导言区（去重）
                        for color_def in new_color_defs:
                            if color_def not in color_defs_set:
                                color_defs.append(color_def)
                                color_defs_set.add(color_def)
                        out.append(rendered_text)
                    else:
                        out.append(para)
                    out.append("")
                    return

                # 有占位符，按位置拆分
                all_markers = []
                for m in image_matches:
                    all_markers.append((m.start(), "image", int(m.group(1)), m.span()))
                for m in table_matches:
                    all_markers.append((m.start(), "table", int(m.group(1)), m.span()))
                all_markers.sort(key=lambda x: x[0])

                cursor = 0
                for pos, kind, m_idx, span in all_markers:
                    if pos > cursor:
                        piece = para[cursor:pos].strip()
                        if piece:
                            out.append(piece)
                    if kind == "image":
                        out.extend(_render_figure({"idx": m_idx, "data": {}}, images_map, format_spec=format_spec, is_double_column=is_double_column))
                    elif kind == "table":
                        out.extend(_render_table({"idx": m_idx, "data": {}}, tables_map, format_spec=format_spec, is_double_column=is_double_column))
                    cursor = span[1]
                if cursor < len(para):
                    tail = para[cursor:].strip()
                    if tail:
                        out.append(tail)
                out.append("")

            lines = content.split('\n')
            pending_lines = []
            for line in lines:
                stripped = line.strip()
                if _is_standalone_formula(stripped):
                    if pending_lines:
                        _process_normal_text_block('\n'.join(pending_lines))
                        pending_lines = []
                    out.append("")
                    out.append(f"$$\\displaystyle {math_aware_escape(stripped)}$$")
                    out.append("")
                else:
                    pending_lines.append(line)

            if pending_lines:
                _process_normal_text_block('\n'.join(pending_lines))
            continue

    # --- 结尾 flush 剩余环境 ---
    _flush_abstract()
    _flush_abstract_en()
    _flush_bibliography()

    # 在 \begin{document} 之前插入颜色定义
    if color_defs:
        # 找到 \\begin{document} 的位置
        doc_start_idx = None
        for i, line in enumerate(out):
            if line.strip() == "\\begin{document}":
                doc_start_idx = i
                break
        if doc_start_idx is not None:
            # 在 \\begin{document} 之前插入颜色定义
            color_lines = [""] + color_defs + [""]
            out = out[:doc_start_idx] + color_lines + out[doc_start_idx:]

    out.append("\\end{document}")
    return "\n".join(out)


def _escape_latex_ref(text: str) -> str:
    """LaTeX 特殊字符转义（用于参考文献 BibTeX 字段）。"""
    replacements = {
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
    for ch, repl in replacements.items():
        text = text.replace(ch, repl)
    return text


# ============================================================
# LLM 模式：从 original_sections 渲染（与上一个接口语义一致）
# ============================================================
def render_from_original_sections(
    sections: List[Dict[str, Any]],
    title: str = "",
    author: str = "",
    images_map: Optional[Dict[int, Any]] = None,
    tables_map: Optional[Dict[int, Any]] = None,
    references: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """兼容 LLM 输出的 original_sections 格式。"""
    # 将 sections 转换为 blocks，然后复用 render_document
    blocks: List[Any] = []
    if title:
        class _TitleBlock:
            type = "title"
            content = title
            level = 0
            _title_attr = ""
            idx = 0
            data = {}
        blocks.append(_TitleBlock())

    def _add_sec(sec: Dict[str, Any], parent_level: int = 0):
        level = sec.get("level", 1)
        if isinstance(level, str):
            level_map = {"chapter": 1, "section": 2, "subsection": 3, "paragraph": 4}
            level_int = level_map.get(level.lower(), parent_level + 1)
        else:
            level_int = int(level)

        _title = sec.get("title", "") or ""
        _sec_content = sec.get("content", "") or ""

        # 检测是否是参考文献章节
        is_ref_section = "参考文献" in _title or "reference" in _title.lower()

        # 清理参考文献章节的 content：去掉开头的 "参考文献：" 等标题残留
        if is_ref_section and _sec_content:
            # 去掉开头的 "参考文献：" / "参考文献" / "References：" / "References" 等行
            cleaned_lines = []
            for line in _sec_content.split("\n"):
                stripped = line.strip()
                # 跳过纯标题残留行
                if re.match(r"^参考文献[：:\s]*$", stripped, re.IGNORECASE):
                    continue
                if re.match(r"^References[：:\s]*$", stripped, re.IGNORECASE):
                    continue
                if re.match(r"^参考\s*$", stripped):
                    continue
                cleaned_lines.append(line)
            _sec_content = "\n".join(cleaned_lines)

        class _Heading:
            type = "references-heading" if is_ref_section else "heading"
            _title_attr = _title
            level = level_int
            idx = 0
            data = {}

        if _title:
            blocks.append(_Heading())

        # 关键：先处理当前层级的 content，再递归处理 subsections
        # 因为 API 可能把 content 放在当前层，也可能放在 subsections
        if _sec_content and _sec_content.strip():
            if is_ref_section:
                # 参考文献区：按空行/数字编号拆分每条参考文献
                ref_lines = []
                for raw_line in _sec_content.split("\n"):
                    stripped = raw_line.strip()
                    if stripped:
                        ref_lines.append(stripped)
                # 将连续行合并为一条参考文献：新条目的标志是 [数字] 或 作者名开头
                # 这里用简单策略：每行尝试判断是否是新条目
                def _is_ref_continuation(line):
                    # 续行：小写字母/URL/DOI/括号开头
                    return bool(
                        re.match(
                            r"^(?:[a-z]|http|DOI[:：]|https|\(|（|procedure|[（(][A-Z])",
                            line
                        )
                    )
                merged_refs = []
                for line in ref_lines:
                    if merged_refs and _is_ref_continuation(line):
                        merged_refs[-1] += " " + line
                    else:
                        merged_refs.append(line)
                # 为每条参考文献创建 reference-item block
                for ref_text in merged_refs:
                    class _RefItemText:
                        type = "reference-item"
                        _content_attr = ref_text
                        content = ref_text
                        _title_attr = ""
                        level = 0
                        idx = 0
                        data = {}
                    blocks.append(_RefItemText())
            else:
                class _Text:
                    type = "text"
                    _content_attr = _sec_content
                    _title_attr = ""
                    level = 0
                    idx = 0
                    data = {}
                blocks.append(_Text())

        subs = sec.get("subsections", []) or []
        for sub in subs:
            _add_sec(sub, level_int)

    for sec in sections:
        _add_sec(sec, 0)

    # 添加参考文献区
    if references:
        class _RefHeading:
            type = "references-heading"
            _title_attr = "参考文献"
            content = ""
            _content_attr = ""
            level = 1
            idx = 0
            data = {}
        blocks.append(_RefHeading())
        for ref in references:
            ref_key = ref.get("key", "")
            entry_type = ref.get("entry_type", "misc")
            fields = ref.get("fields", {})
            fields_str = ", ".join(
                f"{k}={{{_escape_latex_ref(str(v))}}}" for k, v in fields.items()
            )
            ref_text = f"@{entry_type}{{{ref_key}, {fields_str}}}"

            class _RefItem:
                type = "reference-item"
                content = ref_text
                _content_attr = ref_text
                _title_attr = ""
                level = 0
                idx = 0
                data = {"ref_key": ref_key}
            blocks.append(_RefItem())

    return render_document(
        blocks,
        title=title,
        author=author,
        images_map=images_map or {},
        tables_map=tables_map or {},
    )
