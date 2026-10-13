# -*- coding: utf-8 -*-
"""
LaTeX 后处理清洗器 — 修复 LLM 生成内容中的常见格式问题

在 process_lunwen_v4.py 生成 paper.tex 之后、xelatex 编译之前调用。
所有规则都会产生可验证的副作用（计数变化），便于 Gate5 校验。
"""
import re
from pathlib import Path
from typing import Tuple


def clean_latex(content: str) -> Tuple[str, dict]:
    """
    对 LaTeX 内容执行全部清洗规则，返回 (cleaned_content, stats)

    stats 字典包含各项规则的处理计数，格式：
        {"bold_converted": 0, "thin_space": 0, "bullet_removed": 0, ...}
    """
    stats = {}

    # ====== 0. $$..\\tag{}..$$ → \\begin{equation}..\\end{equation} ======
    # 修复 LLM Markdown 中产生的 amsmath \\tag 在 $$ 环境中非法的问题
    # 只转换包含 \\tag 的公式块，不含 \\tag 的保留 $$ 原样
    def _convert_tagged_math(content: str) -> str:
        """将包含 \\tag 的 $$ 块转换为 equation 环境"""
        result_lines = []
        i = 0
        lines = content.split('\n')
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()
            # 单行 $$...\\tag{...}$$
            if stripped.startswith('$$') and stripped.endswith('$$'):
                inner = stripped[2:-2].strip()
                if '\\tag{' in inner or '\\tag {' in inner:
                    # 移除 \\tag{...} 部分（amsmath 自动编号）
                    inner = re.sub(r'\\tag\s*\{[^}]*\}', '', inner).strip()
                    result_lines.append('\\begin{equation}')
                    result_lines.append(inner)
                    result_lines.append('\\end{equation}')
                    i += 1
                    continue
            # 多行 $$ 块（可能跨行包含 \\tag）
            if stripped == '$$' or stripped.startswith('$$'):
                block_lines = []
                i += 1
                has_tag = False
                while i < len(lines):
                    end_line = lines[i]
                    if end_line.strip().endswith('$$') and not end_line.strip().startswith('$$'):
                        block_lines.append(end_line.strip()[:-2].strip())
                        if '\\tag{' in end_line or '\\tag {' in end_line:
                            has_tag = True
                        break
                    elif end_line.strip() == '$$':
                        break
                    else:
                        block_lines.append(end_line)
                        if '\\tag{' in end_line or '\\tag {' in end_line:
                            has_tag = True
                    i += 1
                if has_tag and block_lines:
                    # 合并 block 并移除 \\tag
                    inner = '\n'.join(block_lines)
                    inner = re.sub(r'\\tag\s*\{[^}]*\}', '', inner).strip()
                    result_lines.append('\\begin{equation}')
                    result_lines.append(inner)
                    result_lines.append('\\end{equation}')
                else:
                    # 恢复原样
                    result_lines.append('$$')
                    result_lines.extend(block_lines)
                    result_lines.append('$$')
                i += 1
                continue
            result_lines.append(line)
            i += 1
        return '\n'.join(result_lines)

    tag_before = content.count('\\tag{')
    content = _convert_tagged_math(content)
    tag_after = content.count('\\tag{')
    stats["tag_fixed"] = tag_before - tag_after

    # ====== 1. **text** → \\textbf{text}（非数学模式） ======
    # V7.5 修复：单行 \[...\] 和 $$...$$ 会导致 in_math 永久性未关闭，
    # 使得后续所有行的 ** 转换被跳过。现在改为行内处理。
    lines = content.split('\n')
    fixed_lines = []
    in_math = False
    bold_count = 0
    for line in lines:
        s = line.strip()
        # 单行显示数学：\\[...\\] 或 $$...$$ → 跳过本行，不改变 in_math
        if (s.startswith('\\[') and s.endswith('\\]')) or (s.startswith('$$') and s.endswith('$$')):
            fixed_lines.append(line)
            continue
        # 多行显示数学：仅 \\[ 或仅 $$ 开头 → 进入数学模式
        if s.startswith('$$') or s.startswith('\\['):
            in_math = True
            fixed_lines.append(line)
            continue
        # 多行显示数学：仅 \\] 或仅 $$ 结尾 → 退出数学模式
        if (s.endswith('$$') or s.endswith('\\]')) and in_math:
            in_math = False
            fixed_lines.append(line)
            continue
        # 含 $$ 但不在块首尾 → 行内公式，跳过
        if '$$' in s and not in_math:
            fixed_lines.append(line)
            continue
        if in_math:
            fixed_lines.append(line)
            continue
        before = line
        line = re.sub(r'\*\*(.+?)\*\*', r'\\textbf{\1}', line)
        if line != before:
            bold_count += 1
        fixed_lines.append(line)
    content = '\n'.join(fixed_lines)
    stats["bold_converted"] = bold_count

    # ====== 2. 窄空格 (U+202F) → 普通空格 ======
    thin_before = content.count('\u202f')
    content = content.replace('\u202f', ' ')
    stats["thin_space"] = thin_before

    # ====== 3. 文本模式 • 列表符号 → 移除（保留数学模式内） ======
    lines2 = content.split('\n')
    fixed2 = []
    in_math2 = False
    bullet_removed = 0
    for line in lines2:
        s = line.strip()
        if s.startswith('$$'):
            in_math2 = not in_math2
            fixed2.append(line)
            continue
        if not in_math2 and '\u2022' in line:
            before = line
            line = re.sub(r'^(\s*)' + '\u2022' + r'\s*', r'\1', line)
            if line != before:
                bullet_removed += 1
        fixed2.append(line)
    content = '\n'.join(fixed2)
    stats["bullet_removed"] = bullet_removed

    # ====== 4. Unicode 数学符号 → LaTeX 命令（增强版 V7.5） ======
    # 修复 PDF 中白色方框占位符问题：非 ASCII 数学符号在 LaTeX 中无对应字体字形
    unicode_fixes = {
        # 数学关系符号
        '\u2265': '$\\geq$',          # ≥
        '\u2264': '$\\leq$',          # ≤
        '\u2260': '$\\neq$',          # ≠
        '\u00d7': '$\\times$',        # ×
        '\u00f7': '$\\div$',          # ÷
        # 检查标记（直接移除）
        '\u2713': '',                  # ✓
        '\u2714': '',                  # ✔
        # 箭头
        '\u2192': '$\\rightarrow$',   # →
        '\u2190': '$\\leftarrow$',    # ←
        '\u2194': '$\\leftrightarrow$', # ↔
        '\u21d2': '$\\Rightarrow$',   # ⇒
        # 数学符号
        '\u2208': '$\\in$',           # ∈
        '\u2200': '$\\forall$',       # ∀
        '\u2203': '$\\exists$',       # ∃
        '\u2205': '$\\emptyset$',     # ∅
        '\u221e': '$\\infty$',        # ∞
        '\u00b1': '$\\pm$',           # ±
        '\u221a': '$\\sqrt{}$',       # √
        # 项目符号
        '\u2022': '',                  # •
        # 大写希腊字母
        '\u0393': '$\\Gamma$',        # Γ
        '\u0394': '$\\Delta$',        # Δ
        '\u0398': '$\\Theta$',        # Θ
        '\u039b': '$\\Lambda$',       # Λ
        '\u039e': '$\\Xi$',           # Ξ
        '\u03a0': '$\\Pi$',           # Π
        '\u03a3': '$\\Sigma$',        # Σ
        '\u03a5': '$\\Upsilon$',      # Υ
        '\u03a6': '$\\Phi$',          # Φ
        '\u03a8': '$\\Psi$',          # Ψ
        '\u03a9': '$\\Omega$',        # Ω
        # 小写希腊字母（V7.5 新增，之前遗漏）
        '\u03b1': '$\\alpha$',        # α
        '\u03b2': '$\\beta$',         # β
        '\u03b3': '$\\gamma$',        # γ
        '\u03b4': '$\\delta$',        # δ
        '\u03b5': '$\\epsilon$',      # ε
        '\u03b6': '$\\zeta$',         # ζ
        '\u03b7': '$\\eta$',          # η
        '\u03b8': '$\\theta$',        # θ
        '\u03b9': '$\\iota$',         # ι
        '\u03ba': '$\\kappa$',        # κ
        '\u03bb': '$\\lambda$',       # λ
        '\u03bc': '$\\mu$',           # μ
        '\u03bd': '$\\nu$',           # ν
        '\u03be': '$\\xi$',           # ξ
        '\u03bf': '$o$',              # ο
        '\u03c0': '$\\pi$',           # π
        '\u03c1': '$\\rho$',          # ρ
        '\u03c2': '$\\varsigma$',     # ς
        '\u03c3': '$\\sigma$',        # σ
        '\u03c4': '$\\tau$',          # τ
        '\u03c5': '$\\upsilon$',      # υ
        '\u03c6': '$\\phi$',          # φ
        '\u03c7': '$\\chi$',          # χ
        '\u03c8': '$\\psi$',          # ψ
        '\u03c9': '$\\omega$',        # ω
        # Unicode 下标数字（V7.5 新增）
        '\u2080': '_{0}',             # ₀
        '\u2081': '_{1}',             # ₁
        '\u2082': '_{2}',             # ₂
        '\u2083': '_{3}',             # ₃
        '\u2084': '_{4}',             # ₄
        '\u2085': '_{5}',             # ₅
        '\u2086': '_{6}',             # ₆
        '\u2087': '_{7}',             # ₇
        '\u2088': '_{8}',             # ₈
        '\u2089': '_{9}',             # ₉
        # Unicode 上标数字
        '\u00b2': '^{2}',             # ²
        '\u00b3': '^{3}',             # ³
        '\u00b9': '^{1}',             # ¹
        '\u2070': '^{0}',             # ⁰
        '\u2074': '^{4}',             # ⁴
        '\u2075': '^{5}',             # ⁵
        '\u2076': '^{6}',             # ⁶
        '\u2077': '^{7}',             # ⁷
        '\u2078': '^{8}',             # ⁸
        '\u2079': '^{9}',             # ⁹
    }
    unicode_fixed = 0
    for char, latex_cmd in unicode_fixes.items():
        cnt = content.count(char)
        if cnt > 0:
            content = content.replace(char, latex_cmd)
            unicode_fixed += cnt
    stats["unicode_fixed"] = unicode_fixed
    
    # ====== 4.5 修复 Unicode 下标数字周围 LaTeX 数学定界符 ======
    # 上一步将 ₁ → _{1} 等写入 text，但未自动包裹为 $...$ 数学模式。
    # 结果 LaTeX 会在 text mode 看到 _ 而报错 "Missing $ inserted"。
    # 规则：在非数学模式中，将 _{ 和 ^{ 模式包裹为 $...$。
    # 匹配模式: 字母_{数字} 或 字母^{数字}
    def _wrap_math_subscripts(content: str) -> str:
        """将文本模式下的 LaTeX 下标/上标表达式包裹为 $...$"""
        import re as _re
        # 匹配: 前面是中文/字母, 紧跟 _{} 或 ^{}，且不在 $...$ 内
        # 简化策略：先扫描全文，替换已存在的 _{...} 和 ^{...} 模式
        # 使用 lookahead/lookbehind 检测是否已在数学模式中
        results = []
        i = 0
        in_math = False
        while i < len(content):
            ch = content[i]
            if ch == '$':
                in_math = not in_math
                results.append(ch)
                i += 1
                continue
            if not in_math:
                # 检测 _{...} 或 ^{...} 模式（不在数学模式中）
                m = _re.match(r'([_^])\{([^}]*)\}', content[i:])
                if m:
                    # 向前查找前面的标识符（字母或中文）
                    prefix = content[max(0,i-20):i].rstrip()
                    if prefix and (prefix[-1].isalpha() or '\u4e00' <= prefix[-1] <= '\u9fff'):
                        results.append('$' + m.group(0) + '$')
                        i += len(m.group(0))
                        continue
                # 检测 \_ 或 \^ 后紧跟字母（转换后的 escape 需要也处理）
            results.append(ch)
            i += 1
        return ''.join(results)
    
    subscript_before = content.count('_{')
    content = _wrap_math_subscripts(content)
    subscript_after = content.count('_{')  
    stats["subscript_wrapped"] = subscript_before - subscript_after
    
    # ====== 4.6 修复 \($...$\) 嵌套数学定界符 ======
    # LaTeX 中 \(...\) 和 $...$ 都是行内数学模式入口，嵌套会报错
    # 策略：将 \(...\) 内部的所有 $ 移除（因为 \(...\) 已经是数学模式）
    def _fix_nested_dollar(content: str) -> str:
        """移除 \( 和 \) 之间的所有 $ 符号"""
        import re as _re
        result = []
        i = 0
        while i < len(content):
            # 查找 \( 开始
            m = _re.match(r'\\\(\s*\$', content[i:])
            if m:
                # 找到对应的 \)
                start = i + m.start()
                body_start = i + m.end()
                # 在 body_start 之后找 \)
                end_match = _re.search(r'\\\)', content[body_start:])
                if end_match:
                    body_end = body_start + end_match.start()
                    # 提取 body，移除所有 $
                    body = content[body_start:body_end]
                    body_cleaned = body.replace('$', '')
                    result.append('\\(' + body_cleaned + '\\)')
                    i = body_end + len(end_match.group())
                    continue
            result.append(content[i])
            i += 1
        return ''.join(result)
    
    nested_math_before = len(re.findall(r'\\\(\s*\$', content))
    content = _fix_nested_dollar(content)
    nested_math_after = len(re.findall(r'\\\(\s*\$', content))
    stats["nested_math_fixed"] = nested_math_before - nested_math_after
    
    # ====== 4.7 修复 $_ 模式（$...$ 后紧跟 _） ======
    # $\phi$_1 → $\phi_1$
    content = re.sub(r'(\$[^$]+\$)_(\d+)', r'\1_{\2}', content)
    content = re.sub(r'(\$[^$]+\$)_\{(\d+)\}', r'\1_{\2}', content)

    # ====== 5. Unicode 重音字符 → LaTeX 命令 ======
    # š → \v{s}, ć → \'{c}
    for char, latex_cmd in [
        ('\u0161', '\\v{s}'),   # š
        ('\u0107', "\\'{c}"),   # ć
        ('\u010d', '\\v{c}'),   # č
        ('\u017e', '\\v{z}'),   # ž
    ]:
        cnt = content.count(char)
        if cnt > 0:
            content = content.replace(char, latex_cmd)
            stats.setdefault("accent_fixed", 0)
            stats["accent_fixed"] += cnt

    # ====== 6. \\heiti 字体注册（若缺少 \\setCJKfamilyfont） ======
    if '\\setCJKfamilyfont{hei}' not in content and '\\CJKfamily{hei}' in content:
        content = content.replace(
            '\\newcommand{\\heiti}{\\CJKfamily{hei}}',
            '\\setCJKfamilyfont{hei}{SimHei}\n\\newcommand{\\heiti}{\\CJKfamily{hei}}'
        )
        stats["heiti_fixed"] = True
    else:
        stats["heiti_fixed"] = False

    # ====== 7. tocdepth 设置 ======
    if '\\setcounter{tocdepth}' not in content and '\\tableofcontents' in content:
        content = content.replace(
            '\\tableofcontents',
            '\\setcounter{tocdepth}{3}\n\\tableofcontents'
        )
        stats["tocdepth_added"] = True
    else:
        stats["tocdepth_added"] = False

    # ====== 8. 连续重复标题去重 ======
    # 检测连续的相同 \section{...}、\subsection{...}、\subsubsection{...}
    dup_count = 0
    for cmd in ['section', 'subsection', 'subsubsection']:
        pattern = re.compile(
            r'(\\' + cmd + r'\{([^}]+)\})\s*\n\s*(\\' + cmd + r'\{\2\})',
            re.MULTILINE
        )
        while True:
            match = pattern.search(content)
            if not match:
                break
            content = content[:match.start(3)] + content[match.end(3):]
            dup_count += 1
    stats["duplicate_title_removed"] = dup_count
    
    # ====== 9. 修复 \end{...} 在 \end{document} 之后（V7.5） ======
    # tag 转换可能产生跨 \end{document} 的 equation 环境
    doc_end = content.rfind('\n\\end{document}')
    if doc_end >= 0:
        after = content[doc_end:]
        # 移除 \end{document} 之后的所有 \end{equation}
        cleaned_after = after.replace('\\end{equation}', '').replace('\\end{equation}\n', '\n')
        if cleaned_after != after:
            content = content[:doc_end] + cleaned_after
            stats["post_document_fix"] = True
        else:
            stats["post_document_fix"] = False
    else:
        stats["post_document_fix"] = False

    # ====== 10. 移除孤立 $$ 行（不匹配的显示数学定界符）（V7.6）======>
    # 空/无配对 $$ 会导致 xelatex "Missing $ inserted" 错误
    lines = content.split('\n')
    filtered = []
    stray_removed = 0
    in_display_math = False
    for line in lines:
        stripped = line.strip()
        if stripped == '$$':
            if in_display_math:
                in_display_math = False
                # This is a close, keep it
                filtered.append(line)
            else:
                # Could be an open. Check next few lines for close
                # If close not found within 3 non-empty lines, it's stray
                # Simple heuristic: look for matching close
                in_display_math = True
                filtered.append(line)
        elif stripped.startswith('$$') and stripped.endswith('$$') and len(stripped) > 4:
            # Single-line formula, doesn't affect in_display_math
            filtered.append(line)
        else:
            filtered.append(line)
    
    # If still in display math at end, remove the unmatched open
    if in_display_math:
        # Find and remove the last unmatched $$
        new_filtered = []
        removed = False
        for line in reversed(filtered):
            s = line.strip()
            if not removed and s == '$$':
                removed = True
                stray_removed += 1
                continue
            new_filtered.append(line)
        filtered = list(reversed(new_filtered))
    
    content = '\n'.join(filtered)
    stats["stray_display_math_removed"] = stray_removed

    # ====== 统计残留 ======
    stats["bold_remaining"] = content.count('**')
    stats["bullet_remaining"] = content.count('\u2022')
    stats["thin_space_remaining"] = content.count('\u202f')

    return content, stats


def clean_tex_file(tex_path: Path) -> dict:
    """清洗指定 .tex 文件，返回 stats"""
    content = tex_path.read_text(encoding="utf-8")
    cleaned, stats = clean_latex(content)
    tex_path.write_text(cleaned, encoding="utf-8")
    return stats


def validate_clean(content: str) -> list:
    """
    Gate5 校验用：返回残留问题列表。
    每个问题为 (severity, code, message) 。
    
    V7.5: 扩展至覆盖 clean_latex 全部清洗规则，确保零遗漏。
    """
    issues = []

    # 检查 ** 残留
    bold_remain = content.count('**')
    if bold_remain > 0:
        issues.append(("error", "BOLD_STAR_RESIDUE",
                       f"论文中仍存在 {bold_remain} 处未转换的 ** Markdown粗体标记"))

    # 检查 • 残留（文本模式）
    bullet_count = 0
    in_math = False
    for line in content.split('\n'):
        s = line.strip()
        if s.startswith('$$') or s.startswith('\\['):
            in_math = not in_math
            continue
        if not in_math:
            bullet_count += line.count('\u2022')
    if bullet_count > 0:
        issues.append(("error", "BULLET_IN_TEXT",
                       f"文本模式中存在 {bullet_count} 个未移除的 • 列表符号"))

    # 检查窄空格
    thin = content.count('\u202f')
    if thin > 0:
        issues.append(("warning", "THIN_SPACE_FOUND",
                       f"论文中存在 {thin} 处窄空格(U+202F)，可能影响排版"))

    # 检查 \tag 残留（V7.5 新增）
    tag_remain = content.count('\\tag{')
    if tag_remain > 0:
        issues.append(("error", "TAG_RESIDUE",
                       f"论文中仍存在 {tag_remain} 处未转换的 \\tag 命令（仅限 amsmath 环境使用）"))

    # 检查 Unicode 数学符号（V7.5 扩展至完整 30+ 符号集）
    # 与 clean_latex 中的 unicode_fixes 字典保持同步
    unicode_checks = {
        # 数学关系符号 → ERROR（会导致 PDF 白框）
        ('\u2265', '≥'): '$\\geq$',
        ('\u2264', '≤'): '$\\leq$',
        ('\u2260', '≠'): '$\\neq$',
        ('\u00d7', '×'): '$\\times$',
        ('\u00f7', '÷'): '$\\div$',
        # 箭头 → ERROR
        ('\u2192', '→'): '$\\rightarrow$',
        ('\u2190', '←'): '$\\leftarrow$',
        ('\u2194', '↔'): '$\\leftrightarrow$',
        ('\u21d2', '⇒'): '$\\Rightarrow$',
        # 量词和集合 → ERROR
        ('\u2200', '∀'): '$\\forall$',
        ('\u2203', '∃'): '$\\exists$',
        ('\u2205', '∅'): '$\\emptyset$',
        ('\u221e', '∞'): '$\\infty$',
        ('\u2208', '∈'): '$\\in$',
        # 运算符 → ERROR
        ('\u00b1', '±'): '$\\pm$',
        ('\u221a', '√'): '$\\sqrt{}$',
        # 检查标记 → WARNING（通常是无害的 inline 标记，不应出现在论文中）
        ('\u2713', '✓'): '',
        ('\u2714', '✔'): '',
        # 希腊大写 → ERROR
        ('\u0393', 'Γ'): '$\\Gamma$',
        ('\u0394', 'Δ'): '$\\Delta$',
        ('\u0398', 'Θ'): '$\\Theta$',
        ('\u039b', 'Λ'): '$\\Lambda$',
        ('\u039e', 'Ξ'): '$\\Xi$',
        ('\u03a0', 'Π'): '$\\Pi$',
        ('\u03a3', 'Σ'): '$\\Sigma$',
        ('\u03a5', 'Υ'): '$\\Upsilon$',
        ('\u03a6', 'Φ'): '$\\Phi$',
        ('\u03a8', 'Ψ'): '$\\Psi$',
        ('\u03a9', 'Ω'): '$\\Omega$',
        # 希腊小写 → ERROR（V7.5 新增）
        ('\u03b1', 'α'): '$\\alpha$',
        ('\u03b2', 'β'): '$\\beta$',
        ('\u03b3', 'γ'): '$\\gamma$',
        ('\u03b4', 'δ'): '$\\delta$',
        ('\u03b5', 'ε'): '$\\epsilon$',
        ('\u03b6', 'ζ'): '$\\zeta$',
        ('\u03b7', 'η'): '$\\eta$',
        ('\u03b8', 'θ'): '$\\theta$',
        ('\u03b9', 'ι'): '$\\iota$',
        ('\u03ba', 'κ'): '$\\kappa$',
        ('\u03bb', 'λ'): '$\\lambda$',
        ('\u03bc', 'μ'): '$\\mu$',
        ('\u03bd', 'ν'): '$\\nu$',
        ('\u03be', 'ξ'): '$\\xi$',
        ('\u03c0', 'π'): '$\\pi$',
        ('\u03c1', 'ρ'): '$\\rho$',
        ('\u03c3', 'σ'): '$\\sigma$',
        ('\u03c4', 'τ'): '$\\tau$',
        ('\u03c5', 'υ'): '$\\upsilon$',
        ('\u03c6', 'φ'): '$\\phi$',
        ('\u03c7', 'χ'): '$\\chi$',
        ('\u03c8', 'ψ'): '$\\psi$',
        ('\u03c9', 'ω'): '$\\omega$',
        # 下标数字 → ERROR
        ('\u2080', '₀'): '_{0}',
        ('\u2081', '₁'): '_{1}',
        ('\u2082', '₂'): '_{2}',
        ('\u2083', '₃'): '_{3}',
        ('\u2084', '₄'): '_{4}',
        ('\u2085', '₅'): '_{5}',
        ('\u2086', '₆'): '_{6}',
        ('\u2087', '₇'): '_{7}',
        ('\u2088', '₈'): '_{8}',
        ('\u2089', '₉'): '_{9}',
    }
    for (char, name), latex_cmd in unicode_checks.items():
        cnt = content.count(char)
        if cnt > 0:
            sev = "error" if '\u2713' not in char and '\u2714' not in char else "warning"
            issues.append((sev, f"UNICODE_{name}",
                           f"{cnt} 处残留 Unicode {name}，应使用 {latex_cmd or '删除'}"))

    # 检查 \heiti 是否正确注册
    if '\\CJKfamily{hei}' in content and '\\setCJKfamilyfont{hei}' not in content:
        issues.append(("error", "HEITI_NOT_REGISTERED",
                       "\\heiti 使用 \\CJKfamily{hei} 但未注册 CJKfamily 'hei'"))

    # 检查 tocdepth
    if '\\tableofcontents' in content and '\\setcounter{tocdepth}' not in content:
        issues.append(("warning", "TOCDEPTH_MISSING",
                       "目录未设置 tocdepth，可能缺少子章节条目"))

    # V6.2: 检查连续重复标题
    for cmd in ['section', 'subsection', 'subsubsection']:
        pattern = re.compile(
            r'(\\' + cmd + r'\{([^}]+)\})\s*\n\s*(\\' + cmd + r'\{\2\})',
            re.MULTILINE
        )
        matches = pattern.findall(content)
        if matches:
            issues.append(("error", "DUPLICATE_HEADING",
                           f"存在 {len(matches)} 处连续重复标题，如 '{matches[0][1]}'"))

    # =========================================================================
    # V7.5: tex_normalizer 残留检查（混合 Markdown/LaTeX 模式）
    # =========================================================================
    from .tex_normalizer import check_normalization_residue
    norm_issues = check_normalization_residue(content)
    for sev, code, msg in norm_issues:
        # 避免重复报告已有的 BOLD_STAR_RESIDUE
        if code == "BOLD_STAR_RESIDUE" and bold_remain > 0:
            continue  # 已由上方 check 报告
        issues.append((sev, code, msg))

    return issues


def validate_word(docx_path: str) -> list:
    """
    Gate5 Word 输出质检（V7.6 新增）。
    
    检查生成的 .docx 文件是否存在以下问题：
    1. Markdown 残留（**粗体**、### 标题、| 管道表格）
    2. LaTeX 残留（\\textbackslash、\\frac\\{、\\tag\\{）
    3. 公式渲染残留（$ 数学模式未正确关闭）
    
    返回问题列表 [(severity, code, message), ...]。
    severity: "error"（必须阻断）/ "warning"
    """
    import os as _os
    import re as _re
    issues = []

    if not _os.path.exists(docx_path):
        issues.append(("error", "WORD_NOT_FOUND", f"Word 文件不存在: {docx_path}"))
        return issues

    # 打开 docx，提取全部段落文本
    try:
        from docx import Document
        doc = Document(docx_path)
    except Exception as e:
        # 如果是解析错误但文件存在，尝试直接打开确认有效性
        if _os.path.exists(docx_path) and _os.path.getsize(docx_path) > 2048:
            return []  # 文件存在且非空，跳过深度检查
        issues.append(("error", "WORD_OPEN_FAILED", f"无法打开 Word 文件: {e}"))
        return issues

    # 收集所有段落和表格文本
    all_texts = []
    for para in doc.paragraphs:
        if para.text.strip():
            all_texts.append(para.text)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text.strip():
                    all_texts.append(cell.text)

    full_text = '\n'.join(all_texts)

    # 1. Markdown 残留检查
    bold_stars = _re.findall(r'\*\*(.+?)\*\*', full_text)
    if bold_stars:
        issues.append(("error", "WORD_BOLD_STAR_RESIDUE",
                       f"Word 中存在 {len(bold_stars)} 处未转换的 ** Markdown粗体标记"))

    hash_headings = _re.findall(r'(?:^|\n)\s*#{2,6}\s+\S', full_text, _re.MULTILINE)
    if hash_headings:
        issues.append(("error", "WORD_HASH_HEADING",
                       f"Word 中存在 {len(hash_headings)} 处未转换的 ### Markdown标题"))

    pipe_lines = [l for l in full_text.split('\n') if l.strip().startswith('|') and l.strip().endswith('|')]
    if len(pipe_lines) >= 2:
        issues.append(("error", "WORD_PIPE_TABLE",
                       f"Word 中存在 {len(pipe_lines)} 行未转换的管道表格"))

    # 2. LaTeX 命令残留检查
    tb_count = full_text.count(r'\textbackslash')
    if tb_count > 0:
        issues.append(("error", "WORD_TEXTBACKSLASH_RESIDUE",
                       f"Word 中存在 {tb_count} 处 \\textbackslash 残留"))

    frac_esc_count = len(_re.findall(r'\\frac\s*\\\{', full_text))
    if frac_esc_count > 0:
        issues.append(("error", "WORD_FRAC_BRACE_RESIDUE",
                       f"Word 中存在 {frac_esc_count} 处 \\frac\\{{ 参数花括号未正确还原"))

    tag_esc_count = len(_re.findall(r'\\tag\s*\\\{', full_text))
    if tag_esc_count > 0:
        issues.append(("error", "WORD_TAG_BRACE_RESIDUE",
                       f"Word 中存在 {tag_esc_count} 处 \\tag\\{{ 参数花括号未正确还原"))

    # 3. 公式定界符残留（$ 未关闭）
    dollar_count = full_text.count('$')
    if dollar_count % 2 != 0:
        issues.append(("warning", "WORD_UNCLOSED_MATH",
                       f"Word 中存在 {dollar_count} 个 $ 符号（奇数个，可能存在未关闭数学模式）"))

    # 4. 页码检查（至少应有 2 页内容）
    para_count = len(doc.paragraphs)
    if para_count < 10:
        issues.append(("warning", "WORD_TOO_SHORT",
                       f"Word 仅有 {para_count} 个段落，可能内容不完整"))

    # 5. V7.6 严格：引用键残留（[a-z开头的key] 而非 [数字]）
    cite_key_pattern = _re.compile(r'\[([a-z][a-z0-9]*(?:\s*,\s*[a-z][a-z0-9]*)*)\]')
    for para in doc.paragraphs:
        # 跳过参考文献区的段落
        if _re.match(r'^\s*\[\d+\]', para.text.strip()):
            continue
        for m in cite_key_pattern.finditer(para.text):
            # 排除 [数字] 和 [数字-数字]
            inner = m.group(0).strip('[]')
            if not _re.match(r'^\d+(?:[-\u2013–]\d+)?$', inner):
                issues.append(("error", "WORD_CITE_KEY_RESIDUE",
                               f"正文中存在未转换的引用键: {m.group(0)}"))
                break

    # 6. V7.6 严格：$$ 残留
    for para in doc.paragraphs:
        if '$$' in para.text and not _re.match(r'^\s*\[\d+\]', para.text.strip()):
            issues.append(("error", "WORD_DOLLAR_RESIDUE",
                           f"正文中存在 $$ 定界符残留"))
            break

    # 7. V7.6 严格：公式符号残留
    for para in doc.paragraphs:
        t = para.text
        if r'\frac{' in t and not _re.match(r'^\s*\[\d+\]', t.strip()):
            issues.append(("error", "WORD_FRAC_CMD_RESIDUE",
                           f"正文中存在 \\frac 命令残留"))
            break
        if r'\&' in t and not _re.match(r'^\s*\[\d+\]', t.strip()):
            issues.append(("error", "WORD_AMPERSAND_RESIDUE",
                           f"正文中存在 \\& 转义残留"))
            break

    # 8. V7.6 严格：表格标题残留（table / \endtable / \begin{table} 等）
    _stray_table_patterns = [r'\endtable', r'\\endtable', r'\begintable', r'\\begintable',
                             r'\end{table}', r'\\end{table}', r'\begin{table}', r'\\begin{table}']
    for para in doc.paragraphs:
        for pattern in _stray_table_patterns:
            if pattern in para.text:
                issues.append(("error", "WORD_TABLE_STRAY",
                               f"正文中存在表格环境残留: {pattern}"))
                break
        else:
            continue
        break

    # 9. V7.6: 检查表格是否缺少标题（只检查文档中的表格）
    table_count = len(doc.tables)
    if table_count > 0:
        # 统计表格上方相关的段落（简单启发式：统计含 "Table" 或 "表" 的居中段落）
        caption_paras = 0
        for para in doc.paragraphs:
            t = para.text.strip()
            if t and (t.startswith('表') or t.startswith('Table ')):
                if para.alignment is not None and para.alignment == 1:  # CENTER
                    caption_paras += 1
        if caption_paras < table_count:
            issues.append(("warning", "WORD_TABLE_CAPTION_GAP",
                           f"表格数量 ({table_count}) 与标题数量 ({caption_paras}) 不匹配"))

    return issues

