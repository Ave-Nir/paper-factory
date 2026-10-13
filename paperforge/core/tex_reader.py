# -*- coding: utf-8 -*-
r"""
LaTeX 文档读取器 (PaperForge 核心组件)

输入：.tex 文件路径
输出：DocumentContent 对象
    - .blocks: 按原文顺序的结构化块列表
    - .text: 向后兼容的纯文本拼接
    - .images: 从 .tex 提取的图片列表
    - .tables: 从 .tex 提取的表格列表
    - .source_file

Block 类型定义与 markdown_reader.py / document_reader.py 保持完全一致:
    title, heading(level), abstract, keywords,
    text, image, table, references-heading, reference-item,
    acknowledgements, appendix

解析策略:
    1. 逐行扫描，识别 LaTeX 结构命令（\section, \subsection, \begin{abstract} 等）
    2. 去除注释（% 开头，非 \%）
    3. 将正文内容提取为 text block
    4. 将 \includegraphics 识别为 image block
    5. 将 tabular/tabularx 环境解析为 table block
    6. 将 \begin{thebibliography} ... \end{thebibliography} 解析为参考文献
    7. 识别特殊声明（AI辅助声明、数据可用性声明等）
    8. 识别致谢和附录标题
"""

import os
import re
from typing import List, Optional

from .document_reader import Block, DocxImage, DocxTable, DocumentContent


# ============================================================
# 正则表达式
# ============================================================

# 标题命令：\section{...}, \section*{...}, \subsection{...} 等
_SECTION_RE = re.compile(r'^\\section\*?\s*\{([^}]*)\}')
_SUBSECTION_RE = re.compile(r'^\\subsection\*?\s*\{([^}]*)\}')
_SUBSUBSECTION_RE = re.compile(r'^\\subsubsection\*?\s*\{([^}]*)\}')

# \title{...}
_TITLE_RE = re.compile(r'^\\title\s*\{([^}]*)\}')
# \author{...}
_AUTHOR_RE = re.compile(r'^\\author\s*\{([^}]*)\}')
# \begin{abstract}
_ABSTRACT_BEGIN_RE = re.compile(r'^\\begin\{abstract\}')
_ABSTRACT_END_RE = re.compile(r'^\\end\{abstract\}')
# \begin{keywords} 或 \begin{keyword}
_KEYWORDS_BEGIN_RE = re.compile(r'^\\begin\{keywords?\}')
_KEYWORDS_END_RE = re.compile(r'^\\end\{keywords?\}')

# 参考文献
_BIB_BEGIN_RE = re.compile(r'^\\begin\{thebibliography\}')
_BIB_END_RE = re.compile(r'^\\end\{thebibliography\}')
_BIB_ITEM_RE = re.compile(r'^\\bibitem(?:\[[^\]]*\])?\s*\{([^}]*)\}\s*(.*)$')

# 图片：\includegraphics[options]{path}
_INCLUDEGRAPHICS_RE = re.compile(
    r'\\includegraphics\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}'
)
# figure 环境
_FIGURE_BEGIN_RE = re.compile(r'^\\begin\{figure\}')
_FIGURE_END_RE = re.compile(r'^\\end\{figure\}')
# \caption{...}
_CAPTION_RE = re.compile(r'\\caption\s*(?:\[[^\]]*\])?\s*\{([^}]*)\}')

# 表格环境：tabular / tabularx / tabu / longtable
_TABLE_BEGIN_RE = re.compile(r'^\\begin\{(tabularx?|tabu|longtable)\}')
_TABLE_END_RE = re.compile(r'^\\end\{(tabularx?|tabu|longtable)\}')
# \hline / \toprule / \midrule / \bottomrule
_HLINE_RE = re.compile(r'^(\\hline|\\toprule|\\midrule|\\bottomrule)')
# \multicolumn{n}{c}{text}
_MULTICOLUMN_RE = re.compile(r'\\multicolumn\{(\d+)\}\{([^}]*)\}\{([^}]*)\}')

# 注释行（% 开头，但不是 \%）
_COMMENT_RE = re.compile(r'^(?<!\\)%')

# 参考文献标题关键词
_REFERENCES_KEYWORDS = {"参考文献", "references", "bibliography", "参考资料"}

# 特殊声明标题关键词
_DECLARATION_RE = re.compile(
    r"^\s*("
    r"人工智能辅助声明|AI\s*辅助声明|AI辅助声明|"
    r"数据可用性声明|数据可用性|Data\s+Availability|"
    r"利益冲突声明|Conflict\s+of\s+Interest|"
    r"作者贡献|Author\s+Contributions?|"
    r"基金|Funding|"
    r"ORCID|"
    r"作者信息|Author\s+Information|"
    r"出版信息|Publisher'?s?\s+Note|"
    r"补充材料|Supplementary\s+Material"
    r")\s*[:：]?\s*$",
    re.IGNORECASE
)

# 致谢
_ACK_RE = re.compile(r"^\s*(致\s*谢|Acknowledg?ments?)\s*[:：]?\s*$", re.IGNORECASE)
# 附录
_APPENDIX_RE = re.compile(r"^\s*(附\s*录|Appendix)\s*[:：]?\s*$", re.IGNORECASE)


def _strip_inline_latex(text: str) -> str:
    """去除行内 LaTeX 命令，保留纯文本内容。

    V7.5 修复：保护数学模式（$...$、$$...$$、\\(...\\)、\\[...\\]），
    避免公式被错误剥离。render_enhanced_latex 的 math_aware_escape 会重新处理。

    V7.6 修复：保护 LaTeX 特殊字符转义（\\{、\\}、\\$、\\#、\\&、\\%、\\_、
    \\textbackslash、\\textasciitilde、\\textasciicircum），避免 \{P1\} 被
    暴力拆成 \\P1\\（产生 LaTeX pilcrow 命令），或破坏表格数据。
    """
    # Step 0: 保护数学模式 + LaTeX 特殊字符转义
    _protected = {}
    _counter = [0]

    def _protect(m):
        key = f"STRIP{_counter[0]}"
        _protected[key] = m.group(0)
        _counter[0] += 1
        return key

    # 保护 $$...$$（显示公式）
    text = re.sub(r'\$\$.+?\$\$', _protect, text, flags=re.DOTALL)
    # 保护 $...$（行内公式）
    text = re.sub(r'\$.+?\$', _protect, text)
    # 保护 \(...\) 和 \[...\]
    text = re.sub(r'\\\(.+?\\\)', _protect, text)
    text = re.sub(r'\\\[.+?\\\]', _protect, text, flags=re.DOTALL)

    # V7.6: 保护 LaTeX 特殊字符转义（避免 \{、\} 等被暴力解除）
    text = re.sub(r'\\\{', _protect, text)
    text = re.sub(r'\\\}', _protect, text)
    text = re.sub(r'\\\$', _protect, text)
    text = re.sub(r'\\#', _protect, text)
    text = re.sub(r'\\&', _protect, text)
    text = re.sub(r'\\%', _protect, text)
    text = re.sub(r'\\_', _protect, text)
    text = re.sub(r'\\textbackslash\{\}', _protect, text)
    text = re.sub(r'\\textasciitilde\{\}', _protect, text)
    text = re.sub(r'\\textasciicircum\{\}', _protect, text)

    # V7.6: 保护已转换的 LaTeX 粗体/斜体等（避免被后续 strip 破坏）
    # 同时匹配两种花括号形式：\{...\}（转义）和 {...}（已归一化）
    for _pat in (r'\\(?:textbf|textit|emph|underline|texttt|textsf|textsc)\{([^}]*)\}',
                 r'\\(?:textbf|textit|emph|underline|texttt|textsf|textsc)\\\{([^}]*)\\\}'):
        text = re.sub(_pat, _protect, text)
    # V7.6: 保护 LaTeX \tag 命令
    text = re.sub(r'\\tag\s*\{[^}]*\}', _protect, text)
    text = re.sub(r'\\tag\s*\\\{[^}]*\\\}', _protect, text)
    # V7.6: 保护 \begin{...} 和 \end{...} 环境命令
    text = re.sub(r'\\(?:begin|end)\{([^}]*)\}', _protect, text)
    text = re.sub(r'\\(?:begin|end)\\\{([^}]*)\\\}', _protect, text)
    # V7.6: 保护 \frac{...}{...}（归一化形式）
    text = re.sub(r'\\frac\{([^}]*)\}\{([^}]*)\}', _protect, text)
    text = re.sub(r'\\frac\s*\\\{([^}]*)\\\}\s*\\\{([^}]*)\\\}', _protect, text)
    # V7.6: 保护其他常见数学命令参数
    for _pat in (r'\\(?:mathbb|mathbf|mathcal|mathrm|mathit|mathsf|mathtt)\{[^}]*\}',
                 r'\\(?:mathbb|mathbf|mathcal|mathrm|mathit|mathsf|mathtt)\\\{[^}]*\\\}'):
        text = re.sub(_pat, _protect, text)
    # V7.6: 保护 \text{...} 命令
    text = re.sub(r'\\text\s*\{([^}]*)\}', _protect, text)
    text = re.sub(r'\\text\s*\\\{([^}]*)\\\}', _protect, text)
    # V7.6: 保护 \displaystyle, \scriptstyle, \textstyle 等声明命令
    text = re.sub(r'\\(?:displaystyle|scriptstyle|textstyle)\b', _protect, text)
    # V7.6: 保护数学符号/希腊字母（会被 \\[a-zA-Z]+ 剥离）
    text = re.sub(
        r'\\(?:times|div|pm|mp|cdot|circ|infty|approx|sim|simeq|equiv|neq|'
        r'leq|geq|ll|gg|subseteq|supseteq|subset|supset|in|notin|'
        r'exists|forall|cup|cap|vee|wedge|rightarrow|leftarrow|'
        r'Rightarrow|Leftarrow|to|gets|mapsto|setminus|emptyset|'
        r'nabla|partial|surd|perp|parallel|langle|rangle|'
        r'lceil|rceil|lfloor|rfloor|Delta|Phi|Omega|Sigma|'
        r'Pi|Lambda|Gamma|Theta|Xi|Upsilon|Psi|'
        r'alpha|beta|gamma|delta|epsilon|zeta|eta|theta|'
        r'iota|kappa|lambda|mu|nu|xi|pi|rho|sigma|tau|'
        r'upsilon|phi|chi|psi|omega|varepsilon|varphi|varsigma|'
        r'vartheta|varrho|ell|wp|Re|Im|aleph|hbar|'
        r'quad|qquad|setminus|emptyset|nabla|partial|'
        r'surd|perp|parallel|langle|rangle|'
        r'lceil|rceil|lfloor|rfloor|'
        r'mbox|colon|relbar|Relbar|,|thinspace|;|medspace|thickspace|!)\b',
        _protect, text)

    # Step 1: 去除 LaTeX 格式化命令（保留内容）
    # \textbf{...} → ... （但已保护的跳过）
    text = re.sub(r'\\textbf\{([^}]*)\}', r'\1', text)
    text = re.sub(r'\\textit\{([^}]*)\}', r'\1', text)
    text = re.sub(r'\\emph\{([^}]*)\}', r'\1', text)
    text = re.sub(r'\\underline\{([^}]*)\}', r'\1', text)
    # \cite{...} → [N]
    text = re.sub(r'\\cite[tp]?\{([^}]*)\}', r'[\1]', text)
    # \ref{...} → ...
    text = re.sub(r'\\ref\{([^}]*)\}', r'\1', text)
    # \label{...} → 移除
    text = re.sub(r'\\label\{[^}]*\}', '', text)

    # Step 2: 去除剩余的纯文本 \command（不触碰保护的块）
    text = re.sub(r'\\[a-zA-Z]+\b', '', text)
    # 去除残余花括号（但不影响保护的块）
    text = text.replace('{', '').replace('}', '')

    # Step 3: 还原保护的内容
    for key, original in _protected.items():
        text = text.replace(key, original)

    # 压缩空白
    text = re.sub(r' {2,}', ' ', text)
    return text.strip()


def _parse_table_row(row_text: str) -> List[str]:
    """解析单个 LaTeX 表格行，返回单元格列表"""
    cells = []
    current_cell = ""
    brace_depth = 0
    
    i = 0
    while i < len(row_text):
        ch = row_text[i]
        if ch == '{' and row_text[i-1:i] != '\\':
            brace_depth += 1
            current_cell += ch
        elif ch == '}' and row_text[i-1:i] != '\\':
            brace_depth -= 1
            current_cell += ch
        elif ch == '&' and brace_depth == 0:
            cells.append(_strip_inline_latex(current_cell.strip()))
            current_cell = ""
        else:
            current_cell += ch
        i += 1
    
    if current_cell.strip():
        cells.append(_strip_inline_latex(current_cell.strip()))
    
    # V7.6: 修剪最后一个单元格末尾的 \\ 行尾符（LaTeX 表格语法残留）
    if cells:
        last = cells[-1]
        # 匹配末尾一个或两个反斜杠（可能有空格）
        m = re.match(r'^(.+?)\s*\\\\\s*$', last)
        if not m:
            m = re.match(r'^(.+?)\s*\\\s*$', last)
        if m:
            cells[-1] = m.group(1).strip()
    
    return cells


def read_tex(tex_path: str) -> DocumentContent:
    """读取 .tex 文件，返回 DocumentContent 对象。

    与 document_reader.py 的 read_document() 保持相同输出格式，
    这样 LaTeXBuilder 等组件可以无缝复用。
    """
    with open(tex_path, 'r', encoding='utf-8') as f:
        raw_lines = f.readlines()

    lines = [line.rstrip('\n') for line in raw_lines]

    blocks: List[Block] = []
    images: List[DocxImage] = []
    tables: List[DocxTable] = []
    idx_counter = 0
    table_counter = 0

    state = "normal"        # normal / abstract / keywords / figure / bib / table
    buffer: List[str] = []
    current_caption = ""
    
    table_headers: List[str] = []
    table_rows: List[List[str]] = []

    def flush_paragraph(buf: List[str]) -> None:
        """将累积的普通段落文本生成一个 text block"""
        if not buf:
            return
        text = '\n'.join(buf).strip()
        if text:
            cleaned = _strip_inline_latex(text)
            if cleaned:
                blocks.append(Block(type="text", content=cleaned))

    def flush_table() -> None:
        """将累积的表格生成 table block"""
        nonlocal table_counter, current_caption
        if not table_headers and not table_rows:
            return
        table_counter += 1
        table_obj = DocxTable(
            idx=table_counter,
            headers=list(table_headers),
            rows=[list(r) for r in table_rows],
            caption=current_caption
        )
        tables.append(table_obj)
        blocks.append(Block(
            type="table",
            idx=table_counter,
            data={"table_obj": table_obj, "caption": current_caption}
        ))

    for line_no, line in enumerate(lines):
        stripped = line.strip()

        # 跳过注释行
        if _COMMENT_RE.match(stripped):
            continue

        # --- 状态机处理 ---

        if state == "abstract":
            if _ABSTRACT_END_RE.match(stripped):
                flush_paragraph(buffer)
                buffer = []
                state = "normal"
                continue
            buffer.append(line)
            continue

        if state == "keywords":
            if _KEYWORDS_END_RE.match(stripped):
                flush_paragraph(buffer)
                buffer = []
                state = "normal"
                continue
            buffer.append(line)
            continue

        if state == "figure":
            if _FIGURE_END_RE.match(stripped):
                fig_text = '\n'.join(buffer)
                img_match = _INCLUDEGRAPHICS_RE.search(fig_text)
                cap_match = _CAPTION_RE.search(fig_text)
                if img_match:
                    img_path = img_match.group(1).strip()
                    caption = cap_match.group(1).strip() if cap_match else current_caption
                    idx_counter += 1
                    abs_img_path = os.path.join(
                        os.path.dirname(tex_path), img_path
                    )
                    try:
                        from PIL import Image
                        with Image.open(abs_img_path) as im:
                            w, h = im.size
                    except Exception:
                        w, h = 0, 0
                    img_obj = DocxImage(
                        idx=idx_counter,
                        extracted_path=abs_img_path,
                        width=w,
                        height=h,
                        caption=caption,
                    )
                    images.append(img_obj)
                    blocks.append(Block(
                        type="image",
                        idx=idx_counter,
                        data={"image_obj": img_obj, "caption": caption}
                    ))
                buffer = []
                current_caption = ""
                state = "normal"
                continue
            buffer.append(line)
            continue

        if state == "bib":
            if _BIB_END_RE.match(stripped):
                flush_paragraph(buffer)
                buffer = []
                state = "normal"
                continue
            bib_match = _BIB_ITEM_RE.match(stripped)
            if bib_match:
                flush_paragraph(buffer)
                buffer = []
                ref_key = bib_match.group(1)
                ref_text = bib_match.group(2).strip()
                blocks.append(Block(
                    type="reference-item",
                    content=ref_text,
                    data={"ref_key": ref_key}
                ))
            else:
                if stripped:
                    if blocks and blocks[-1].type == "reference-item":
                        blocks[-1].content += " " + stripped
            continue

        if state == "table":
            if _TABLE_END_RE.match(stripped):
                flush_table()
                table_headers = []
                table_rows = []
                state = "normal"
                continue
            # 跳过 \hline 等横线命令
            if _HLINE_RE.match(stripped):
                continue
            # 跳过 \centering 命令
            if stripped == '\\centering':
                continue
            # 跳过 \label{...} 命令
            if re.match(r'^\\label\{[^}]*\}', stripped):
                continue
            # 跳过 tabular/tabularx 开始声明（如 \begin{tabularx}{\columnwidth}{XX}）
            if _TABLE_BEGIN_RE.match(stripped):
                continue
            # 跳过表格列格式声明（如 {|c|c|c|}）
            if stripped.startswith('{') and all(
                ch in '|clrp{}*' for ch in stripped if ch != ' '
            ):
                continue
            # 捕获 \caption{...} 命令
            cap_match = _CAPTION_RE.search(stripped)
            if cap_match:
                current_caption = cap_match.group(1).strip()
                continue
            # 解析表格行
            if '&' in stripped:
                cells = _parse_table_row(stripped)
                if cells:
                    if not table_headers:
                        table_headers = cells
                    else:
                        table_rows.append(cells)
            continue

        # --- 普通状态 ---

        # 跳过文档类、包声明等导言区命令
        if stripped.startswith('\\documentclass'):
            continue
        if stripped.startswith('\\usepackage'):
            continue
        if stripped.startswith('\\graphicspath'):
            continue
        if stripped.startswith('\\ctexset'):
            continue
        if stripped.startswith('\\pagestyle'):
            continue
        if stripped.startswith('\\pagenumbering'):
            continue
        if stripped.startswith('\\setlength'):
            continue
        if stripped.startswith('\\linespread'):
            continue
        if stripped.startswith('\\geometry'):
            continue
        if stripped.startswith('\\hypersetup'):
            continue
        # V7.6: 更多 preamble 命令
        if stripped.startswith('\\setCJK'):
            continue
        if stripped.startswith('\\setmainfont'):
            continue
        if stripped.startswith('\\setsansfont'):
            continue
        if stripped.startswith('\\setmonofont'):
            continue
        if stripped.startswith('\\newcommand'):
            continue
        if stripped.startswith('\\renewcommand'):
            continue
        if stripped.startswith('\\titleformat'):
            continue
        if stripped.startswith('\\captionsetup'):
            continue
        if stripped.startswith('\\fancyhf'):
            continue
        if stripped.startswith('\\fancyhead'):
            continue
        if stripped.startswith('\\fancyfoot'):
            continue
        if stripped.startswith('\\fancypagestyle'):
            continue
        if stripped.startswith('\\DeclareMathOperator'):
            continue
        # V7.6: 跳过浮动环境容器命令
        # 注意：\begin{table} 需要由 state machine 捕获以进入表格解析状态，
        # 这里只跳过 \end{table}（表格解析已在 _TABLE_END_RE 完成后回到 normal 状态）
        if stripped.startswith('\\end{table}'):
            continue
        # V7.6: 跳过表格/图片环境后残留的孤立 "table"/"figure" 文本
        if stripped in ('table', 'figure', r'\endtable', r'\endfigure',
                        r'\\endtable', r'\\endfigure'):
            continue
        if stripped.startswith('\\end{figure}') or stripped.startswith('\\begin{figure}'):
            continue
        if stripped.startswith('\\begin{document}'):
            continue

        # \title{...}
        title_match = _TITLE_RE.match(stripped)
        if title_match:
            blocks.append(Block(type="title", content=title_match.group(1).strip()))
            continue

        # \author{...}
        author_match = _AUTHOR_RE.match(stripped)
        if author_match:
            blocks.append(Block(type="text", content=author_match.group(1).strip(),
                                data={"is_author": True}))
            continue

        # \begin{abstract}
        if _ABSTRACT_BEGIN_RE.match(stripped):
            flush_paragraph(buffer)
            buffer = []
            state = "abstract"
            continue

        # \begin{keywords}
        if _KEYWORDS_BEGIN_RE.match(stripped):
            flush_paragraph(buffer)
            buffer = []
            state = "keywords"
            continue

        # \begin{figure}
        if _FIGURE_BEGIN_RE.match(stripped):
            flush_paragraph(buffer)
            buffer = []
            state = "figure"
            continue

        # \begin{table}
        if stripped.startswith('\\begin{table'):
            flush_paragraph(buffer)
            buffer = []
            state = "table"
            continue

        # \begin{thebibliography}
        if _BIB_BEGIN_RE.match(stripped):
            flush_paragraph(buffer)
            buffer = []
            state = "bib"
            blocks.append(Block(
                type="references-heading",
                level=1,
                title="References"
            ))
            continue

        # \section{...}
        section_match = _SECTION_RE.match(stripped)
        if section_match:
            flush_paragraph(buffer)
            buffer = []
            title_text = section_match.group(1).strip()
            title_clean = _strip_inline_latex(title_text)
            
            if any(kw in title_clean.lower() for kw in _REFERENCES_KEYWORDS):
                blocks.append(Block(
                    type="references-heading",
                    level=1,
                    title=title_clean
                ))
            elif _ACK_RE.match(title_clean):
                blocks.append(Block(
                    type="heading",
                    level=1,
                    title=title_clean,
                    content=title_clean,
                    data={"is_acknowledgements": True}
                ))
            elif _APPENDIX_RE.match(title_clean):
                blocks.append(Block(
                    type="heading",
                    level=1,
                    title=title_clean,
                    content=title_clean,
                    data={"is_appendix": True}
                ))
            elif _DECLARATION_RE.match(title_clean):
                blocks.append(Block(
                    type="heading",
                    level=1,
                    title=title_clean,
                    content=title_clean,
                    data={"is_declaration": True}
                ))
            else:
                blocks.append(Block(
                    type="heading",
                    level=1,
                    title=title_clean,
                    content=title_clean
                ))
            continue

        # \subsection{...}
        subsection_match = _SUBSECTION_RE.match(stripped)
        if subsection_match:
            flush_paragraph(buffer)
            buffer = []
            title_text = subsection_match.group(1).strip()
            title_clean = _strip_inline_latex(title_text)
            
            if _ACK_RE.match(title_clean):
                blocks.append(Block(
                    type="heading",
                    level=2,
                    title=title_clean,
                    content=title_clean,
                    data={"is_acknowledgements": True}
                ))
            elif _APPENDIX_RE.match(title_clean):
                blocks.append(Block(
                    type="heading",
                    level=2,
                    title=title_clean,
                    content=title_clean,
                    data={"is_appendix": True}
                ))
            else:
                blocks.append(Block(
                    type="heading",
                    level=2,
                    title=title_clean,
                    content=title_clean
                ))
            continue

        # \subsubsection{...}
        subsubsection_match = _SUBSUBSECTION_RE.match(stripped)
        if subsubsection_match:
            flush_paragraph(buffer)
            buffer = []
            title_text = subsubsection_match.group(1).strip()
            title_clean = _strip_inline_latex(title_text)
            blocks.append(Block(
                type="heading",
                level=3,
                title=title_clean,
                content=title_clean
            ))
            continue

        # \maketitle, \tableofcontents, \clearpage, \newpage 等
        if re.match(r'^\\(maketitle|tableofcontents|clearpage|newpage|noindent|centering|onehalfspacing|hfill|break|par)\b', stripped):
            continue
        # V7.6: 更多体部命令跳过
        if re.match(r'^\\(markboth|markright|addcontentsline|setcounter|thispagestyle|pagenumbering)\b', stripped):
            continue

        # \end{document}
        if stripped.startswith('\\end{document}'):
            flush_paragraph(buffer)
            buffer = []
            break

        # 空行：结束当前段落
        if not stripped:
            flush_paragraph(buffer)
            buffer = []
            continue

        # 检查正文行是否为特殊声明（非标题形式）
        if _DECLARATION_RE.match(stripped):
            flush_paragraph(buffer)
            buffer = []
            title_clean = _strip_inline_latex(stripped)
            blocks.append(Block(
                type="heading",
                level=1,
                title=title_clean,
                content=title_clean,
                data={"is_declaration": True}
            ))
            continue

        # 检查正文行是否为致谢（非标题形式）
        if _ACK_RE.match(stripped):
            flush_paragraph(buffer)
            buffer = []
            title_clean = _strip_inline_latex(stripped)
            blocks.append(Block(
                type="heading",
                level=1,
                title=title_clean,
                content=title_clean,
                data={"is_acknowledgements": True}
            ))
            continue

        # 检查正文行是否为附录（非标题形式）
        if _APPENDIX_RE.match(stripped):
            flush_paragraph(buffer)
            buffer = []
            title_clean = _strip_inline_latex(stripped)
            blocks.append(Block(
                type="heading",
                level=1,
                title=title_clean,
                content=title_clean,
                data={"is_appendix": True}
            ))
            continue

        # 普通行
        buffer.append(stripped)

    # 清理剩余状态
    flush_paragraph(buffer)
    if state == "table":
        flush_table()

    # 生成纯文本
    plain_text = '\n'.join(b.content for b in blocks if b.type == "text")

    return DocumentContent(
        blocks=blocks,
        text=plain_text,
        images=images,
        tables=tables,
        source_file=tex_path
    )
