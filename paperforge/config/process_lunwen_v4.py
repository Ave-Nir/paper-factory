# -*- coding: utf-8 -*-
"""
正式项目：排版 work/论文.docx - 表格宽度优化版
优化方向：
1. 使用 tabularx 包自动调整列宽
2. 长文本列自动换行
3. 表格宽度设为 \textwidth
4. 解决三线表横向过长问题
输出目录：build_lunwen_v4（独立文件夹）
"""
import sys
import os
import subprocess
import re
import argparse
from pathlib import Path
from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_PARAGRAPH_ALIGNMENT
from docx.enum.section import WD_SECTION
from docx.oxml.ns import qn

sys.path.insert(0, '.')

from core.document_reader import read_document
from core.markdown_reader import read_markdown
from core.latex_builder import escape_text, escape_table_cell
from core.formatting import PRESET_FORMATS
from core.template_detector import TemplateDetector
from core.quality_inspector import QualityInspector
from core.input_validator import InputValidator
from gates.gate_system import Gate3FullBuild, Gate4FinalAudit


def _is_standalone_formula(text: str) -> bool:
    """判断一行文本是否为独立的数学公式。

    V7.6: 对于已用 $$...$$ 或 $...$ 包裹的公式，返回 True
    以便渲染器剥离已有定界符后重新正确包裹。
    """
    if not text or len(text) > 200:
        return False
    # V7.6: 已包裹的 $$...$$ 公式 → 返回 True（让渲染器剥离后重新包裹）
    if text.startswith("$$") and text.endswith("$$") and len(text) > 4:
        return True
    # 已包裹的 $...$ 公式 → 返回 True
    if text.startswith("$") and text.endswith("$") and not text.startswith("$$") and len(text) > 2:
        return True
    # V7.6: LaTeX 文本格式化命令开头的行不是公式
    for cmd in ('\\textbf{', '\\textit{', '\\emph{', '\\underline{', '\\texttt{',
                '\\textsf{', '\\textsc{', '表', '图'):
        if text.startswith(cmd):
            return False
    if text.startswith("http") or text.startswith("www"):
        return False
    if "字数" in text or "偏差" in text or "状态" in text or "合格" in text:
        return False
    # V7.6: 排除 LaTeX 字体/样式声明行（preamble 残留）
    # 这些行含有 LaTeX 样式的 [...] 选项，不是公式
    if text.startswith("SimSun") or text.startswith("SimHei") or text.startswith("KaiTi"):
        return False
    if text.startswith("FangSong") or text.startswith("Times"):
        return False
    if re.match(r'^\[(?:block|hang|display|leftmargin|rightmargin)\]', text):
        return False
    if re.match(r'^(?:font|labelsep|labelformat|labelfont|textfont)=', text):
        return False
    # V7.6: 排除路径/文件名行
    if './' in text or 'images/' in text:
        return False
    # V7.6: 排除纯 LaTeX preamble 命令（但保留数学符号如 \phi, \sum）
    # 检查是否以格式/样式命令开头（非数学命令）
    _non_math_prefixes = (
        r'\\section', r'\\subsection', r'\\subsubsection',
        r'\\textbf', r'\\textit', r'\\emph', r'\\underline',
        r'\\texttt', r'\\textsf', r'\\textsc',
        r'\\titleformat', r'\\captionsetup',
        r'\\setCJK', r'\\setmainfont', r'\\setsansfont',
        r'\\newcommand', r'\\renewcommand', r'\\DeclareMathOperator',
        r'\\fancy', r'\\geometry', r'\\hypersetup',
        r'\\graphicspath', r'\\pagestyle', r'\\pagenumbering',
        r'\\markboth', r'\\markright', r'\\addcontentsline',
        r'\\setcounter', r'\\setlength', r'\\linespread',
        r'\\clearpage', r'\\newpage', r'\\maketitle',
    )
    for prefix in _non_math_prefixes:
        if re.match(prefix, text):
            return False
    chinese_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    if chinese_chars > 0:
        # V7.6: 包含中文的行一定不是数学公式行（中文不应出现在 $$ 内）
        return False
    # V7.6: 纯分隔符号行不是公式（如 ---、===、***）
    has_letters_or_digits = any(c.isalpha() or c.isdigit() for c in text)
    if not has_letters_or_digits:
        return False
    math_symbols = set("=+-*/^_{}()[]|∥½¼¾¹²³⁰⁴⁵⁶⁷⁸⁹₀₁₂₃₄₅₆₇₈₉αβγδεζηθικλμνξοπρστυφχψωΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ∑∏∫∂√∞≈≠≤≥±×÷·∂∇⊗⊕∧∨¬∃∀∈∉⊂⊃⊆⊇∪∩∅→←↑↓↔⇒⇔≡≜≝≞")
    math_functions = ["exp", "log", "ln", "sin", "cos", "tan", "max", "min", "arg", "sup", "inf", "lim", "sum", "prod", "int", "det", "tr", "rank", "var", "cov", "std", "mean", "median", "mode", "D_KL", "JSD", "KL", "N(", "K /", "t₀", "r₀"]
    has_math_symbol = any(c in math_symbols for c in text)
    has_math_func = any(func in text for func in math_functions)
    if not ("=" in text or has_math_symbol or has_math_func):
        return False
    return True


def read_input_document(file_path: str, build_dir: str = "."):
    """根据文件扩展名自动选择读取器。

    - .md / .markdown → Markdown 解析器
    - .tex → LaTeX 解析器
    - .docx → Word 文档解析器
    - .json → PaperSpec JSON（NL Intake 产物）
    """
    ext = os.path.splitext(file_path)[1].lower()
    if ext in ('.md', '.markdown'):
        return read_markdown(file_path)
    elif ext == '.tex':
        from core.tex_reader import read_tex
        return read_tex(file_path)
    elif ext == '.docx':
        return read_document(file_path, build_dir)
    elif ext == '.json':
        from core.nl_to_document import (
            deserialize_intake_output, build_document_content,
        )
        import json as _json
        payload = _json.loads(open(file_path, encoding="utf-8").read())
        paper_spec, ref_db, section_data_map = deserialize_intake_output(payload)
        return build_document_content(paper_spec, ref_db, section_data_map)
    else:
        raise ValueError(f"不支持的文件格式: {ext}（支持 .docx / .md / .markdown / .tex / .json）")


def convert_citations(text: str) -> str:
    def _replace_cite(match):
        nums = match.group(1).split(',')
        refs = ','.join(f'ref{n.strip()}' for n in nums)
        return f'\\textsuperscript{{\\cite{{{refs}}}}}'
    
    text = re.sub(r'\[(\d+(?:\s*,\s*\d+)*)\]', _replace_cite, text)
    return text


def convert_figure_table_refs(text: str) -> str:
    """将正文中的'图X'、'表X'、'如图X所示'、'见表X'等转换为 LaTeX \\ref 引用。"""
    
    def _replace_fig_ref(match):
        prefix = match.group(1)
        num = match.group(2)
        suffix = match.group(3) if match.group(3) else ''
        return f'{prefix}\\ref{{fig:{num}}}{suffix}'
    
    def _replace_tab_ref(match):
        prefix = match.group(1)
        num = match.group(2)
        suffix = match.group(3) if match.group(3) else ''
        return f'{prefix}\\ref{{tab:{num}}}{suffix}'
    
    # 图片引用：如图X所示、图X、图 X 等
    # 匹配 "如图X所示"、"如图 X 所示"、"在图X中" 等模式
    text = re.sub(
        r'(如|在|见|查看|参考)(图|Figure|Fig\.?)\s*(\d+)\s*(所示|中|如下)?',
        lambda m: f'{m.group(1)}{m.group(2)}\\ref{{fig:{m.group(3)}}}{m.group(4) if m.group(4) else ""}',
        text,
        flags=re.IGNORECASE,
    )
    
    # 表格引用：如表X所示、表X、见表X等
    text = re.sub(
        r'(如|在|见|查看|参考)(表|Table|Tab\.?)\s*(\d+)\s*(所示|中|如下)?',
        lambda m: f'{m.group(1)}{m.group(2)}\\ref{{tab:{m.group(3)}}}{m.group(4) if m.group(4) else ""}',
        text,
        flags=re.IGNORECASE,
    )
    
    return text


def enhance_generality(text: str) -> str:
    replacements = [
        (r'本文([围绕针对]|[基基]于)', r'该方法\1'),
        (r'本文[提给]出', r'该方法提出'),
        (r'本文[建构]立', r'建立'),
        (r'本文[实完]成', r'完成'),
        (r'本文[研分]究', r'研究'),
        (r'本文[结]果', r'计算结果'),
        (r'本文[显表]明', r'结果表明'),
        (r'本文[认认]为', r'研究表明'),
        (r'本研究([实提]|发现|结果)', r'研究\1'),
        (r'本研究中', r'研究中'),
        (r'本研究[针围]', r'研究针'),
        (r'实装任务', r'工程应用'),
        (r'实装应用', r'工程应用'),
        (r'大单位内部', r'工程应用场景'),
        (r'基于', r'基于通用'),
        (r'方法', r'工程方法'),
        (r'流程', r'标准化流程'),
        (r'步骤', r'标准化步骤'),
    ]
    
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text)
    
    return text


def enhance_math_recognition(text: str, do_escape: bool = True) -> str:
    # ── V6.4 fix: 先保护已有的 $...$ / $$...$$ 数学块，避免后续替换破坏 LaTeX ──
    _early_math_blocks = {}
    _early_counter = [0]

    def _protect_early_math(m):
        placeholder = f"__EARLYMATH_{_early_counter[0]}__"
        _early_math_blocks[placeholder] = m.group(0)
        _early_counter[0] += 1
        return placeholder

    # 先保护 $$...$$（显示公式），再保护 $...$（行内公式）
    text = re.sub(r'\$\$(.+?)\$\$', _protect_early_math, text, flags=re.DOTALL)
    text = re.sub(r'\$[^$]+?\$', _protect_early_math, text)

    # 数学处理在前，转义在后（因为 _ 和 $ 已在数学下标中使用）
    text = text.replace('×', '$' + '\\times' + '$')
    text = text.replace('·', '$' + '\\cdot' + '$')
    # 将"数字度"形式转换为"数字°"：45度 → 45°, 32.0度 → 32.0°
    # 排除中文词汇中的"度"（精度、高度、纬度、湿度、温度、强度等）
    # 只替换数字后面直接跟"度"的情况
    text = re.sub(r'(\d+(?:\.\d+)?)\s*度(?![A-Za-z])', lambda m: m.group(1) + '°', text)
    # 处理度符号后面跟N/S/E/W的情况：30°N → 30$^\circ$N
    text = re.sub(r'(\d+(?:\.\d+)?)\^°', lambda m: m.group(1) + '$^\\circ$', text)
    text = re.sub(r'([A-Za-z])\^°', lambda m: m.group(1) + '$^\\circ$', text)
    # 替换剩余的 ° 为 LaTeX 公式（上标形式）
    text = text.replace('°', '$^\\circ$')

    # 希腊字母识别：识别作为单位前缀或独立符号的希腊字母
    # - 独立出现: 前后都不是字母（μ → $\mu$）
    # - 作为单位前缀: μ 后跟大写字母或单位（μV, μA, μF, μs 等）
    # 不识别：作为变量名的一部分（如 x_μ 中的下标）——这种情况极少，已被下标规则覆盖
    _GREEK_LETTERS = {
        'α': 'alpha', 'β': 'beta', 'γ': 'gamma', 'δ': 'delta',
        'ε': 'epsilon', 'ζ': 'zeta', 'η': 'eta', 'θ': 'theta',
        'ι': 'iota', 'κ': 'kappa', 'λ': 'lambda', 'μ': 'mu',
        'ν': 'nu', 'ξ': 'xi', 'ο': 'omicron', 'π': 'pi',
        'ρ': 'rho', 'σ': 'sigma', 'τ': 'tau', 'υ': 'upsilon',
        'φ': 'phi', 'χ': 'chi', 'ψ': 'psi', 'ω': 'omega',
    }
    for greek_char, latex_name in _GREEK_LETTERS.items():
        # 独立出现的希腊字母，或前后跟数字（如 Aβ40 → A$\beta$40）
        text = re.sub(
            greek_char,
            lambda m: '$\\' + latex_name + '$',
            text
        )
    # μ 后跟单位字母：μV, μA, μF, μH, μs, μW, μHz 等
    text = re.sub(r'μ(?=[VAFHNSWs]|[VAFH]\b)', lambda m: '$' + '\\mu' + '$', text)
    text = re.sub(r'μ(?=Hz|hz|Hz\b)', lambda m: '$' + '\\mu' + '$', text)

    # 识别并保护连续下划线的代码/变量名（如 min_cluster_size, hf_assessment）
    # 这些应该转义下划线而不是当作数学下标
    # 关键：只保护 **小写字母开头** 的变量名（min_cluster_size, hf_assessment）
    # 避免把数学变量（如 E_w, P_t, G_t, L_b 等大写字母开头的下标符号）误识别为代码变量
    protected_vars = {}
    var_counter = 0

    def _protect_var(match):
        nonlocal var_counter
        var_name = match.group(0)
        placeholder = f"__VAR_{var_counter}__"
        protected_vars[placeholder] = var_name.replace('_', '\\_')
        var_counter += 1
        return placeholder

    # 保护小写字母开头的变量名（如 min_cluster_size）
    text = re.sub(r'\b[a-z][a-zA-Z0-9]*(?:_[a-zA-Z0-9]+)+', _protect_var, text)

    # 保护大写字母开头的数学符号（如 D_KL, JSD, KL 等）
    math_symbols = ['D_KL', 'D_{KL}', 'KL', 'JSD', 'N_0', 'N_t', 'E_w', 'P_t', 'G_t', 'L_b']
    for symbol in math_symbols:
        if '_' in symbol:
            escaped = symbol.replace('_', r'\_')
            text = text.replace(symbol, '$' + escaped + '$')

    def _math_sub(m):
        return '$' + m.group(1) + '_{' + m.group(2) + '}' + '$'
    # 识别 letter_digit+ 形式的下标（如 x_1, P_2）
    text = re.sub(r'(?<![a-zA-Z/_])([A-Za-z])_(\d+)(?![a-zA-Z0-9/_])',
                  _math_sub, text)

    # 包裹已经写成 P_{xxx} 的下标（Word 原文已含大括号形式，如 P_{measured}）
    def _wrap_brace_sub(m):
        return '$' + m.group(1) + '_{' + m.group(2) + '}' + '$'
    # 在 ( 前面加 $，避免重复处理已经被 _math_sub 处理过的下标
    text = re.sub(r'(?<![a-zA-Z/$])(\w)_\{([^{}]+)\}(?![a-zA-Z/_])',
                  _wrap_brace_sub, text)

    # 包裹 P_measured 形式的单下标（letter_letter 模式）
    def _simple_sub(m):
        return '$' + m.group(1) + '_{' + m.group(2) + '}' + '$'
    text = re.sub(
        r'(?<![a-zA-Z/_])([A-Za-z])_([a-z]+)(?![a-zA-Z0-9/_])',
        _simple_sub, text,
    )

    # 还原保护的变量名（用转义后的下划线替换占位符）
    for placeholder, escaped_var in protected_vars.items():
        text = text.replace(placeholder, escaped_var)

    # ── V6.4 fix: 还原早期保护的数学块 ──
    for placeholder, math_block in _early_math_blocks.items():
        text = text.replace(placeholder, math_block)

    # 最后转义剩余的特殊字符（&, %, #, {, }, ~, ^, \）
    # 但不转义数学模式中的 $ 和 _（已在上面处理）
    # 先保护数学模式中的内容
    math_blocks = {}
    math_counter = 0
    def _protect_math(m):
        nonlocal math_counter
        placeholder = f"__MATH_{math_counter}__"
        math_blocks[placeholder] = m.group(0)
        math_counter += 1
        return placeholder
    # 保护 $...$ 形式的数学模式
    text = re.sub(r'\$[^$]+\$', _protect_math, text)

    # V7.6: 保护 LaTeX 命令（避免花括号被转义破坏）
    _latex_blocks = {}
    _latex_counter = [0]
    def _protect_latex_cmd(m):
        key = f"__LATEXCMD_{_latex_counter[0]}__"
        _latex_blocks[key] = m.group(0)
        _latex_counter[0] += 1
        return key
    text = re.sub(
        r'\\(?:textbf|textit|emph|underline|texttt|textsf|textsc|textsuperscript|'
        r'cite|ref|label|caption|heiti|CJKfamily)\{[^}]*\}',
        _protect_latex_cmd, text,
    )
    # V7.6: 保护 LaTeX 特殊字符转义（\{、\}、\$、\#、\&、\%、\_）
    text = re.sub(r'\\[{}&#$_]', _protect_latex_cmd, text)

    if do_escape:
        # 逐字符转义非数学相关的特殊字符（避免重复转义）
        _CHAR_ESCAPE = {
            "&": r"\&",
            "%": r"\%",
            "#": r"\#",
            "{": r"\{",
            "}": r"\}",
            "~": r"\textasciitilde{}",
            "^": r"\textasciicircum{}",
        }
        result_chars = []
        for ch in text:
            result_chars.append(_CHAR_ESCAPE.get(ch, ch))
        text = ''.join(result_chars)

    # 还原 LaTeX 命令
    for placeholder, original in _latex_blocks.items():
        text = text.replace(placeholder, original)

    # 还原数学模式
    for placeholder, math_block in math_blocks.items():
        text = text.replace(placeholder, math_block)

    return text


def _output_accumulated_abstract(out, abstract_output, keywords_output, abstract_en_output, keywords_en_output, has_chapter=True):
    if abstract_output:
        out.append("\\begin{abstract}")
        out.extend(abstract_output)
        if keywords_output:
            out.append("")
            for kw in keywords_output:
                out.append(f"\\par\\textbf{{关键词：}}{kw}")
        out.append("\\end{abstract}")
        out.append("")

    out.append("\\tableofcontents")
    out.append("\\clearpage")
    out.append("")

    if abstract_en_output:
        if has_chapter:
            out.append("\\chapter*{Abstract}")
            out.append("\\markboth{Abstract}{Abstract}")
        else:
            out.append("\\section*{Abstract}")
            out.append("\\markboth{Abstract}{Abstract}")
        for line in abstract_en_output:
            out.append(line)
        out.append("")
        if keywords_en_output:
            for kw in keywords_en_output:
                out.append(f"\\par\\textbf{{Key words:}}{kw}")
            out.append("")


# 模板 → (文档类, 文档类选项)
_LATEX_DOC_CLASS_MAP = {
    "nsfc":       ("ctexart",    "12pt,a4paper"),
    "sci":        ("ctexart",    "12pt,a4paper"),
    "thesis":     ("ctexrep",    "12pt,a4paper"),
    "humanities": ("ctexart",    "12pt,a4paper"),
    "renai":      ("article",    "12pt,a4paper"),
    "ieee":       ("IEEEtran",   "conference,10pt,a4paper"),
    "icml2025":   ("article",    "10pt,a4paper"),
    "cvpr2024":   ("article",    "10pt,a4paper"),
    "neurips2024":("article",    "10pt,a4paper"),
    "acl2024":    ("article",    "11pt,a4paper"),
}

# 双列模板列表（需要智能布局决策）
_DOUBLE_COLUMN_TEMPLATES = ["ieee"]


def _should_figure_span_two_columns(width, height, format_spec=None):
    """判断图片是否应占双列。宽高比 >= threshold 时占双列"""
    if width <= 0 or height <= 0:
        return False
    threshold = getattr(format_spec, "image_aspect_threshold", 1.5) if format_spec else 1.5
    aspect_ratio = width / height
    return aspect_ratio >= threshold


def _should_table_span_two_columns(n_cols, format_spec=None):
    """判断表格是否应占双列。列数 >= threshold 时占双列"""
    threshold = getattr(format_spec, "table_column_threshold", 4) if format_spec else 4
    return n_cols >= threshold


def _reorder_ack_appendix(blocks):
    """
    预处理：确保附录在致谢之后（按规范顺序）。
    
    如果检测到附录出现在致谢之前，则将所有附录区块移到致谢之后。
    """
    import re
    
    def _is_ack_heading(b):
        if getattr(b, "type", "") != "heading":
            return False
        data = getattr(b, "data", {}) or {}
        if data.get("is_acknowledgements", False):
            return True
        title = getattr(b, "title", "")
        return bool(re.match(r"^\s*致\s*谢", title, re.IGNORECASE)) or bool(re.match(r"^\s*Acknowledg?ments?", title, re.IGNORECASE))
    
    def _is_appendix_heading(b):
        if getattr(b, "type", "") != "heading":
            return False
        data = getattr(b, "data", {}) or {}
        if data.get("is_appendix", False):
            return True
        title = getattr(b, "title", "")
        return bool(re.match(r"^\s*附\s*录", title, re.IGNORECASE)) or bool(re.match(r"^\s*Appendix", title, re.IGNORECASE))
    
    ack_idx = None
    first_appendix_idx = None
    
    for i, b in enumerate(blocks):
        if ack_idx is None and _is_ack_heading(b):
            ack_idx = i
        if first_appendix_idx is None and _is_appendix_heading(b):
            first_appendix_idx = i
    
    if ack_idx is None or first_appendix_idx is None or first_appendix_idx > ack_idx:
        return blocks
    
    # 收集附录区块（从第一个附录标题到致谢标题之前）
    appendix_blocks = blocks[first_appendix_idx:ack_idx]
    before_appendix = blocks[:first_appendix_idx]
    from_ack = blocks[ack_idx:]
    
    # 找到致谢内容的结束位置（致谢标题 + 所有非heading内容）
    ack_end = 1
    while ack_end < len(from_ack) and getattr(from_ack[ack_end], "type", "") != "heading":
        ack_end += 1
    
    ack_blocks = from_ack[:ack_end]
    after_ack = from_ack[ack_end:]
    
    return before_appendix + ack_blocks + appendix_blocks + after_ack


def render_enhanced_latex(doc, build_dir, format_spec=None, template="nsfc"):
    from core.formatting import FormatSpec
    from core.latex_builder import render_document
    spec = format_spec or FormatSpec()

    title = ""
    for b in doc.blocks:
        if getattr(b, "type", "") == "title":
            # 同时支持 content 和 title 字段（NL Intake 模式下标题放在 title 字段）
            title = getattr(b, "content", "") or getattr(b, "title", "")
            break

    # 选择文档类
    doc_class, doc_options = _LATEX_DOC_CLASS_MAP.get(template, ("ctexart", "12pt,a4paper"))
    has_chapter = doc_class in ("ctexrep", "ctexbook", "report", "book")

    # 导言区宏包
    packages = [
        "\\usepackage{fontspec}",
        "\\usepackage{graphicx}",
        "\\usepackage{amsmath,amssymb}",
        "\\usepackage{booktabs}",
        "\\usepackage{geometry}",
        "\\usepackage{hyperref}",
        "\\usepackage{xcolor}",
        "\\usepackage{tabularx}",
        "\\usepackage{ragged2e}",
        "\\usepackage{setspace}",
        "\\usepackage{fancyhdr}",
        "\\usepackage{lastpage}",
        "\\usepackage{caption}",
        "\\usepackage{titlesec}",
    ]
    # ctex* 文档类（ctexart/ctexrep/ctexbook）已内置 ctex，无需额外加载
    # 非 ctex* 文档类（article/report等）且为中文模板时加载
    # 注意：renai 模板在 MiKTeX sandbox 中 ctex 会崩溃，改用 xeCJK
    if doc_class not in ("ctexart", "ctexrep", "ctexbook") and template in ("nsfc", "sci", "thesis", "humanities"):
        packages.insert(0, "\\usepackage[UTF8]{ctex}")
    elif template == "renai":
        packages.insert(0, "\\usepackage{xeCJK}")
        packages.insert(1, "\\setCJKmainfont{SimSun}[BoldFont=SimHei,ItalicFont=KaiTi]")
        packages.insert(2, "\\setCJKsansfont{SimHei}")
        packages.insert(3, "\\setCJKmonofont{FangSong}")
        packages.insert(4, "\\setCJKfamilyfont{hei}{SimHei}")
        packages.insert(5, "\\newcommand{\\heiti}{\\CJKfamily{hei}}")

    # 章节命令映射
    if has_chapter:
        section_cmd = {1: "chapter", 2: "section", 3: "subsection"}
    else:
        section_cmd = {1: "section", 2: "subsection", 3: "subsubsection"}

    out = [
        f"\\documentclass[{doc_options}]{{{doc_class}}}",
    ]
    out.extend(packages)
    if doc_class in ("ctexart", "ctexrep", "ctexbook"):
        out.append("\\ctexset{section={format=\\raggedright}}")
        out.append("\\ctexset{subsection={format=\\raggedright}}")
        out.append("\\ctexset{subsubsection={format=\\raggedright}}")
        # 仁爱学院毕设模板（按《毕设学生手册（2026届修订版）》）
        # 一级标题：黑体小三号（15pt）居中
        # 二级标题：黑体四号（14pt）顶格
        # 三级标题：黑体四号（14pt）顶格
        # 正文：宋体小四号（12pt）
        # 图表标题：五号（10.5pt）
        if template == "renai":
            # titlesec 已在导言区加载；为各章节设置字号
            if has_chapter:
                # 一级标题 chapter：黑体小三号（15pt）左对齐
                out.append("\\titleformat{\\chapter}[block]{\\heiti\\fontsize{15pt}{21pt}\\selectfont\\bfseries\\raggedright}{\\chinese{chapter}、}{0pt}{}")
                out.append("\\titleformat{\\section}[block]{\\heiti\\fontsize{14pt}{20pt}\\selectfont\\bfseries\\raggedright}{\\thesection}{0.5em}{}")
                out.append("\\titleformat{\\subsection}[block]{\\heiti\\fontsize{14pt}{20pt}\\selectfont\\bfseries\\raggedright}{\\thesubsection}{0.5em}{}")
            else:
                # ctexart：section 一级标题（15pt），subsection 二级（14pt），subsubsection 三级（14pt）
                out.append("\\titleformat{\\section}[block]{\\heiti\\fontsize{15pt}{21pt}\\selectfont\\bfseries\\raggedright}{\\thesection}{0.5em}{}")
                out.append("\\titleformat{\\subsection}[block]{\\heiti\\fontsize{14pt}{20pt}\\selectfont\\bfseries\\raggedright}{\\thesubsection}{0.5em}{}")
                out.append("\\titleformat{\\subsubsection}[block]{\\heiti\\fontsize{14pt}{20pt}\\selectfont\\bfseries\\raggedright}{\\thesubsubsection}{0.5em}{}")
            # 正文：宋体小四号（12pt）
            out.append("\\setmainfont{Times New Roman}")
            out.append("\\setsansfont{Arial}")
            # caption：图表标题五号（10.5pt）
            out.append("\\captionsetup{font={small,bf},labelsep=quad,labelformat={default}}")
    # renai 模板使用 xeCJK（非 ctex），单独处理标题格式
    if template == "renai" and doc_class not in ("ctexart", "ctexrep", "ctexbook"):
        # article 文档类：section 一级标题（15pt），subsection 二级（14pt），subsubsection 三级（14pt）
        out.append("\\titleformat{\\section}[block]{\\heiti\\fontsize{15pt}{21pt}\\selectfont\\raggedright}{\\thesection}{0.5em}{}")
        out.append("\\titleformat{\\subsection}[block]{\\heiti\\fontsize{14pt}{20pt}\\selectfont\\raggedright}{\\thesubsection}{0.5em}{}")
        out.append("\\titleformat{\\subsubsection}[block]{\\heiti\\fontsize{14pt}{20pt}\\selectfont\\raggedright}{\\thesubsubsection}{0.5em}{}")
        out.append("\\setmainfont{Times New Roman}")
        out.append("\\setsansfont{Arial}")
        out.append("\\captionsetup{font={small,bf},labelsep=quad,labelformat={default}}")
    out.extend([
        f"\\geometry{{a4paper, top={spec.top_margin}cm, bottom={spec.bottom_margin}cm, left={spec.left_margin}cm, right={spec.right_margin}cm}}",
        "\\graphicspath{{./images/}}",
        f"\\setstretch{{{spec.line_spacing}}}",
        "",
        # 页眉页脚设置（仁爱学院毕设要求）
        "\\pagestyle{fancy}",
        "\\fancyhf{}",
        "\\fancyfoot[C]{\\small \\thepage\\ / \\pageref{LastPage}}",
        "\\fancyhead[L]{\\small \\leftmark}",
        "\\fancyhead[R]{\\small \\rightmark}",
        "\\renewcommand{\\headrulewidth}{0.4pt}",
        "\\renewcommand{\\footrulewidth}{0pt}",
        "\\setlength{\\headheight}{15pt}",
        "",
        "\\title{" + escape_text(title) + "}",
    ])
    
    # 第一次遍历：收集作者信息（在摘要之前的文本）并记录需要跳过的 block 索引
    author_info = []
    affiliation_info = []
    author_block_indices = []
    
    for idx, block in enumerate(doc.blocks):
        btype = getattr(block, "type", "")
        content = getattr(block, "content", "")
        
        if btype == "abstract" or btype == "abstract-en":
            break
        
        if btype == "heading":
            break
        
        if btype == "text":
            text = content.strip()
            if not text:
                continue
            
            # 作者姓名模式：纯中文汉字 2-5 字，或英文名（First Last，首字母大写，2-4个词）
            if re.match(r'^[\u4e00-\u9fff]{2,5}$', text):
                author_info.append(text)
                author_block_indices.append(idx)
                continue
            # 英文名模式：2-4 个首字母大写的单词，不含标点（如 "John Smith", "Alice Bob Chen"）
            if re.match(r'^[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+){1,3}$', text) and len(text.split()) <= 4:
                author_info.append(text)
                author_block_indices.append(idx)
                continue
            # 单位模式：包含学术/机构关键词（中英文）
            affiliation_keywords = [
                '大学', '学院', '系', '班级', '专业', '研究所', '研究院', '实验室', '中心', '公司',
                'School', 'College', 'Department', 'University', 'Institute', 'Laboratory',
                'Lab', 'Center', 'Centre', 'Corporation', 'Inc', 'Ltd', 'Company',
            ]
            if any(keyword in text for keyword in affiliation_keywords):
                affiliation_info.append(text)
                author_block_indices.append(idx)
                continue
    
    # 构建作者信息（\author 参数中不能用 \par 或 \\，使用 \and 或简单文本）
    author_parts = []
    if author_info:
        author_parts.append("\\textbf{" + escape_text(" ".join(author_info)) + "}")
    if affiliation_info:
        if author_info:
            author_parts.append("\\quad " + escape_text(" ".join(affiliation_info)))
        else:
            author_parts.append(escape_text(" ".join(affiliation_info)))
    
    author_text = " ".join(author_parts)
    
    out.append("\\author{" + author_text + "}")
    out.append("\\date{}")
    out.extend([
        "",
        "\\begin{document}",
        "\\maketitle",
        "\\thispagestyle{empty}",
        "\\clearpage",
        "",
        # 摘要部分使用罗马数字页码
        "\\pagenumbering{Roman}",
        "\\pagestyle{fancy}",
        "",
    ])
    
    in_abstract = False
    in_keywords = False
    in_abstract_en = False
    abstract_output = []
    keywords_output = []
    abstract_en_output = []
    keywords_en_output = []
    in_bibliography = False
    bib_lines = []
    bib_heading_output = False
    table_idx = 0
    fig_idx = 0
    page_numbering_set = False
    in_acknowledgements = False
    in_appendix = False
    author_info = []
    affiliation_info = []
    toc_done = False  # 确保目录只输出一次
    in_multiline_math = False  # V7.6: 跨 block 跟踪多行公式
    
    # 预处理：确保附录在致谢之后（按规范顺序）
    blocks = _reorder_ack_appendix(list(doc.blocks))
    # 移除已收集为作者信息的 block（按索引过滤）
    blocks = [b for i, b in enumerate(blocks) if i not in author_block_indices]
    
    for block_idx, block in enumerate(blocks):
        btype = getattr(block, "type", "")
        content = getattr(block, "content", "")
        data = getattr(block, "data", {})
        
        if btype == "title":
            continue
        
        if btype == "heading":
            # 如果在参考文献模式下遇到heading（如致谢），先输出已收集的参考文献
            if in_bibliography and bib_lines:
                # 不主动添加标题，由 \thebibliography 环境自动生成
                out.append("\\begin{thebibliography}{99}")
                for line in bib_lines:
                    out.append(line)
                out.append("\\end{thebibliography}")
                out.append("")
                bib_lines = []

            # 在进入正文前，输出累积的摘要/关键词/目录（无论是否有摘要，目录都应输出，但只输出一次）
            if not toc_done:
                _output_accumulated_abstract(out, abstract_output, keywords_output, abstract_en_output, keywords_en_output, has_chapter)
                toc_done = True
            abstract_output = []
            keywords_output = []
            abstract_en_output = []
            keywords_en_output = []

            level = getattr(block, "level", 1)
            heading_title = getattr(block, "title", "")
            # 保留原文标题（含序号），不做序号去除
            # 使用不自动编号的命令（chapter*/section*/subsection*）避免双重序号
            clean_title = enhance_generality(heading_title.strip())

            # 智能层级调整：识别"一、二、三"为一级标题，"3.1、3.2"为二级标题
            original_level = level
            if level == 1:
                # 检查是否为"数字.数字"格式的二级标题（如"3.1"、"4.2"）
                if re.match(r'^\d+\.\d+', heading_title):
                    level = 2  # 降为二级标题
                # 检查是否为中文"一、二、三、四、五、六、七、八、九、十"格式的一级标题
                elif re.match(r'^[一二三四五六七八九十]+、', heading_title):
                    level = 1  # 保持一级标题

            # 页码区域控制（仁爱学院毕设要求）
            is_ack = data.get("is_acknowledgements", False) or re.match(r"^\s*致\s*谢", heading_title, re.IGNORECASE) or re.match(r"^\s*Acknowledg?ments?", heading_title, re.IGNORECASE)
            is_app = data.get("is_appendix", False) or re.match(r"^\s*附\s*录", heading_title, re.IGNORECASE) or re.match(r"^\s*Appendix", heading_title, re.IGNORECASE)
            
            if is_ack:
                in_acknowledgements = True
                out.append("\\pagestyle{empty}")
            elif is_app:
                if not in_appendix:
                    in_appendix = True
                    out.append("\\pagestyle{fancy}")
                    out.append("\\setcounter{page}{1}")
            elif level == 1 and not page_numbering_set and not in_acknowledgements and not in_appendix:
                page_numbering_set = True
                out.append("\\pagestyle{fancy}")
                out.append("\\setcounter{page}{1}")
                out.append("\\pagenumbering{arabic}")

            cmd = section_cmd.get(level, "section")
            # level 1 大标题另起一页（ctexart 的 \section 默认不换页）
            if level == 1:
                out.append("\\clearpage")
            # 使用带星号的命令（不自动编号），保留原文序号
            out.append(f"% [LOC:heading:{block_idx}:level{level}]")
            out.append(f"\\{cmd}*{{{escape_text(clean_title)}}}")
            # 设置页眉（\chapter*不会自动设置页眉）
            if level == 1:
                out.append(f"\\markboth{{{escape_text(clean_title)}}}{{{escape_text(clean_title)}}}")
            # 手动添加到目录
            toc_cmd = "chapter" if has_chapter else "section"
            if level == 1:
                toc_cmd = "chapter" if has_chapter else "section"
            elif level == 2:
                toc_cmd = "section" if has_chapter else "subsection"
            else:
                toc_cmd = "subsection" if has_chapter else "subsubsection"
            out.append(f"\\addcontentsline{{toc}}{{{toc_cmd}}}{{{escape_text(clean_title)}}}")
            out.append("")
            in_abstract = False
            in_bibliography = False
            continue
        
        if btype == "abstract":
            text = content.strip()
            if re.match(r"^\s*摘\s*要\s*$", text):
                out.append(f"% [LOC:abstract:{block_idx}:chinese]")
                in_abstract = True
                continue
            if re.match(r"^\s*Abstract\s*$", text, re.IGNORECASE):
                out.append(f"% [LOC:abstract:{block_idx}:english]")
                in_abstract_en = True
                continue
            continue

        if btype == "abstract-en":
            in_abstract = False
            in_keywords = False
            in_abstract_en = True
            continue
        
        if btype == "text":
            text = content.strip()
            
            # 关键词检测：支持"关键词"、"关键字"、"Key words"、"Keywords"等多种变体
            if re.match(r"^\s*关键(词|字)", text):
                out.append(f"% [LOC:keywords:{block_idx}:chinese]")
                in_abstract = False
                in_keywords = True
                in_abstract_en = False
                kw = re.sub(r"^关键(词|字)[：:]\s*", "", text)
                keywords_output.append(escape_text(kw))
                continue
            
            if re.match(r"^\s*(Key\s*words|Keywords|KeyWords)", text, re.IGNORECASE):
                out.append(f"% [LOC:keywords:{block_idx}:english]")
                in_abstract = False
                in_keywords = False
                in_abstract_en = False
                kw = re.sub(r"^(Key\s*words|Keywords|KeyWords)[\s:：]*", "", text, flags=re.IGNORECASE)
                keywords_en_output.append(escape_text(kw))
                continue
            
            special_titles = ['人工智能辅助声明', '数据可用性声明', '作者贡献声明', '利益冲突声明', 'Funding', 'Data Availability']
            matched_special = False
            for special_title in special_titles:
                if text == special_title or text == special_title + '：' or text == special_title + ':':
                    if abstract_output or keywords_output or abstract_en_output:
                        _output_accumulated_abstract(out, abstract_output, keywords_output, abstract_en_output, keywords_en_output, has_chapter)
                        abstract_output = []
                        keywords_output = []
                        abstract_en_output = []
                        keywords_en_output = []
                    out.append("\\clearpage")
                    out.append(f"\\section*{{{escape_text(special_title)}}}")
                    out.append("")
                    in_abstract = False
                    in_keywords = False
                    in_abstract_en = False
                    in_bibliography = False
                    matched_special = True
                    break

            if matched_special:
                # 特殊标题本身已输出；不要继续处理本 block（标题不应再作为正文出现）
                continue

            if text.startswith("Abstract:") or text.startswith("Abstract "):
                in_abstract = False
                in_keywords = False
                in_abstract_en = True
                text = convert_citations(text)
                text = enhance_math_recognition(text)
                text = enhance_generality(text)
                abstract_en_output.append(text)
                continue
            
            if in_abstract:
                text = convert_citations(content)
                text = enhance_math_recognition(text)
                text = convert_figure_table_refs(text)
                text = enhance_generality(text)
                abstract_output.append(text)
            elif in_abstract_en:
                text = convert_citations(content)
                text = enhance_math_recognition(text)
                text = convert_figure_table_refs(text)
                text = enhance_generality(text)
                abstract_en_output.append(text)
            elif in_bibliography:
                bib_lines.append(escape_text(content))
            else:
                lines = content.split('\n')
                for line in lines:
                    stripped = line.strip()
                    if _is_standalone_formula(stripped):
                        out.append("")
                        # V7.6: 已有 $$/$ 定界符的公式直接输出（不额外转义）
                        if stripped.startswith('$$') or stripped.endswith('$$'):
                            # Multi-line formula: enter/exit tracking
                            if stripped.startswith('$$') and not stripped.endswith('$$'):
                                in_multiline_math = True
                            elif stripped.endswith('$$') and not stripped.startswith('$$'):
                                in_multiline_math = False
                            out.append(stripped)
                        elif in_multiline_math:
                            # Middle line of multi-line formula → output as-is
                            out.append(stripped)
                        elif stripped.startswith('$') and stripped.endswith('$'):
                            out.append(stripped)
                        else:
                            # 无定界符的公式 → 包裹
                            out.append(f"$$\\displaystyle {escape_text(stripped)}$$")
                        out.append("")
                    else:
                        text = enhance_math_recognition(line)
                        text = convert_citations(text)
                        text = convert_figure_table_refs(text)
                        text = enhance_generality(text)
                        if text.strip():
                            out.append(text)
                out.append("")
                continue
        
        if btype == "image":
            idx = getattr(block, "idx", 0)
            fig_idx += 1
            # 从图像对象推断扩展名（普适性：兼容 jpeg/png）
            ext = "png"
            img_obj = data.get("image_obj") if isinstance(data, dict) else None
            img_width_px = 0
            img_height_px = 0
            if img_obj is not None:
                local_path = (
                    getattr(img_obj, "extracted_path", "")
                    or getattr(img_obj, "path", "")
                    or getattr(img_obj, "local_path", "")
                )
                if local_path:
                    _, guessed_ext = os.path.splitext(local_path)
                    if guessed_ext:
                        ext = guessed_ext.lstrip(".")
                # 获取图片尺寸
                img_width_px = getattr(img_obj, "width", 0)
                img_height_px = getattr(img_obj, "height", 0)
            path = f"images/image{idx:02d}.{ext}"
            # 获取图片caption
            caption = data.get("caption", "") if isinstance(data, dict) else ""

            # 智能布局决策：判断是否应占双列
            is_double_column_template = template in _DOUBLE_COLUMN_TEMPLATES
            use_double_column = False
            if is_double_column_template:
                use_double_column = _should_figure_span_two_columns(img_width_px, img_height_px, format_spec)

            # 根据布局决策设置 figure 环境和图片宽度
            figure_env = "figure*" if use_double_column else "figure"
            if use_double_column:
                img_width = "0.9\\textwidth"
            else:
                img_width = getattr(format_spec, "image_width", "0.9\\textwidth") if format_spec else "0.9\\textwidth"
            fig_cap_pos = getattr(format_spec, "figure_caption_position", "bottom") if format_spec else "bottom"

            out.append(f"\\begin{{{figure_env}}}[htbp]")
            out.append("  \\centering")
            if fig_cap_pos == "top":
                out.append(f"  \\caption{{{escape_text(caption) if caption else f'图{fig_idx}'}}}")
                out.append(f"  \\label{{fig:{fig_idx}}}")
            out.append(f"  \\includegraphics[width={img_width},height=0.7\\textheight,keepaspectratio]{{{path}}}")
            if fig_cap_pos == "bottom":
                out.append(f"  \\caption{{{escape_text(caption) if caption else f'图{fig_idx}'}}}")
                out.append(f"  \\label{{fig:{fig_idx}}}")
            out.append(f"\\end{{{figure_env}}}")
            out.append("")
            continue
        
        if btype == "table":
            table_idx += 1
            tbl_obj = data.get("table_obj")
            if tbl_obj:
                headers = getattr(tbl_obj, "headers", [])
                rows = getattr(tbl_obj, "rows", [])
                if headers and rows:
                    n_cols = len(headers)

                    # 智能布局决策：判断是否应占双列
                    is_double_column_template = template in _DOUBLE_COLUMN_TEMPLATES
                    use_double_column = False
                    if is_double_column_template:
                        use_double_column = _should_table_span_two_columns(n_cols, format_spec)

                    # 根据布局决策设置 table 环境
                    if use_double_column:
                        table_env = "table*"
                    else:
                        table_env = "table"

                    # 根据布局决策设置表格宽度
                    if use_double_column:
                        tbl_width = "\\textwidth"
                    else:
                        tbl_width = "\\columnwidth"

                    # 所有表格都使用 tabularx 自动调整列宽
                    # 计算合适的列格式：全部使用 X（居中对齐+自动换行）
                    col_fmt = "X" * n_cols
                    tbl_cap_pos = getattr(format_spec, "table_caption_position", "top") if format_spec else "top"
                    # 根据模板语言选择表格标题前缀
                    is_chinese_template = template in ("nsfc", "sci", "thesis", "humanities", "renai")
                    table_caption_prefix = "表" if is_chinese_template else "Table"
                    # 获取表格caption
                    tbl_caption = ""
                    if tbl_obj:
                        tbl_caption = getattr(tbl_obj, "caption", "") or ""

                    out.append(f"\\begin{{{table_env}}}[htbp]")
                    out.append("  \\centering")
                    if tbl_cap_pos == "top":
                        caption_text = escape_text(tbl_caption) if tbl_caption else f"{table_caption_prefix} {table_idx}"
                        out.append(f"  \\caption{{{caption_text}}}")
                        out.append(f"  \\label{{tab:{table_idx}}}")
                    out.append(f"  \\begin{{tabularx}}{{{tbl_width}}}{{{col_fmt}}}")
                    out.append("    \\toprule")
                    header_tex = " & ".join(escape_table_cell(h) for h in headers) + " \\\\"
                    out.append(f"    {header_tex}")
                    out.append("    \\midrule")
                    for row in rows:
                        padded = list(row) + [""] * (n_cols - len(row))
                        out.append("    " + " & ".join(escape_table_cell(str(c)) for c in padded) + " \\\\")
                    out.append("    \\bottomrule")
                    out.append("  \\end{tabularx}")
                    if tbl_cap_pos == "bottom":
                        caption_text = escape_text(tbl_caption) if tbl_caption else f"{table_caption_prefix} {table_idx}"
                        out.append(f"  \\caption{{{caption_text}}}")
                        out.append(f"  \\label{{tab:{table_idx}}}")
                    out.append(f"\\end{{{table_env}}}")
                    out.append("")
            continue
        
        if btype == "references-heading":
            if abstract_output or keywords_output or abstract_en_output:
                _output_accumulated_abstract(out, abstract_output, keywords_output, abstract_en_output, keywords_en_output, has_chapter)
                abstract_output = []
                keywords_output = []
                abstract_en_output = []
                keywords_en_output = []

            out.append(f"% [LOC:references-heading:{block_idx}]")
            # 原文中的参考文献标题直接跳过，由模板在文档末尾统一添加
            # 避免重复输出"参考文献"/"References"标题
            in_bibliography = True
            # 不设置 bib_heading_output，让末尾逻辑自动添加标题
            continue
        
        if btype == "reference-item":
            # 格式 1: [N] XXX  →  使用 N 作为编号
            m = re.match(r"^\s*\[(\d+)\]\s*(.+)$", content)
            if m:
                ref_num = int(m.group(1))
                ref_body = m.group(2).strip()
                bib_lines.append(f"\\bibitem{{ref{ref_num}}} {escape_text(ref_body)}")
                continue
            # 格式 2: 整条文献被外层方括号包裹（已被 document_reader 拆掉外层方括号）
            #         →  自动编号（递增）
            ref_body = content.strip()
            # 兼容性：极少数情况下外层方括号未拆掉
            m2 = re.match(r"^\s*\[([^\[\]]+)\]\s*$", ref_body)
            if m2:
                ref_body = m2.group(1).strip()
            ref_num = len(bib_lines) + 1
            bib_lines.append(f"\\bibitem{{ref{ref_num}}} {escape_text(ref_body)}")
            continue
    
    if abstract_output or keywords_output or abstract_en_output:
        _output_accumulated_abstract(out, abstract_output, keywords_output, abstract_en_output, keywords_en_output, has_chapter)

    if bib_lines:
        # 不主动添加任何"参考文献"/"References"标题，避免与 \thebibliography 环境
        # 自动生成的标题重复。\thebibliography 在 ctexart 中生成 \refname，
        # 在 ctexrep/book 中生成 \bibname，默认即"参考文献"（中文）或"References"（英文）。
        out.append("\\begin{thebibliography}{99}")
        for line in bib_lines:
            out.append(line)
        out.append("\\end{thebibliography}")
        out.append("")

    out.append("\\end{document}")
    return "\n".join(out)


def generate_word(doc, build_dir, format_spec=None):
    """使用 WordDocumentBuilder 生成 Word 文档（严格对齐 PDF 排版格式）"""
    # 准备 images_map 和 tables_map（从 DocxImage/DocxTable 提取）
    images_map = {}
    tables_map = {}
    for img in getattr(doc, "images", []):
        images_map[getattr(img, "idx", 0)] = img
    for tbl in getattr(doc, "tables", []):
        tables_map[getattr(tbl, "idx", 0)] = tbl

    # 对 blocks 做内容增强（与 PDF 保持一致的 generality 处理）
    enhanced_blocks = _enhance_blocks(doc.blocks)

    # 使用 WordDocumentBuilder 构建文档（传入 format_spec 实现不同模板不同格式）
    from core.word_builder import WordDocumentBuilder

    builder = WordDocumentBuilder(format_spec=format_spec)
    output_path = builder.build_from_blocks(
        blocks=enhanced_blocks,
        title=None,       # 使用 block 中的 title
        author="",        # 暂不单独生成作者区
        output_dir=build_dir,
        filename="paper",
        images_map=images_map,
        tables_map=tables_map,
    )
    return output_path


def _enhance_blocks(blocks):
    """对 blocks 内容应用 generality 增强（与 PDF 保持一致）。

    同时将以下内容升级为带标题的 heading block（用于 Word 单独分页）：
    - 人工智能辅助声明
    - 数据可用性声明
    - 作者贡献声明
    - 利益冲突声明
    - Funding
    - Data Availability
    """
    special_titles = [
        '人工智能辅助声明', 'AI辅助声明', 'AI 辅助声明',
        '数据可用性声明', '数据可用性', 'Data Availability',
        '利益冲突声明', 'Conflict of Interest',
        '作者贡献', 'Author Contributions', 'Author Contribution',
        '基金', 'Funding',
        'ORCID',
        '作者信息', 'Author Information',
        '出版信息', "Publisher's Note", "Publishers Note",
        '补充材料', 'Supplementary Material',
    ]
    enhanced = []
    for block in blocks:
        btype = getattr(block, "type", "")
        content = getattr(block, "content", "")
        title = getattr(block, "title", "")

        # Heading 标题通用性增强（保留原文序号）
        if btype == "heading" and title:
            title_stripped = title.strip()
            number_part = ""
            text_part = title_stripped
            m = re.match(r'^(\d+(?:\.\d+){0,3})\s*[\.\、]?\s*', title_stripped)
            if m:
                number_part = m.group(1)
                text_part = title_stripped[m.end():].strip()
            else:
                text_part = title_stripped
                number_part = ""
            enhanced_text = enhance_generality(text_part)
            # 清理标题中的冗余文字
            enhanced_text = re.sub(r'[（(]\s*具有工程普适性\s*[)）]\s*', '', enhanced_text)
            if number_part:
                block.title = f"{number_part} {enhanced_text}"
            else:
                block.title = enhanced_text

        # 特殊标题：把"声明/声明正文" 拆成 heading + text
        if btype == "text" and content:
            text_stripped = content.strip()
            for special in special_titles:
                # 匹配 "特殊标题" 或 "特殊标题：xxx" 形式
                if text_stripped == special or text_stripped.startswith(special):
                    # 提取标题和正文
                    if text_stripped == special:
                        block.type = "heading"
                        block.level = 1
                        block.title = special
                        block.content = ""
                    elif text_stripped[len(special):].lstrip(' ：:').startswith('声明') is False:
                        # 形如 "特殊标题：xxx"
                        body = text_stripped[len(special):].lstrip(' ：:')
                        block.type = "heading"
                        block.level = 1
                        block.title = special
                        block.content = body
                    break

        # 正文段落通用性增强 + 清理冗余文字 + 公式识别
        if btype == "text" and content and getattr(block, "type", "") == "text":
            cleaned = enhance_generality(content.strip())
            # 删除冗余修饰语
            cleaned = re.sub(r'[（(]\s*具有工程普适性\s*[)）]\s*', '', cleaned)
            cleaned = re.sub(r'[（(]\s*具有工程通用性\s*[)）]\s*', '', cleaned)
            # 公式识别：把 T_{core}, x^2 等转为 $...$ 形式，便于 Word 渲染（仅数学识别，不转义）
            cleaned = enhance_math_recognition(cleaned, do_escape=False)
            block.content = cleaned

        # 摘要段落增强
        if btype == "abstract" and content and "摘要" not in content and content.strip():
            cleaned = enhance_generality(content.strip())
            cleaned = re.sub(r'[（(]\s*具有工程普适性\s*[)）]\s*', '', cleaned)
            cleaned = re.sub(r'[（(]\s*具有工程通用性\s*[)）]\s*', '', cleaned)
            block.content = cleaned

        # 参考文献不做增强（保持原样）
        enhanced.append(block)

    return enhanced


def parse_args():
    parser = argparse.ArgumentParser(
        description="PaperForge v4 - Word/Markdown → PDF/Word 通用排版工具"
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=None,
        help="输入文档路径（支持 .docx / .md / .markdown / .json，默认自动查找）",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="输出目录（默认根据输入文件名自动生成）",
    )
    parser.add_argument(
        "--miktex",
        default="D:/miktex_install/miktex/miktex/bin/x64",
        help="MiKTeX bin 目录路径",
    )
    parser.add_argument(
        "--intake-text",
        default=None,
        help="（实验性）从自然语言文本经 LLM 转 PaperSpec JSON 后排版。"
             "需要设置 LLM_API_KEY 或 OPENAI_API_KEY 环境变量。"
    )
    parser.add_argument(
        "--intake-input",
        default=None,
        help="（实验性）从 .txt/.md 文件读取自然语言，经 LLM 转 PaperSpec JSON 后排版。"
             "需要设置 LLM_API_KEY 或 OPENAI_API_KEY 环境变量。",
    )
    parser.add_argument(
        "--intake-spec-out",
        default=None,
        help="（实验性）保存 LLM 生成的 PaperSpec JSON 到指定路径（与 --intake-text/--intake-input 配合使用）",
    )
    parser.add_argument(
        "--no-word",
        action="store_true",
        help="只生成 PDF，不生成 Word 副本",
    )
    parser.add_argument(
        "-t", "--template",
        default="auto",
        help="模板选择：auto（自动检测）、nsfc（国家自然科学基金）、ieee、cvpr2024、icml2025、neurips2024、acl2024、sci、humanities（人文社科）、thesis（学位论文）、renai（天津仁爱学院）",
    )
    parser.add_argument(
        "--diagram-runs",
        default=None,
        help="paper2diagram 输出目录路径，用于自动插入生成的流程图",
    )
    return parser.parse_args()


def _build_resolved_template(template_name: str) -> 'ResolvedTemplate':
    """为 Gate 检查构建 ResolvedTemplate 对象"""
    from core.template_engine import ResolvedTemplate, PackageSpec
    
    doc_class_info = _LATEX_DOC_CLASS_MAP.get(template_name, ("article", "12pt,a4paper"))
    doc_class, class_options_str = doc_class_info
    
    is_chinese = template_name not in ("ieee", "icml2025", "neurips2024", "cvpr2024", "acl2024") or template_name == "renai"
    
    return ResolvedTemplate(
        document_class=doc_class,
        class_options=class_options_str.split(","),
        packages=[
            PackageSpec("amsmath"),
            PackageSpec("amssymb"),
            PackageSpec("graphicx"),
            PackageSpec("booktabs"),
            PackageSpec("hyperref"),
        ],
        section_order=["introduction", "method", "experiments", "conclusion"],
        citation_style="numeric",
        bibliography_style="unsrt",
        page_limit=8,
        column_layout="double" if template_name == "ieee" else "single",
        font_size="10pt" if template_name in ("ieee", "icml2025", "neurips2024", "cvpr2024") else "12pt",
        figure_placement_default="t",
        table_placement_default="t",
        title_page_template="",
        language="english" if not is_chinese else "chinese",
        anonymous=False,
        engine="xelatex",
    )


def main():
    args = parse_args()
    INPUT_FILE = args.input
    # 自动查找默认输入文件（从配置读取）
    if not INPUT_FILE and not args.intake_text and not args.intake_input:
        try:
            import yaml
            config_path = os.path.join(os.path.dirname(__file__), "style_config.yaml")
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f)
            candidates = config.get("input_candidates", [])
        except Exception:
            candidates = ["work/论文.docx", "test/论文.docx", "论文.docx", "test/实验报告.md", "实验报告.md"]
        
        for cand in candidates:
            if os.path.exists(cand):
                INPUT_FILE = cand
                break
        if not INPUT_FILE:
            INPUT_FILE = "work/论文.docx"

    # 实验性：自然语言 → PaperSpec → 排版
    if args.intake_text or args.intake_input:
        try:
            from core.llm_factory import create_llm_from_env, LLMConfigError
            from core.nl_intake import NLIntake, IntakeParseError, IntakeValidationError
            from core.nl_to_document import (
                build_document_content, serialize_intake_output,
            )
        except ImportError as e:
            print(f"[错误] 缺少依赖: {e}", file=sys.stderr)
            return 7

        if args.intake_text:
            user_text = args.intake_text
        else:
            if not os.path.exists(args.intake_input):
                print(f"[错误] 输入文件不存在: {args.intake_input}", file=sys.stderr)
                return 2
            user_text = open(args.intake_input, encoding="utf-8").read()

        try:
            llm = create_llm_from_env()
        except LLMConfigError as e:
            print(f"[错误] {e}", file=sys.stderr)
            return 3

        print("=" * 70)
        print(f"PaperForge v4 — NL Intake 模式")
        print("=" * 70)
        print(f"  文本长度: {len(user_text)} 字符")

        intake = NLIntake(llm)
        try:
            paper_spec, ref_db, section_data_map = intake.process(
                user_text, venue=None, field=None,
            )
        except (IntakeParseError, IntakeValidationError) as e:
            print(f"[错误] LLM 输出解析/校验失败: {e}", file=sys.stderr)
            return 4
        except Exception as e:
            print(f"[错误] LLM 调用失败: {e}", file=sys.stderr)
            return 5

        print(f"  ✓ 标题: {paper_spec.get('title', '(无)')}")
        print(f"  ✓ Venue: {paper_spec.get('venue', '(无)')}")
        print(f"  ✓ 引用: {len(ref_db)} 条")

        # 可选：保存 JSON
        if args.intake_spec_out:
            payload = serialize_intake_output(paper_spec, ref_db, section_data_map)
            with open(args.intake_spec_out, "w", encoding="utf-8") as f:
                import json as _json
                f.write(_json.dumps(payload, ensure_ascii=False, indent=2))
            print(f"  ✓ PaperSpec JSON: {args.intake_spec_out}")

        # 转 DocumentContent 后进入主流程
        INPUT_FILE = "nl_intake"  # 占位，让主流程走特殊分支
        doc = build_document_content(paper_spec, ref_db, section_data_map)
    else:
        doc = None  # 主流程后续会读取

    if args.output:
        BUILD_DIR = args.output
    else:
        base = os.path.splitext(os.path.basename(INPUT_FILE))[0] if INPUT_FILE else "build"
        safe = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", base).strip("_") or "build"
        BUILD_DIR = f"build_{safe}"
    MIKTEX_PATH = args.miktex

    # 判断文件类型
    if INPUT_FILE and INPUT_FILE != "nl_intake":
        ext = os.path.splitext(INPUT_FILE)[1].lower()
        is_markdown = ext in ('.md', '.markdown')
    else:
        is_markdown = False

    # 模板选择
    if args.template == "auto" and not is_markdown:
        template = None  # 推迟到读取文档后检测
    else:
        # 当用户显式指定了非 auto 模板时（如 renai、humanities），尊重用户选择
        # 仅在未显式指定时对 .md 输入默认使用 sci
        if args.template and args.template != "auto":
            template = args.template
        else:
            template = "sci" if is_markdown else "nsfc"

    os.makedirs(BUILD_DIR, exist_ok=True)
    os.makedirs(os.path.join(BUILD_DIR, "images"), exist_ok=True)

    print("=" * 70)
    print(f"PaperForge v4 通用排版 - {INPUT_FILE}")
    print("=" * 70)
    print(f"输入文件: {INPUT_FILE} ({'Markdown' if is_markdown else ('NL Intake' if doc is not None else 'Word')})")
    print(f"输出目录: {BUILD_DIR}")

    print("\nStep 1: 读取文档")
    if doc is None:
        # 主入口是 .docx/.md/.json，需要读取
        doc = read_input_document(INPUT_FILE, BUILD_DIR)
    print(f"  Blocks: {len(doc.blocks)} 个")
    print(f"  Tables: {len(doc.tables)} 个")

    # Markdown / .tex 模式：将图片复制到 build/images 目录
    import shutil
    if doc.images:
        images_dir = os.path.join(BUILD_DIR, "images")
        os.makedirs(images_dir, exist_ok=True)
        for idx, img in enumerate(doc.images, 1):
            src = getattr(img, "extracted_path", "")
            if src and os.path.exists(src):
                ext = os.path.splitext(src)[1].lstrip('.').lower() or 'png'
                dst = os.path.join(images_dir, f"image{idx:02d}.{ext}")
                shutil.copy2(src, dst)
                img.extracted_path = f"images/image{idx:02d}.{ext}"
                img.idx = idx
                # 同步更新 block 中的 idx
                for block in doc.blocks:
                    if getattr(block, "type", "") == "image" and getattr(block, "idx", 0) == img.idx:
                        block.idx = idx
                        if isinstance(getattr(block, "data", None), dict):
                            block.data["image_obj"] = img

    # Step 1.15: 处理 paper2diagram 流程图（只插入第一张，插入到"三、结果分析"之前）
    if args.diagram_runs and os.path.exists(args.diagram_runs):
        print("\nStep 1.15: 导入 paper2diagram 流程图")
        import json as _json
        summary_path = os.path.join(args.diagram_runs, "outputs", "S5-candidate-image", "generation-summary.json")
        if os.path.exists(summary_path):
            with open(summary_path, "r", encoding="utf-8") as f:
                diagram_summary = _json.load(f)
            
            images_dir = os.path.join(BUILD_DIR, "images")
            os.makedirs(images_dir, exist_ok=True)
            
            from collections import namedtuple
            DiagramImage = namedtuple("DiagramImage", ["extracted_path", "idx", "caption", "width", "height"])
            
            next_idx = len(doc.images) + 1
            
            first_item = next((item for item in diagram_summary if item.get("generated") and item.get("image_path")), None)
            if first_item:
                src = first_item["image_path"]
                if os.path.exists(src):
                    ext = os.path.splitext(src)[1].lstrip('.').lower() or 'png'
                    dst = os.path.join(images_dir, f"image{next_idx:02d}.{ext}")
                    shutil.copy2(src, dst)
                    
                    diagram_img = DiagramImage(
                        extracted_path=f"images/image{next_idx:02d}.{ext}",
                        idx=next_idx,
                        caption=first_item.get("identity", "Diagram 1"),
                        width=0,
                        height=0
                    )
                    doc.images.append(diagram_img)
                    
                    from core.types import Block
                    diagram_block = Block(
                        type="image",
                        data={"image_obj": diagram_img, "caption": diagram_img.caption},
                        idx=next_idx
                    )
                    
                    insert_pos = len(doc.blocks)
                    for i, block in enumerate(doc.blocks):
                        block_text = getattr(block, 'content', '') or ''
                        if isinstance(block_text, str) and '三、结果分析' in block_text:
                            insert_pos = i
                            break
                    
                    doc.blocks.insert(insert_pos, diagram_block)
                    print(f"  ✓ 流程图 1: {first_item['identity']} (插入位置: 第{insert_pos}个block，'三、结果分析'之前)")
                else:
                    print(f"  ✗ 图片文件不存在: {src}")
            else:
                print("  ✗ 未找到已生成的流程图")
        else:
            print(f"  ✗ 未找到 generation-summary.json: {summary_path}")
    elif args.diagram_runs:
        print(f"\nStep 1.15: paper2diagram 目录不存在: {args.diagram_runs}")

    # Step 1.2: 入口质量检测
    print("\nStep 1.2: 入口质量检测")
    validator = InputValidator(images_dir=os.path.join(BUILD_DIR, "images"))
    input_report = validator.validate(doc)
    input_report.print_summary()
    # 保存 JSON 报告
    report_path = os.path.join(BUILD_DIR, "input_quality_report.json")
    input_report.save_json(report_path)
    print(f"  报告文件: {report_path}")
    if not input_report.can_proceed:
        print("\n  [致命错误] 输入文档质量不达标，终止排版。")
        print(f"  详情请查看: {report_path}")
        sys.exit(1)

    # Step 1.5: 模板自动检测（如用户未指定）
    if args.template == "auto":
        detector = TemplateDetector()
        detection = detector.detect(doc, hint=None)
        template = detection.template
        print(f"\nStep 1.5: 模板自动检测")
        print(f"  推断模板: {template} (置信度 {detection.confidence:.0%})")
        if detection.evidence:
            print(f"  判定依据: {', '.join(detection.evidence[:3])}")
    else:
        print(f"\nStep 1.5: 使用用户指定模板")
        print(f"  指定模板: {template}")

    # 根据模板名提前加载 FormatSpec（LaTeX 和 Word 都需要）
    format_spec = PRESET_FORMATS.get(template)
    if format_spec:
        print(f"  格式预设: {template} (标题 {format_spec.title_size}, 正文 {format_spec.body_size})")
    else:
        print(f"  [警告] 未找到模板 '{template}' 的格式预设，使用默认")

    # 生成 LaTeX 和 PDF（docx 和 markdown 都支持）
    tex_path = None
    print("\nStep 2: 渲染增强版 LaTeX（含表格宽度优化）")
    tex_content = render_enhanced_latex(doc, BUILD_DIR, format_spec=format_spec, template=template)
    tex_path = os.path.join(BUILD_DIR, "paper.tex")
    with open(tex_path, "w", encoding="utf-8") as f:
        f.write(tex_content)
    print(f"  保存: {tex_path}")

    # Step 2.5: LaTeX 清洗（修复 LLM 常见格式问题）
    from core.latex_cleaner import clean_tex_file, validate_clean
    clean_stats = clean_tex_file(Path(tex_path))
    if any(v for v in clean_stats.values() if isinstance(v, int) and v > 0):
        print(f"  [CLEAN] **→textbf: {clean_stats.get('bold_converted',0)}, "
              f"Unicode→LaTeX: {clean_stats.get('unicode_fixed',0)}, "
              f"tag→equation: {clean_stats.get('tag_fixed',0)}, "
              f"嵌套\\($: {clean_stats.get('nested_math_fixed',0)}, "
              f"下标包裹: {clean_stats.get('subscript_wrapped',0)}, "
              f"窄空格: {clean_stats.get('thin_space',0)}, "
              f"•移除: {clean_stats.get('bullet_removed',0)}")
        if clean_stats.get('heiti_fixed'):
            print(f"  [CLEAN] heiti字体已注册")
        if clean_stats.get('tocdepth_added'):
            print(f"  [CLEAN] tocdepth已设置")
        # 重新读取清洗后的内容以更新统计
        tex_content = Path(tex_path).read_text(encoding="utf-8")
    
    # Step 2.6: Gate5 格式卫生校验（V7.5 激活 —— 编译前拦截格式污染）
    gate5_issues = validate_clean(tex_content)
    if gate5_issues:
        print(f"\n  [Gate5] 格式卫生检查: 发现 {len(gate5_issues)} 个问题")
        has_errors = any(sev == 'error' for sev, _, _ in gate5_issues)
        for severity, code, msg in gate5_issues:
            tag = "ERROR" if severity == "error" else "WARN"
            print(f"    [{tag}] [{code}] {msg}")
        if has_errors:
            print(f"\n  [Gate5] 存在 ERROR 级别格式问题，中止排版。")
            print(f"  请修复以上问题后重新排版。")
            return
        else:
            print(f"  [Gate5] 仅有警告级别问题，继续编译...")
    else:
        print(f"  [Gate5] 格式卫生检查: PASS")

    cite_count = tex_content.count(r"\cite{")
    math_count = tex_content.count(r"$") // 2
    generality_count = tex_content.count("工程普适性")
    tabularx_count = tex_content.count("tabularx")
    print(f"  \\cite 引用: {cite_count} 个")
    print(f"  数学公式: {math_count} 个")
    print(f"  普适性标记: {generality_count} 处")
    print(f"  使用 tabularx 的表格: {tabularx_count} 个")

    print("\nStep 3: 编译 PDF")

    # 使用统一的 MikTeXResolver
    from core.utils.miktex import MikTeXResolver
    resolver = MikTeXResolver(custom_path=MIKTEX_PATH)
    config = resolver.resolve("xelatex")
    env = resolver.get_env(config)

    # 检查引擎是否可用
    if not config.is_found and not config.found_in_path:
        print(f"  [错误] 找不到 xelatex，请检查 MiKTeX 安装")
        print(f"  搜索路径: {MIKTEX_PATH}")
        return

    compile_errors = []

    # PDF 编译部分
    try:
        # 第一次编译：生成.aux和.toc文件
        result = subprocess.run(
            [config.engine_path, "-interaction=nonstopmode", "paper.tex"],
            cwd=BUILD_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if "Output written" in result.stdout:
            print("  第1次编译: 生成辅助文件")
        else:
            # 提取错误信息
            for line in result.stdout.split("\n"):
                if line.startswith("!"):
                    compile_errors.append(line.strip())
            if compile_errors:
                print(f"  [警告] 第1次编译有错误: {len(compile_errors)} 个")

        # 第二次编译：读取.toc文件生成目录
        result = subprocess.run(
            [config.engine_path, "-interaction=nonstopmode", "paper.tex"],
            cwd=BUILD_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if "Output written" in result.stdout:
            pages_match = re.search(r"Output written on paper\.pdf \((\d+) pages", result.stdout)
            if pages_match:
                print(f"  第2次编译: 生成目录, {pages_match.group(1)} 页")

        # 第三次编译：确保所有交叉引用正确
        result = subprocess.run(
            [config.engine_path, "-interaction=nonstopmode", "paper.tex"],
            cwd=BUILD_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=180,
        )
        if "Output written" in result.stdout:
            pages_match = re.search(r"Output written on paper\.pdf \((\d+) pages", result.stdout)
            if pages_match:
                print(f"  第3次编译: 完成, {pages_match.group(1)} 页")

    except subprocess.TimeoutExpired:
        print(f"  [错误] 编译超时 (180秒)")
        compile_errors.append("编译超时")

    except FileNotFoundError:
        print(f"  [错误] 找不到 LaTeX 引擎: {config.engine_path}")
        compile_errors.append(f"引擎未找到: {config.engine_path}")

    except Exception as e:
        print(f"  [错误] 编译异常: {e}")
        compile_errors.append(str(e))

    # Step 3.5: Gate3 全文编译检查 + 输出质量检查
    print("\nStep 3.5: Gate3 全文编译检查")
    if tex_path and os.path.exists(tex_path):
        from core.types import ReferenceDB
        
        resolved_template = _build_resolved_template(template)
        ref_db = ReferenceDB()
        gate3 = Gate3FullBuild()
        gate3_report = gate3.check(
            tex_path=tex_path,
            work_dir=BUILD_DIR,
            ref_db=ref_db,
            template=resolved_template,
        )
        print(f"  Gate3 状态: {gate3_report.status}")
        if gate3_report.diagnostics:
            for diag in gate3_report.diagnostics[:5]:
                print(f"    [{diag.severity.value.upper()}] {diag.location}: {diag.message}")
        
        if gate3_report.status == "FAIL":
            print(f"  [警告] Gate3 检查失败，可能影响 PDF 输出质量")
    
    print("\nStep 3.6: 输出质量检查")
    inspector = QualityInspector()
    quality_report = inspector.inspect(BUILD_DIR)
    print(f"  {quality_report.summary()}")
    if quality_report.errors:
        print(f"  [错误] 发现 {len(quality_report.errors)} 个编译错误")
        for issue in quality_report.errors[:3]:
            print(f"    - {issue.message}")
    if quality_report.warnings:
        print(f"  [警告] 发现 {len(quality_report.warnings)} 个警告")

    print("\nStep 4: 生成 Word 版本")
    word_path = ""
    if not args.no_word:
        word_path = generate_word(doc, BUILD_DIR, format_spec=format_spec)
        print(f"  保存: {word_path}")
    else:
        print("  跳过 (--no-word)")

    # Step 5: Gate4 终审检查
    pdf_path = os.path.join(BUILD_DIR, "paper.pdf")
    if tex_path and os.path.exists(pdf_path):
        print("\nStep 5: Gate4 终审检查")
        resolved_template = _build_resolved_template(template)
        gate4 = Gate4FinalAudit()
        gate4_report = gate4.check(
            pdf_path=pdf_path,
            tex_path=tex_path,
            template=resolved_template,
        )
        print(f"  Gate4 状态: {gate4_report.status}")
        if gate4_report.diagnostics:
            for diag in gate4_report.diagnostics[:5]:
                print(f"    [{diag.severity.value.upper()}] {diag.location}: {diag.message}")

    print("\n" + "=" * 70)
    print("最终结果汇总")
    print("=" * 70)
    print(f"  输入文件: {INPUT_FILE}")
    print(f"  输出目录: {BUILD_DIR}")
    if tex_path and os.path.exists(tex_path):
        print(f"  LaTeX: {tex_path}")

    pdf_path = os.path.join(BUILD_DIR, "paper.pdf")
    if os.path.exists(pdf_path):
        pdf_size = os.path.getsize(pdf_path)
        print(f"  PDF: {pdf_path} ({pdf_size/1024:.1f} KB)")

    if word_path:
        print(f"  Word: {word_path}")
    print("\n表格宽度优化内容:")
    print("  ✓ 使用 tabularx 包自动调整列宽")
    print("  ✓ 长文本列自动换行")
    print("  ✓ 表格宽度设为 \\textwidth")
    print("  ✓ 解决三线表横向过长问题")
    print("=" * 70)


if __name__ == "__main__":
    main()