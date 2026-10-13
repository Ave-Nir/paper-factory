# -*- coding: utf-8 -*-
"""
paperforge.core.tex_normalizer - .tex 文件预处理规范化器

将混合 Markdown/LaTeX 语法的 .tex 文件规范化为标准 LaTeX，
消除会导致编译失败的非标准模式。

处理：
    1. **粗体** → \\textbf{粗体}
    2. ### / \\#\\#\\# 小节标题 → \\subsubsection*{标题}
    3. 空 $$ 块 → 移除
    4. Markdown 管道表格 → LaTeX table 环境
    5. $$ |table| 数学模式内表格 → 移出
"""

import re
from typing import Tuple, List


def normalize_tex(content: str) -> Tuple[str, dict]:
    """规范化混合 Markdown/LaTeX 语法的 .tex 文件。"""
    stats = {
        "bold_fixed": 0,
        "headings_fixed": 0,
        "tables_fixed": 0,
        "empty_math_removed": 0,
        "table_in_math_fixed": 0,
        "math_delimiters_fixed": 0,
        "begin_end_fixed": 0,
        "textbackslash_fixed": 0,
        "frac_braces_fixed": 0,
        "textasciicircum_fixed": 0,
        "math_underscore_fixed": 0,
        "cmd_braces_fixed": 0,
    }

    # =====================================================================
    # 1. **粗体** → \textbf{粗体}
    # =====================================================================
    stats["bold_fixed"] = len(re.findall(r'\*\*(.+?)\*\*', content))
    content = re.sub(r'\*\*(.+?)\*\*', r'\\textbf{\1}', content)

    # =====================================================================
    # 2. ### / \#\#\# 小节标题 → \subsubsection*{标题}
    # =====================================================================
    def _fix_heading(m):
        stats["headings_fixed"] += 1
        return r"\subsubsection*{" + m.group(1).strip() + "}"

    # 先处理 \#\#\# 形式
    heading_count = len(re.findall(r'^\\#\\#\\#\s+', content, re.MULTILINE))
    content = re.sub(
        r'^\\#\\#\\#\s+(.+?)$',
        _fix_heading,
        content,
        flags=re.MULTILINE,
    )
    stats["headings_fixed"] = heading_count
    # 再处理直接的 ###
    extra = len(re.findall(r'^###\s+', content, re.MULTILINE))
    content = re.sub(
        r'^###\s+(.+?)$',
        _fix_heading,
        content,
        flags=re.MULTILINE,
    )
    stats["headings_fixed"] += extra

    # =====================================================================
    # 3. 空 $$ 块 → 移除（包括 \$\$ 转义形式）
    # =====================================================================
    stats["empty_math_removed"] = len(re.findall(r'\$\$\s*\n\s*\$\$', content))
    content = re.sub(r'\$\$\s*\n\s*\$\$', '', content)
    # 同时处理 \$\$...\$\$ 空块（转义形式的空数学块）
    esc_empty = len(re.findall(r'\\\$\\\$\s*\n\s*\\\$\\\$', content))
    stats["empty_math_removed"] += esc_empty
    content = re.sub(r'\\\$\\\$\s*\n\s*\\\$\\\$', '', content)

    # =====================================================================
    # 3.5. \$\$ → $$, \$ → $ 数学定界符去转义（V7.6 修复）
    # =====================================================================
    # 问题：原始 .tex 文件中公式使用 \$\$...\$\$ 和 \$...\$ 存储，
    # tex_reader 将其当作纯文本而非数学模式，导致 render 阶段
    # math_aware_escape 二次转义产生 \\$\\$...\\\$\\$$$ 等完全损坏的 LaTeX。
    # 修复：规范化时将数学定界符还原。
    stats["math_delimiters_fixed"] = 0

    def _unescape_math(m):
        stats["math_delimiters_fixed"] += 1
        inner = m.group(1)
        # 内部仍可能有已转义的字符，保持原样
        return '$$' + inner + '$$'

    # 显示公式：\$\$...\$\$ → $$...$$
    # 匹配跨行显示公式（非贪婪，DOTALL）
    content = re.sub(
        r'\\\$\\\$(.+?)\s*\\\$\\\$',
        _unescape_math,
        content,
        flags=re.DOTALL,
    )

    def _unescape_inline_math(m):
        stats["math_delimiters_fixed"] += 1
        return '$' + m.group(1) + '$'

    # 行内公式：\$...\$ → $...$
    # 匹配非贪婪，不跨行
    content = re.sub(
        r'\\\$(.+?)\s*\\\$',
        _unescape_inline_math,
        content,
    )

    # =====================================================================
    # 3.6. \begin\{...\} → \begin{...} 和 \end\{...\} → \end{...} (V7.6)
    # =====================================================================
    # 问题：原始 .tex 中 LaTeX 环境命令的花括号被转义为 \{ \}，
    # 导致 \begin\{aligned\} 无法被 LaTeX 正确解析。
    stats["begin_end_fixed"] = 0

    def _fix_begin_end(m):
        stats["begin_end_fixed"] += 1
        return '\\' + m.group(1) + '{' + m.group(2) + '}'

    content = re.sub(
        r'\\(begin|end)\\\{([^}]*)\\\}',
        _fix_begin_end,
        content,
    )

    # =====================================================================
    # 3.7. 数学模式内 \textbackslash → \ 还原真实 LaTeX 命令（V7.6）
    # =====================================================================
    # 问题：原始 .tex 用 \textbackslash 表示 \ 字符（\textbackslash phi 意为 \phi），
    # 但 tex_reader 将其当作纯文本传递，render 阶段不变，导致公式渲染为
    # 字面 "\textbackslash phi" 而非希腊字母 φ。
    # 修复：全局替换 \textbackslash\s+ → \（排除 \textbackslash{} 书目模式）。
    stats["textbackslash_fixed"] = 0

    # 先保护 \textbackslash{}（书目中使用的模式、表示字面反斜杠）
    TBS_PLACEHOLDER = "__TEXTBACKSLASH_BRACES__"
    content = content.replace(r'\textbackslash{}', TBS_PLACEHOLDER)
    stats["textbackslash_fixed"] += content.count(TBS_PLACEHOLDER)

    # 全局替换：\textbackslash\s+ → \
    # 区分场景：
    #   \textbackslash \{ → 保留 \{（去textbackslash前缀，\{已是正确的LaTeX转义花括号）
    #   \textbackslash phi → \phi（还原LaTeX命令）
    #   \textbackslash \textbackslash → \\（行分隔符）
    def _replace_tb_count(m):
        stats["textbackslash_fixed"] += 1
        return '\\'

    # 先处理 \textbackslash\{ → \{ 和 \textbackslash\} → \}（花括号特殊场景）
    content = re.sub(r'\\textbackslash\s+(\\\{)', r'\1', content)
    content = re.sub(r'\\textbackslash\s+(\\\})', r'\1', content)
    # 再处理 \textbackslash 后跟字母/数字的 LaTeX 命令
    def _replace_tb_with_char(m):
        stats["textbackslash_fixed"] += 1
        return '\\' + m.group(1)

    content = re.sub(r'\\textbackslash\s+([a-zA-Z0-9])', _replace_tb_with_char, content)
    # 处理行尾 \textbackslash（aligned \\ 行分隔）
    content = re.sub(r'\\textbackslash\s*$', r'\\', content, flags=re.MULTILINE)

    # V7.6: 兜底 - 剩余所有 \textbackslash\s+ → \（如 \\ 行分隔符的首个 \textbackslash）
    def _catchall_tb(m):
        stats["textbackslash_fixed"] += 1
        return '\\'
    content = re.sub(r'\\textbackslash\s+', _catchall_tb, content)

    # 还原保护的 \textbackslash{}
    content = content.replace(TBS_PLACEHOLDER, r'\textbackslash{}')

    # =====================================================================
    # 3.7b. \frac\{a\}\{b\} → \frac{a}{b} 全局修复（V7.6 — 在数学模式处理之前）
    # =====================================================================
    # \frac 的两个参数花括号被转义后，会变成 \frac\{a\}\{b\}
    # 无论处于数学模式还是文本模式，都应还原为正确的 LaTeX 命令语法。
    stats["frac_braces_fixed"] = len(re.findall(r'\\frac\s*\\\{', content))
    content = re.sub(
        r'\\frac\s*\\\{([^{}]*?)\\\}\s*\\\{([^{}]*?)\\\}',
        r'\\frac{\1}{\2}',
        content,
    )

    # =====================================================================
    # 3.8. \textasciicircum → ^ 仅数学模式内（V7.6 修复）
    # =====================================================================
    # \textasciicircum 在 LaTeX 数学模式内表示上标符号 ^。
    # 在文本模式保持 \textasciicircum（合法），不替换以避免 "Missing $" 错误。
    stats["textasciicircum_fixed"] = 0

    def _fix_textasciicircum_display(m):
        inner = m.group(1)
        count = inner.count(r'\textasciicircum')
        stats["textasciicircum_fixed"] += count
        inner = inner.replace(r'\textasciicircum', '^')
        return '$$' + inner + '$$'

    content = re.sub(r'\$\$(.+?)\$\$', _fix_textasciicircum_display, content, flags=re.DOTALL)

    def _fix_textasciicircum_inline(m):
        inner = m.group(1)
        count = inner.count(r'\textasciicircum')
        stats["textasciicircum_fixed"] += count
        inner = inner.replace(r'\textasciicircum', '^')
        return '$' + inner + '$'

    content = re.sub(r'\$([^$]+?)\$', _fix_textasciicircum_inline, content)

    # =====================================================================
    # 3.9. 数学模式内 \_ → _ 下标修复（V7.6）
    # =====================================================================
    # 问题：\\_ 在数学模式内表示字面下划线，不是下标。真正的下标直接用 _。
    # 例：P\\_1 → P_1（P 下标 1），{P\\_1, P\\_2} → {P_1, P_2}
    stats["math_underscore_fixed"] = 0

    def _fix_math_underscore(m):
        inner = m.group(1)
        stats["math_underscore_fixed"] += inner.count(r'\_')
        inner = inner.replace(r'\_', '_')
        # Fix subscript/superscript brace groups: _\{...\} → _{...}
        stats["math_underscore_fixed"] += len(re.findall(r'_\\{', inner))
        inner = re.sub(r'_\\{([^}]*)\\}', r'_{\1}', inner)
        inner = re.sub(r'\^\\{([^}]*)\\}', r'^{\1}', inner)
        return '$$' + inner + '$$'

    content = re.sub(r'\$\$(.+?)\$\$', _fix_math_underscore, content, flags=re.DOTALL)

    def _fix_inline_math_underscore(m):
        inner = m.group(1)
        stats["math_underscore_fixed"] += inner.count(r'\_')
        inner = inner.replace(r'\_', '_')
        # Fix subscript/superscript brace groups
        stats["math_underscore_fixed"] += len(re.findall(r'_\\{', inner))
        inner = re.sub(r'_\\{([^}]*)\\}', r'_{\1}', inner)
        inner = re.sub(r'\^\\{([^}]*)\\}', r'^{\1}', inner)
        return '$' + inner + '$'

    content = re.sub(r'\$([^$]+?)\$', _fix_inline_math_underscore, content)

    # =====================================================================
    # 3.10. LaTeX 命令参数花括号去转义（V7.6 修复）
    # =====================================================================
    # 问题：\frac\\{a\\}\\{b\\}、\tag\\{1\\}、\mathbb\\{R\\}、\text\\{word\\} 等
    # LaTeX 命令的参数花括号被错误转义为 \\{ \\}，导致命令无法正确解析。
    # 修复：在数学模式内，将已知 LaTeX 命令的 \\{ 和 \\} 还原为 { 和 }。
    # 注意：仅修复已知命令参数的花括号，保留集合符号 \\{P1\\}（无命令前缀的独立花括号）。
    stats["cmd_braces_fixed"] = 0

    # 已知可带参数的 LaTeX 命令集合
    _ARG_COMMANDS = (
        'frac', 'tag', 'mathbb', 'mathbf', 'mathcal', 'mathrm', 'mathit',
        'mathsf', 'mathtt', 'sqrt', 'binom', 'stackrel', 'substack',
        'text', 'textbf', 'textit', 'emph', 'underline', 'overline',
        'overrightarrow', 'overleftarrow', 'widehat', 'widetilde',
        'vec', 'dot', 'ddot', 'hat', 'tilde', 'bar', 'acute', 'grave',
        'check', 'breve', 'boldsymbol', 'pmb', 'textsuperscript',
        'textsubscript', 'displaystyle', 'scriptstyle', 'textstyle',
        'mathcal', 'mathscr', 'mathfrak', 'DeclareMathOperator',
        'operatorname', 'smash', 'rlap', 'llap', 'clap', 'mathclap',
    )

    _cmd_pattern = '|'.join(_ARG_COMMANDS)

    def _fix_cmd_braces_inline(m):
        inner = m.group(0)
        # Special: \frac\{a\}\{b\} → \frac{a}{b} (handle before general fix)
        inner = re.sub(
            r'\\frac\s*\\\{([^{}]*?)\\\}\s*\\\{([^{}]*?)\\\}',
            r'\\frac{\1}{\2}',
            inner,
        )
        # 替换 \cmd\{ → \cmd{
        fixed = re.sub(
            r'\\((' + _cmd_pattern + r'))\s*\\\{',
            r'\\\1{',
            inner,
        )
        # 此时 \cmd{arg\} → \cmd{arg} — 将剩余的 \} 转为 }
        # 但保留独立的 \{ 和 \}（集合符号）
        # 策略：先找到所有已知命令，记录其参数结束位置，只转这些 \}。
        # 简化：全局 \}→}，但用保护机制恢复独立的 \}
        _prot = {}

        def _protect_set_braces(m2):
            key = f"SB{len(_prot)}"
            _prot[key] = m2.group(0)
            return key

        # 保护 \{...\} 模式（集合符号：无 LaTeX 命令前缀）
        fixed = re.sub(
            r'(?<![a-zA-Z0-9])\\\{([^}]*)\\\}',
            _protect_set_braces,
            fixed,
        )
        # 现在安全地替换剩余 \} → }
        fixed = fixed.replace(r'\}', '}')
        # 还原保护的集合符号
        for k, v in _prot.items():
            fixed = fixed.replace(k, v)
        return fixed

    def _fix_cmd_braces_display(m):
        inner = m.group(0)
        # Special: \frac\{a\}\{b\} → \frac{a}{b}
        inner = re.sub(
            r'\\frac\s*\\\{([^{}]*?)\\\}\s*\\\{([^{}]*?)\\\}',
            r'\\frac{\1}{\2}',
            inner,
        )
        fixed = re.sub(
            r'\\((' + _cmd_pattern + r'))\s*\\\{',
            r'\\\1{',
            inner,
        )
        _prot = {}

        def _protect_set_braces(m2):
            key = f"SB{len(_prot)}"
            _prot[key] = m2.group(0)
            return key

        fixed = re.sub(
            r'(?<![a-zA-Z0-9])\\\{([^}]*)\\\}',
            _protect_set_braces,
            fixed,
        )
        fixed = fixed.replace(r'\}', '}')
        for k, v in _prot.items():
            fixed = fixed.replace(k, v)
        return fixed

    # 统计修复数量（修复前计数）
    _before_cmd_braces = len(re.findall(
        r'\\(?:' + _cmd_pattern + r')\s*\\\{', content
    ))
    content = re.sub(r'\$\$[^$]+\$\$', _fix_cmd_braces_display, content, flags=re.DOTALL)
    content = re.sub(r'\$[^$]+\$', _fix_cmd_braces_inline, content)
    stats["cmd_braces_fixed"] = _before_cmd_braces

    # =====================================================================
    # 4. 管道表格 → LaTeX table 环境（必须在 bold/heading 转换之后）
    # =====================================================================
    content, stats = _convert_pipe_tables(content, stats)

    return content, stats


def _extract_tables_from_math(content: str, stats: dict) -> Tuple[str, dict]:
    """将 $$\\displaystyle | col | col |$$ 中的表格行从数学模式提取出来。

    这些块会被后续的 _convert_pipe_tables 处理。
    """
    lines = content.split('\n')
    result = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # 检测 $$...|...| 模式
        if stripped.startswith('$$') and '|' in stripped:
            # 提取竖线分隔的内容，去掉 $$ 包裹
            inner = stripped.replace('$$', '').replace(r'\displaystyle', '').strip()
            if inner.startswith('|') and inner.endswith('|'):
                result.append(inner)
                stats["table_in_math_fixed"] += 1
                i += 1
                continue

        result.append(line)
        i += 1

    return '\n'.join(result), stats


def _is_separator_row(cells: List[str]) -> bool:
    """判断是否为 Markdown 表格分隔行（如 |---|---|）"""
    if not cells:
        return False
    # 非空单元格必须全部是 - : 和空格
    non_empty = [c for c in cells if c.strip()]
    if not non_empty:
        return False
    return all(re.match(r'^[\-:\s]+$', c) for c in non_empty)


def _split_pipe_row(line: str) -> List[str]:
    """按 | 拆分管道表格行，返回单元格列表"""
    stripped = line.strip()
    if stripped.startswith('|'):
        stripped = stripped[1:]
    if stripped.endswith('|'):
        stripped = stripped[:-1]
    return [c.strip() for c in stripped.split('|')]


def _convert_pipe_tables(content: str, stats: dict) -> Tuple[str, dict]:
    """将 Markdown 管道表格转换为 LaTeX table 环境。

    策略：逐行扫描，按空行分段。在每个段落内检测连续管道行。
    """
    paragraphs = content.split('\n\n')
    result_paras = []

    for para in paragraphs:
        para_lines = para.split('\n')

        # 检测这个段落中是否有管道表格
        pipe_rows = []
        pipe_indices = []
        for idx, line in enumerate(para_lines):
            stripped = line.strip()
            if stripped.startswith('|') and stripped.endswith('|'):
                cells = _split_pipe_row(stripped)
                if len(cells) >= 2:
                    pipe_rows.append(cells)
                    pipe_indices.append(idx)

        # 如果管道行少于2行（至少表头+分隔行+1数据行=3行），跳过
        if len(pipe_rows) < 3:
            result_paras.append(para)
            continue

        # 验证：分隔行应该在第二行
        has_separator = len(pipe_rows) >= 2 and _is_separator_row(pipe_rows[1])

        if not has_separator:
            result_paras.append(para)
            continue

        # --- 开始转换 ---
        stats["tables_fixed"] += 1

        headers = pipe_rows[0]
        sep_idx = 1
        data_rows = pipe_rows[2:]

        n_cols = len(headers)
        col_fmt = _infer_col_fmt(headers, data_rows, n_cols)

        # 查找标题（在表格前面的普通文本中）
        caption = f"Table {stats['tables_fixed']}"
        for look_idx in range(pipe_indices[0] - 1, -1, -1):
            look_line = para_lines[look_idx].strip()
            if not look_line:
                continue
            # 查找 \textbf{表N ...} 或 **表N ...** 形式
            cap_match = re.search(
                r'(?:\\textbf\{|^\*\*)(表\s*\d+.+?)(?:\}|\*\*)',
                look_line
            )
            if cap_match:
                caption = cap_match.group(1).strip()
                # 移除标题行
                para_lines[look_idx] = ''
                break
            # 如果只有这一行有意义的文本，用它做标题
            if look_idx == pipe_indices[0] - 1:
                stripped = look_line.strip()
                if stripped and not stripped.startswith('|'):
                    caption = stripped
                    para_lines[look_idx] = ''
                break

        # 生成 LaTeX table
        table_tex = [r'\begin{table}[htbp]']
        table_tex.append(r'  \centering')
        table_tex.append(f'  \\caption{{{_escape_cell(caption)}}}')
        table_tex.append(f'  \\begin{{tabular}}{{{col_fmt}}}')
        table_tex.append(r'    \toprule')
        # 表头
        hdr = ' & '.join(_escape_cell(h) for h in headers) + r' \\'
        table_tex.append(f'    {hdr}')
        table_tex.append(r'    \midrule')
        # 数据行
        for row in data_rows:
            padded = list(row) + [''] * (n_cols - len(row))
            rtex = ' & '.join(_escape_cell(str(c)) for c in padded[:n_cols]) + r' \\'
            table_tex.append(f'    {rtex}')
        table_tex.append(r'    \bottomrule')
        table_tex.append(r'  \end{tabular}')
        table_tex.append(r'\end{table}')

        # 替换管道行（标记为空）
        for pi in pipe_indices:
            para_lines[pi] = ''

        # 在表格起始位置插入 LaTeX table
        insert_pos = pipe_indices[0]
        para_lines[insert_pos] = '\n'.join(table_tex)

        result_paras.append('\n'.join(para_lines))

    return '\n\n'.join(result_paras), stats


def _infer_col_fmt(headers: List[str], rows: List[List[str]], n_cols: int) -> str:
    """推断最佳列对齐方式。"""
    _NUM_RE = re.compile(r'^\s*[\+\-]?\d+(?:\.\d+)?(?:\s*[%％])?\s*$')
    aligns = []
    for col_idx in range(n_cols):
        numeric = 0
        total = 0
        for row in rows:
            if col_idx < len(row):
                cell = row[col_idx].strip()
                if cell:
                    total += 1
                    if _NUM_RE.match(cell):
                        numeric += 1
        if total > 0 and numeric / total >= 0.6:
            aligns.append('r')
        else:
            aligns.append('l')
    while len(aligns) < n_cols:
        aligns.append('l')
    return ''.join(aligns[:n_cols])


def _escape_cell(text: str) -> str:
    """对表格单元格进行 LaTeX 安全转义。

    保护数学模式（$...$、$$...$$、\(...\)）和常见 LaTeX 命令
    （\\textbf{...}、\\textit{...}、\\cite{...} 等），转义其余特殊字符。
    """
    if not text:
        return ""
    # 保护数学模式和 LaTeX 命令
    protected = {}
    counter = [0]

    def _protect(m):
        key = f"NORMCELL{counter[0]}"
        protected[key] = m.group(0)
        counter[0] += 1
        return key

    # 先保护数学模式
    text = re.sub(r'\$\$.+?\$\$', _protect, text, flags=re.DOTALL)
    text = re.sub(r'\$.+?\$', _protect, text)
    text = re.sub(r'\\\(.+?\\\)', _protect, text)
    # 保护常见 LaTeX 命令（避免其内部花括号被转义）
    text = re.sub(r'\\(?:textbf|textit|emph|underline|texttt|textsf|textsc)\{[^}]*\}', _protect, text)
    text = re.sub(r'\\cite\{[^}]*\}', _protect, text)
    text = re.sub(r'\\ref\{[^}]*\}', _protect, text)
    # 保护已转义的 LaTeX 花括号 \{ \}（避免被二次转义成 \\{ \\}）
    text = re.sub(r'\\\{', _protect, text)
    text = re.sub(r'\\\}', _protect, text)
    # 保护 LaTeX 特殊字符命令（\textbackslash, \textasciitilde, \textasciicircum 等）
    text = re.sub(r'\\(?:textbackslash|textasciitilde|textasciicircum|textregistered|texttrademark)\{\}', _protect, text)

    ESC_MAP = {"&": r"\&", "%": r"\%", "#": r"\#", "_": r"\_",
               "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}",
               "^": r"\textasciicircum{}"}
    out = []
    for ch in text:
        out.append(ESC_MAP.get(ch, ch))
    text = ''.join(out)

    for key, original in protected.items():
        text = text.replace(key, original)
    return text


# ============================================================
# Gate 检查函数
# ============================================================
def check_normalization_residue(content: str) -> List[Tuple[str, str, str]]:
    """检查是否仍有残留的非标准模式。"""
    issues: List[Tuple[str, str, str]] = []

    # ** 粗体残留
    bold_stars = re.findall(r'\*\*(.+?)\*\*', content)
    if bold_stars:
        issues.append((
            "error", "BOLD_STAR_RESIDUE",
            f"存在 {len(bold_stars)} 处未转换的 ** Markdown粗体标记"
        ))

    # ### 标题残留
    hash_headings = re.findall(
        r'(?:\\#){3,6}\s+\S|^#{3,6}\s+\S', content, re.MULTILINE
    )
    if hash_headings:
        issues.append((
            "error", "HASH_HEADING_RESIDUE",
            f"存在 {len(hash_headings)} 处未转换的 ### Markdown标题"
        ))

    # 管道表格残留（需要至少2个连续管道行）
    lines = content.split('\n')
    pipe_count = 0
    consecutive = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith('|') and stripped.endswith('|'):
            cells = [c for c in stripped.split('|') if c]
            if len(cells) >= 2:
                consecutive += 1
                pipe_count += 1
        else:
            consecutive = 0
        if consecutive >= 2:
            break
    if consecutive >= 2:
        issues.append((
            "error", "PIPE_TABLE_RESIDUE",
            f"存在 {pipe_count} 行未转换的 Markdown管道表格"
        ))

    # 空 $$ 块
    empty_math = re.findall(r'\$\$\s*\$\$', content)
    if empty_math:
        issues.append((
            "warning", "EMPTY_MATH_BLOCK",
            f"存在 {len(empty_math)} 个空 $$ 公式块"
        ))

    return issues
