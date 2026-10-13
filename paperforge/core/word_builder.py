# -*- coding: utf-8 -*-
r"""
Word 文档格式渲染器 v2 - 完整修复版

核心改进（5大问题修复）：
1. 中英混排字体统一：中文宋体，英文/数字 Times New Roman
2. 大小标题序号保留：1. / 1.1 / 1.1.1 按原文保留
3. 自动生成目录：收集所有 Heading 后在文首生成目录区
4. 引用角标上标处理：文本中 [1] / [1-3] / [1,2] 自动转换为上标
5. LaTeX 公式人类可读化：$x^2$, $\frac{a}{b}$, $\sqrt{x}$ 等渲染为可读文本

架构：
  WordFormatRenderer - 段落级格式渲染
  LaTeXHumanizer    - LaTeX 公式转人类可读文本
  WordDocumentBuilder - 从 blocks 构建完整 Word 文档
"""

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Any, Dict

from docx import Document
from docx.shared import Pt, Cm, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.oxml.ns import nsmap

from .formatting import FormatSpec
from .document_reader import Block, RichTextSegment


# ============================================================
# 工具函数
# ============================================================

# Unicode 上标字符映射（用于引用角标）
SUPERSCRIPT_MAP = {
    '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
    '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
    '+': '⁺', '-': '⁻', '−': '⁻', '=': '⁼', '(': '⁽', ')': '⁾',
    ' ': ' ', ',': ',', '、': '、', '–': '–',
}

# Unicode 下标字符映射（用于化学公式、数学下标）
SUBSCRIPT_MAP = {
    '0': '₀', '1': '₁', '2': '₂', '3': '₃', '4': '₄',
    '5': '₅', '6': '₆', '7': '₇', '8': '₈', '9': '₉',
    '+': '₊', '-': '₋', '−': '₋', '(': '₍', ')': '₎',
    ' ': ' ', ',': ',',
}

# LaTeX 希腊字母 -> Unicode 映射
GREEK_MAP = {
    r'\alpha': 'α', r'\beta': 'β', r'\gamma': 'γ', r'\delta': 'δ',
    r'\epsilon': 'ε', r'\zeta': 'ζ', r'\eta': 'η', r'\theta': 'θ',
    r'\iota': 'ι', r'\kappa': 'κ', r'\lambda': 'λ', r'\mu': 'μ',
    r'\nu': 'ν', r'\xi': 'ξ', r'\pi': 'π', r'\rho': 'ρ',
    r'\sigma': 'σ', r'\tau': 'τ', r'\upsilon': 'υ', r'\phi': 'φ',
    r'\chi': 'χ', r'\psi': 'ψ', r'\omega': 'ω',
    r'\Alpha': 'Α', r'\Beta': 'Β', r'\Gamma': 'Γ', r'\Delta': 'Δ',
    r'\Epsilon': 'Ε', r'\Zeta': 'Ζ', r'\Eta': 'Η', r'\Theta': 'Θ',
    r'\Iota': 'Ι', r'\Kappa': 'Κ', r'\Lambda': 'Λ', r'\Mu': 'Μ',
    r'\Nu': 'Ν', r'\Xi': 'Ξ', r'\Pi': 'Π', r'\Rho': 'Ρ',
    r'\Sigma': 'Σ', r'\Tau': 'Τ', r'\Upsilon': 'Υ', r'\Phi': 'Φ',
    r'\Chi': 'Χ', r'\Psi': 'Ψ', r'\Omega': 'Ω',
    r'\varepsilon': 'ε', r'\vartheta': 'ϑ', r'\varrho': 'ϱ',
    r'\varsigma': 'ς', r'\varphi': 'φ',
}

# 常用数学符号
MATH_SYMBOLS = {
    r'\times': '×', r'\div': '÷', r'\pm': '±', r'\mp': '∓',
    r'\cdot': '·', r'\circ': '°', r'\infty': '∞', r'\approx': '≈',
    r'\sim': '∼', r'\simeq': '≃', r'\equiv': '≡', r'\neq': '≠',
    r'\leq': '≤', r'\geq': '≥', r'\ll': '≪', r'\gg': '≫',
    r'\subseteq': '⊆', r'\supseteq': '⊇', r'\subset': '⊂', r'\supset': '⊃',
    r'\in': '∈', r'\notin': '∉', r'\exists': '∃', r'\forall': '∀',
    r'\sum': '∑', r'\prod': '∏', r'\int': '∫', r'\oint': '∮',
    r'\cup': '∪', r'\cap': '∩', r'\vee': '∨', r'\wedge': '∧',
    r'\rightarrow': '→', r'\leftarrow': '←', r'\Rightarrow': '⇒',
    r'\Leftarrow': '⇐', r'\leftrightarrow': '↔', r'\Leftrightarrow': '⇔',
    r'\to': '→', r'\gets': '←', r'\mapsto': '↦',
    r'\langle': '⟨', r'\rangle': '⟩', r'\lceil': '⌈', r'\rceil': '⌉',
    r'\lfloor': '⌊', r'\rfloor': '⌋',
    r'\surd': '√', r'\perp': '⊥', r'\parallel': '∥',
    r'\emptyset': '∅', r'\nabla': '∇', r'\partial': '∂',
    r'\setminus': '∖', r'\backslash': '\\',
}

# Sorted by length descending: prevent substring collisions (e.g. \subset before \subseteq)
_MATH_SYMBOLS_SORTED = sorted(MATH_SYMBOLS.items(), key=lambda x: -len(x[0]))

# 中英文字体常量
CN_SONG = "宋体"
CN_HEI = "黑体"
CN_KAI = "楷体"
EN_TNR = "Times New Roman"
MATH_FONT = "Cambria Math"  # V6.7: 数学公式专用字体，包含完整数学符号表


def is_cjk_char(ch: str) -> bool:
    """判断是否为 CJK 字符（中文/日文/韩文等）"""
    if not ch or len(ch) == 0:
        return False
    cp = ord(ch)
    # CJK 统一表意文字
    if 0x4E00 <= cp <= 0x9FFF:
        return True
    # CJK 扩展 A 区
    if 0x3400 <= cp <= 0x4DBF:
        return True
    # CJK 扩展 B-F 区
    if 0x20000 <= cp <= 0x2FFFF:
        return True
    # CJK 标点符号
    if 0x3000 <= cp <= 0x303F:
        return True
    # 全角符号（中文常用）
    if 0xFF00 <= cp <= 0xFFEF:
        return True
    # 中文符号区（特殊标点）
    if 0x20000 <= cp <= 0x2B81F:
        return True
    return False


def split_mixed_text(text: str) -> List[Tuple[str, str]]:
    """将文本分割为 CJK 片段和 ASCII 片段。

    返回 [(segment_text, font_type), ...]
    font_type: 'cn' 或 'en'

    连续同类型字符合并为一个片段，便于为每个 run 设置正确字体。
    """
    if not text:
        return []

    segments = []
    current_chars = [text[0]]
    current_type = 'cn' if is_cjk_char(text[0]) else 'en'

    for ch in text[1:]:
        ch_type = 'cn' if is_cjk_char(ch) else 'en'
        if ch_type == current_type:
            current_chars.append(ch)
        else:
            segments.append((''.join(current_chars), current_type))
            current_chars = [ch]
            current_type = ch_type

    segments.append((''.join(current_chars), current_type))
    return segments


# ============================================================
# LaTeXHumanizer: LaTeX 公式人类可读化
# ============================================================

class LaTeXHumanizer:
    r"""将 LaTeX 公式转人类可读的文本。"""

    # 格式化标志位
    FLAG_NORMAL = 0
    FLAG_SUPERSCRIPT = 1
    FLAG_SUBSCRIPT = 2
    FLAG_BOLD = 4
    FLAG_ITALIC = 8

    @dataclass
    class RenderChunk:
        """渲染片段"""
        text: str
        flags: int = 0  # 位或运算的 FLAG_*

    @classmethod
    def humanize(cls, latex_text: str) -> str:
        """将整段文本中所有 $...$ LaTeX 公式转为人可读形式。"""
        if not latex_text:
            return ""

        # 匹配 $...$ 和 $$...$$ 模式，同时处理无 $ 的简单 LaTeX 片段
        result = latex_text
        # 先替换 $$...$$（显示公式）
        result = re.sub(
            r'\$\$(.+?)\$\$',
            lambda m: ' ' + cls._render_single(m.group(1)) + ' ',
            result,
            flags=re.DOTALL,
        )
        # 再替换 $...$（行内公式）
        result = re.sub(
            r'\$(.+?)\$',
            lambda m: cls._render_single(m.group(1)),
            result,
        )
        # V7.6: 处理非公式区域内的 LaTeX 特殊字符转义
        result = cls._unescape_text(result)
        return result

    @classmethod
    def humanize_plain_text(cls, text: str) -> str:
        """处理纯文本中的 LaTeX 特殊字符转义（无数学公式）。

        用于表格单元格、参考文献等不包含 $...$ 公式的文本。
        """
        if not text:
            return ""

        # V7.7: 先处理 Markdown **bold** 语法，将其转换为纯文本（移除标记）
        # 注意：这里不转换为 \textbf{}，因为后面会移除 LaTeX 命令
        text = re.sub(r'\*\*([^*]+?)\*\*', r'\1', text)

        # V7.6: 先处理 $...$ 内联数学模式（表格表头等）
        text = re.sub(
            r'\$(.+?)\$',
            lambda m: cls._render_single(m.group(1)),
            text,
        )
        # 希腊字母
        for latex, unicode_char in GREEK_MAP.items():
            text = text.replace(latex, unicode_char)
        # 数学符号
        for latex, unicode_char in _MATH_SYMBOLS_SORTED:
            text = text.replace(latex, unicode_char)
        # LaTeX 特殊字符去转义
        text = cls._unescape_text(text)
        # 移除残留的 LaTeX 命令（包括 \textbackslash 各种变体）
        text = re.sub(r'\\textbackslash[\{\}\\]*', '\\\\', text)
        text = re.sub(r'\\[a-zA-Z]+(?:\{[^}]*\})?', '', text)
        return text

    @staticmethod
    def _unescape_text(text: str) -> str:
        """去除 LaTeX 特殊字符转义（文本模式）。"""
        # \textbackslash{} → \（标准形式）
        text = text.replace(r'\textbackslash{}', '\\')
        # \textbackslash\{\} → \（二次转义形式，如书目中）
        text = text.replace(r'\textbackslash\{}', '\\')
        # 兜底：\textbackslash 后跟任意内容 → \
        text = re.sub(r'\\textbackslash\s*\\\{[^}]*\\\}', '\\\\', text)
        # \{ → {, \} → }
        text = text.replace(r'\{', '{').replace(r'\}', '}')
        # \$ → $, \# → #, \& → &, \% → %, \_ → _
        text = text.replace(r'\$', '$').replace(r'\#', '#').replace(r'\&', '&')
        text = text.replace(r'\%', '%').replace(r'\_', '_')
        # \textasciitilde{} → ~, \textasciicircum{} → ^
        text = text.replace(r'\textasciitilde{}', '~').replace(r'\textasciicircum{}', '^')
        # \~{} → ~, \^{} → ^
        text = text.replace(r'\~{}', '~').replace(r'\^{}', '^')
        # 清理双反斜杠（\\ → \）——当 \ 不是转义前缀时
        text = text.replace(r'\\', '\\')
        return text

    @classmethod
    def humanize_to_runs(cls, latex_text: str) -> List[RenderChunk]:
        """将整段文本转成带格式标志的片段列表（供 Word 渲染使用）。

        这是更精细的渲染方式，保留 subscript/superscript 格式信息。
        """
        if not latex_text:
            return []

        chunks = []
        # 按 $...$ 分段，$ 外的是普通文本，$ 内的是公式
        pattern = re.compile(r'(\$\$.+?\$\$|\$.+?\$)', re.DOTALL)
        parts = pattern.split(latex_text)

        for i, part in enumerate(parts):
            if i % 2 == 1:  # 奇数索引是公式
                inner = part.strip('$')
                formatted = cls._render_to_chunks(inner)
                chunks.extend(formatted)
            else:  # 偶数索引是普通文本
                if part:
                    chunks.append(cls.RenderChunk(text=part, flags=cls.FLAG_NORMAL))

        return chunks

    @classmethod
    def _render_single(cls, formula: str) -> str:
        """渲染单个 LaTeX 公式为纯文本（使用 Unicode 符号）。"""
        result = formula.strip()
        # 希腊字母
        for latex, unicode_char in GREEK_MAP.items():
            result = result.replace(latex, unicode_char)
        # 数学符号（按长度降序避免子串冲突）
        for latex, unicode_char in _MATH_SYMBOLS_SORTED:
            result = result.replace(latex, unicode_char)
        # \mathbb{R} → ℝ 等黑板粗体
        result = cls._apply_mathbb(result)
        # \quad → 空格
        result = result.replace(r'\quad', '  ')
        result = result.replace(r'\qquad', '    ')
        # \tag{...} → 移除
        result = re.sub(r'\\tag\{[^}]*\}', '', result)
        # \{ → {, \} → }
        result = result.replace(r'\{', '{').replace(r'\}', '}')
        # \big, \Big, \bigl, \bigr, \left, \right → 移除（仅大小提示，括号本身保留）
        result = re.sub(r'\\(?:big[lr]?|Big[lr]?|left|right)\s*', '', result)
        # 上标 x^{...} / x^n
        result = cls._apply_superscript(result)
        # 下标 x_{...} / x_n
        result = cls._apply_subscript(result)
        # \frac{a}{b} → a/b
        result = cls._apply_frac(result)
        # \sqrt{x} → √x
        result = cls._apply_sqrt(result)
        # \mathbf{x}, \textit{x} 保留斜体（变量默认为斜体）
        result = re.sub(r'\\mathbf\{([^}]*)\}', r'\1', result)
        result = re.sub(r'\\textbf\{([^}]*)\}', r'\1', result)
        result = re.sub(r'\\textit\{([^}]*)\}', r'\1', result)
        result = re.sub(r'\\mathrm\{([^}]*)\}', r'\1', result)
        result = re.sub(r'\\text\{([^}]*)\}', r'\1', result)
        # 去掉多余的 {} 和反斜杠
        result = result.replace('{', '').replace('}', '')
        # 去除反斜杠命令（如果还有）
        result = re.sub(r'\\[a-zA-Z]+', '', result)
        return result

    @classmethod
    def _apply_mathbb(cls, text: str) -> str:
        r"""将 \mathbb{R}, \mathbb{N} 等黑板粗体转为 Unicode 双线体。"""
        _BB_MAP = {
            'R': 'ℝ', 'N': 'ℕ', 'Z': 'ℤ', 'Q': 'ℚ', 'C': 'ℂ',
            'P': 'ℙ', 'H': 'ℍ',
        }
        def repl(m):
            inner = m.group(1)
            return _BB_MAP.get(inner, inner)
        result = re.sub(r'\\mathbb\{([^}]+)\}', repl, text)
        return result

    @classmethod
    def _apply_superscript(cls, text: str) -> str:
        """将 x^2 / x^{123} 转为 Unicode 上标。"""
        # 处理 x^{complex}
        def repl_multi(match):
            base = match.group(1)
            exp = match.group(2)
            return base + cls._to_superscript(exp)

        result = re.sub(r'([a-zA-Z0-9)])(?<!\\)\^\{([^}]+)\}', repl_multi, text)
        # 处理 x^n (单字符)
        def repl_single(match):
            base = match.group(1)
            exp = match.group(2)
            return base + cls._to_superscript(exp)

        result = re.sub(r'([a-zA-Z0-9)])(?<!\\)\^([a-zA-Z0-9])', repl_single, result)
        return result

    @classmethod
    def _apply_subscript(cls, text: str) -> str:
        """将 x_1 / x_{ij} 转为 Unicode 下标。"""
        def repl_multi(match):
            base = match.group(1)
            sub = match.group(2)
            return base + cls._to_subscript(sub)

        result = re.sub(r'([a-zA-Z0-9)])_\{([^}]+)\}', repl_multi, text)
        def repl_single(match):
            base = match.group(1)
            sub = match.group(2)
            return base + cls._to_subscript(sub)

        result = re.sub(r'([a-zA-Z0-9)])_([a-zA-Z0-9])', repl_single, result)
        return result

    @classmethod
    def _apply_frac(cls, text: str) -> str:
        """将 \\frac{a}{b} 渲染为 a⁄b（使用 Unicode 分号斜线 U+2044）。"""
        def repl(match):
            num = match.group(1)
            den = match.group(2)
            return f"{num}\u2044{den}"

        # 递归处理嵌套的 \frac
        prev = None
        result = text
        while prev != result:
            prev = result
            result = re.sub(r'\\frac\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}',
                            repl, result)
        return result

    @classmethod
    def _apply_sqrt(cls, text: str) -> str:
        r"""将 \sqrt{x} 转为 √(x)。"""
        def repl(match):
            body = match.group(1)
            return f"√({body})"

        prev = None
        result = text
        while prev != result:
            prev = result
            result = re.sub(r'\\sqrt\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}', repl, result)
        return result

    @classmethod
    def _to_superscript(cls, text: str) -> str:
        """将文本转为 Unicode 上标字符（仅支持有限字符）。"""
        result = []
        for ch in text:
            if ch in SUPERSCRIPT_MAP:
                result.append(SUPERSCRIPT_MAP[ch])
            else:
                # 大写字母没有 Unicode 上标，用小写近似
                if ch.isupper():
                    mapped = SUPERSCRIPT_MAP.get(ch.lower(), ch)
                    result.append(mapped)
                else:
                    result.append(ch)
        return ''.join(result)

    @classmethod
    def _to_subscript(cls, text: str) -> str:
        """将文本转为 Unicode 下标字符。"""
        result = []
        for ch in text:
            if ch in SUBSCRIPT_MAP:
                result.append(SUBSCRIPT_MAP[ch])
            else:
                if ch.isupper():
                    mapped = SUBSCRIPT_MAP.get(ch.lower(), ch)
                    result.append(mapped)
                else:
                    result.append(ch)
        return ''.join(result)

    @classmethod
    def _render_to_chunks(cls, formula: str) -> List[RenderChunk]:
        """将单个 LaTeX 公式渲染为带格式标志的片段列表（供 Word 渲染）。

        更精细：返回的每个片段带有 FLAG_SUPERSCRIPT / FLAG_SUBSCRIPT 等，
        Word 渲染器据此设置 run.font.superscript / subscript。

        这样可支持任意字符的上/下标（而不仅是 Unicode 有限集合）。
        """
        chunks: List[cls.RenderChunk] = []
        text = formula.strip()

        # \tag{...} → 移除
        text = re.sub(r'\\tag\{[^}]*\}', '', text)
        # \quad → 空格
        text = text.replace(r'\quad', '  ').replace(r'\qquad', '    ')
        # \{ → {, \} → }
        text = text.replace(r'\{', '{').replace(r'\}', '}')
        # \big, \Big, \bigl, \bigr, \left, \right → 移除（仅大小提示，括号本身保留）
        text = re.sub(r'\\(?:big[lr]?|Big[lr]?|left|right)\s*', '', text)

        # 希腊字母 & 数学符号预处理（按长度降序）
        for latex, unicode_char in GREEK_MAP.items():
            text = text.replace(latex, unicode_char)
        for latex, unicode_char in _MATH_SYMBOLS_SORTED:
            text = text.replace(latex, unicode_char)
        # \mathbb{R} → ℝ 等黑板粗体
        text = cls._apply_mathbb(text)

        # 解析 \frac{a}{b} → 生成 a/b 三个 chunk
        # 解析 \sqrt{x} → 生成 √x 两个 chunk
        # 解析 x^{2} → x(正常) + 2(上标)
        # 解析 x_{ij} → x(正常) + ij(下标)

        pos = 0
        while pos < len(text):
            # 检查 \frac{...}{...}
            frac_match = re.match(r'\\frac\{', text[pos:])
            if frac_match:
                num_start = pos + frac_match.end()
                num_end = _find_matching_brace(text, num_start)
                if num_end is not None:
                    num = text[num_start:num_end]
                    # 找第二个 {
                    if num_end + 1 < len(text) and text[num_end + 1] == '{':
                        den_start = num_end + 2
                        den_end = _find_matching_brace(text, den_start)
                        if den_end is not None:
                            den = text[den_start:den_end]
                            # 先递归处理分子分母
                            num_chunks = cls._render_to_chunks(num)
                            den_chunks = cls._render_to_chunks(den)
                            chunks.extend(num_chunks)
                            chunks.append(cls.RenderChunk(text='\u2044', flags=cls.FLAG_NORMAL))  # U+2044 fraction slash
                            chunks.extend(den_chunks)
                            pos = den_end + 1
                            continue

            # 检查 \sqrt{...}
            sqrt_match = re.match(r'\\sqrt\{', text[pos:])
            if sqrt_match:
                body_start = pos + sqrt_match.end()
                body_end = _find_matching_brace(text, body_start)
                if body_end is not None:
                    body = text[body_start:body_end]
                    chunks.append(cls.RenderChunk(text='√(', flags=cls.FLAG_NORMAL))
                    body_chunks = cls._render_to_chunks(body)
                    chunks.extend(body_chunks)
                    chunks.append(cls.RenderChunk(text=')', flags=cls.FLAG_NORMAL))
                    pos = body_end + 1
                    continue

            # 检查 ^{...} 上标（需前面有字符）
            if pos > 0 and text[pos:pos + 2] == '^{':
                # text[pos] = '^', text[pos+1] = '{' → { 位于 pos+1
                brace_pos = pos + 1
                exp_end = _find_matching_brace(text, brace_pos)
                if exp_end is not None:
                    exp = text[brace_pos + 1:exp_end]
                    exp_chunks = cls._render_to_chunks(exp)
                    for c in exp_chunks:
                        c.flags |= cls.FLAG_SUPERSCRIPT
                    chunks.extend(exp_chunks)
                    pos = exp_end + 1
                    continue

            # 检查 _{...} 下标
            if pos > 0 and text[pos:pos + 2] == '_{':
                # text[pos] = '_', text[pos+1] = '{' → { 位于 pos+1
                brace_pos = pos + 1
                sub_end = _find_matching_brace(text, brace_pos)
                if sub_end is not None:
                    sub = text[brace_pos + 1:sub_end]
                    sub_chunks = cls._render_to_chunks(sub)
                    for c in sub_chunks:
                        c.flags |= cls.FLAG_SUBSCRIPT
                    chunks.extend(sub_chunks)
                    pos = sub_end + 1
                    continue

            # 检查 ^n（单字符上标）—— 也支持 pos=0（如 $^\circ$）
            if text[pos] == '^' and pos + 1 < len(text):
                ch = text[pos + 1]
                if ch != '{':
                    chunks.append(cls.RenderChunk(text=ch, flags=cls.FLAG_SUPERSCRIPT))
                    pos += 2
                    continue

            # 检查 _n（单字符下标）—— 也支持 pos=0
            if text[pos] == '_' and pos + 1 < len(text):
                ch = text[pos + 1]
                if ch != '{':
                    chunks.append(cls.RenderChunk(text=ch, flags=cls.FLAG_SUBSCRIPT))
                    pos += 2
                    continue

            # 检查 \mathbf / \textit / \mathrm / \text
            fmt_match = re.match(r'\\(mathbf|textbf|textit|mathrm|text)\{', text[pos:])
            if fmt_match:
                cmd = fmt_match.group(1)
                body_start = pos + fmt_match.end()
                body_end = _find_matching_brace(text, body_start)
                if body_end is not None:
                    body = text[body_start:body_end]
                    body_chunks = cls._render_to_chunks(body)
                    flag_map = {
                        'mathbf': cls.FLAG_BOLD,
                        'textbf': cls.FLAG_BOLD,
                        'textit': cls.FLAG_ITALIC,
                    }
                    flag = flag_map.get(cmd, cls.FLAG_NORMAL)
                    for c in body_chunks:
                        c.flags |= flag
                    chunks.extend(body_chunks)
                    pos = body_end + 1
                    continue

            # 普通字符
            chunks.append(cls.RenderChunk(text=text[pos], flags=cls.FLAG_NORMAL))
            pos += 1

        # 清理可能残留的 {} 和反斜杠命令
        cleaned = []
        for c in chunks:
            t = c.text.replace('{', '').replace('}', '')
            t = re.sub(r'\\[a-zA-Z]+', '', t)
            if t:
                cleaned.append(cls.RenderChunk(text=t, flags=c.flags))
        return cleaned


def _find_matching_brace(text: str, start_pos: int) -> Optional[int]:
    """在 text 中找到与 start_pos 处 { 匹配的 } 的位置。

    假设 text[start_pos] = '{'，depth 初始值为 1，
    从 start_pos + 1 开始查找匹配的 }。
    """
    if start_pos >= len(text):
        return None
    depth = 1
    i = start_pos + 1
    while i < len(text) and depth > 0:
        if text[i] == '{':
            depth += 1
        elif text[i] == '}':
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


# ============================================================
# WordFormatRenderer: 段落级格式渲染
# ============================================================

@dataclass
class HeadingEntry:
    """目录条目"""
    level: int
    number: str   # "1.", "1.1", "2.3.1" 等
    text: str


class WordFormatRenderer:
    """Word 文档格式渲染器（完整字体处理版）。"""

    def __init__(self, doc: Document, format_spec: FormatSpec = None):
        self.doc = doc
        self.fmt = format_spec or FormatSpec()

    # --------------------------------------------------
    # 文档级配置
    # --------------------------------------------------
    def apply_document_defaults(self) -> None:
        """应用文档级默认配置"""
        for section in self.doc.sections:
            section.page_width = Cm(21.0)
            section.page_height = Cm(29.7)
            section.top_margin = Cm(self.fmt.top_margin)
            section.bottom_margin = Cm(self.fmt.bottom_margin)
            section.left_margin = Cm(self.fmt.left_margin)
            section.right_margin = Cm(self.fmt.right_margin)

    # --------------------------------------------------
    # Run 级渲染核心（字体控制）
    # --------------------------------------------------
    def _add_run_with_font(
        self,
        paragraph,
        text: str,
        cn_font: str = CN_SONG,
        en_font: str = EN_TNR,
        size_pt: float = 12.0,
        bold: bool = False,
        italic: bool = False,
        superscript: bool = False,
        subscript: bool = False,
        color: Optional[RGBColor] = None,
        math_mode: bool = False,
    ) -> None:
        """添加带字体区分的 run 到段落。

        核心思路：将文本按 CJK/ASCII 拆分成多个片段，
        对每个片段设置合适字体。

        V6.7: math_mode=True 时所有片段统一使用 Cambria Math 字体。
        """
        if not text:
            return

        # V6.7: 数学模式下统一使用数学字体
        if math_mode:
            cn_font = MATH_FONT
            en_font = MATH_FONT

        # 拆分并添加
        segments = split_mixed_text(text)
        for seg_text, seg_type in segments:
            run = paragraph.add_run(seg_text)
            # 根据类型设置字体
            if seg_type == 'cn':
                run.font.name = cn_font
            else:
                run.font.name = en_font
            # XML 级字体设置（确保 Word 正确处理）
            self._set_run_font_xml(run, cn_font, en_font)
            # 字号
            run.font.size = Pt(size_pt)
            # 样式
            run.bold = bold
            run.italic = italic
            if superscript:
                run.font.superscript = True
            if subscript:
                run.font.subscript = True
            if color:
                run.font.color.rgb = color

    def _set_run_font_xml(self, run, cn_font: str, en_font: str) -> None:
        """在 run XML 级别设置 eastAsia / ascii / hAnsi 字体。

        这是 Word 正确显示中英文混合字体的关键。
        """
        rPr = run._element.get_or_add_rPr()
        # 移除已有的 rFonts
        for existing in rPr.findall(qn('w:rFonts')):
            rPr.remove(existing)
        # 添加新的 rFonts
        rFonts = OxmlElement('w:rFonts')
        rFonts.set(qn('w:eastAsia'), cn_font)
        rFonts.set(qn('w:ascii'), en_font)
        rFonts.set(qn('w:hAnsi'), en_font)
        rPr.append(rFonts)

    # --------------------------------------------------
    # 标题级渲染
    # --------------------------------------------------
    def render_title(self, text: str) -> None:
        """渲染论文标题（黑体 22pt，居中）"""
        if not text:
            return
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(18)
        p.paragraph_format.space_after = Pt(18)
        self._add_run_with_font(
            p, text,
            cn_font=CN_HEI, en_font=EN_TNR,
            size_pt=self._pt_value(self.fmt.title_size, 22),
            bold=True,
        )

    def render_heading(self, text: str, level: int) -> None:
        """渲染章节标题（保留原文序号）。"""
        if not text:
            return
        level = min(max(level, 1), 4)
        p = self.doc.add_paragraph()

        # 根据 level 从 FormatSpec 读取样式（消除硬编码）
        commands = {
            1: (self.fmt.heading1_font, self.fmt.heading1_size, self.fmt.heading1_bold, Pt(12), Pt(6)),
            2: (self.fmt.heading2_font, self.fmt.heading2_size, self.fmt.heading2_bold, Pt(8), Pt(4)),
            3: (self.fmt.heading3_font, self.fmt.heading3_size, self.fmt.heading3_bold, Pt(6), Pt(3)),
            4: (self.fmt.heading4_font, self.fmt.heading4_size, self.fmt.heading4_bold, Pt(4), Pt(2)),
        }
        font, size_str, bold, space_before, space_after = commands.get(
            level, (CN_SONG, "12pt", False, Pt(4), Pt(2))
        )
        size = self._pt_value(size_str, 12)
        p.paragraph_format.space_before = space_before
        p.paragraph_format.space_after = space_after

        # V7.7: 直接处理 Markdown **bold** 和 LaTeX \textbf{} 语法，将其转换为 Word 粗体格式
        # 先统一处理：将 \textbf{content} 替换为 **content** 格式，然后统一处理
        normalized_text = re.sub(r'\\textbf\{([^}]*)\}', r'**\1**', text)
        # 同时处理 \textit{content} 等其他 LaTeX 格式命令（移除命令保留内容）
        normalized_text = re.sub(r'\\(?:textit|texttt|emph)\{([^}]*)\}', r'\1', normalized_text)
        # 检测是否包含 **bold** 语法
        bold_pattern = re.compile(r'\*\*([^*]+?)\*\*')
        match = bold_pattern.search(normalized_text)
        if match:
            # 有 **bold** 语法，分段处理
            last_end = 0
            for m in bold_pattern.finditer(normalized_text):
                # 添加 ** 之前的文本
                if m.start() > last_end:
                    before_text = normalized_text[last_end:m.start()]
                    self._add_run_with_font(
                        p, before_text,
                        cn_font=font, en_font=font,
                        size_pt=size,
                        bold=bold,
                    )
                # 添加 **bold** 中的文本（强制粗体）
                bold_text = m.group(1)
                self._add_run_with_font(
                    p, bold_text,
                    cn_font=font, en_font=font,
                    size_pt=size,
                    bold=True,  # 强制粗体
                )
                last_end = m.end()
            # 添加最后一个 ** 之后的文本
            if last_end < len(normalized_text):
                after_text = normalized_text[last_end:]
                self._add_run_with_font(
                    p, after_text,
                    cn_font=font, en_font=font,
                    size_pt=size,
                    bold=bold,
                )
        else:
            # 没有 **bold** 语法，直接渲染
            self._add_run_with_font(
                p, normalized_text,
                cn_font=font, en_font=font,  # 统一使用配置字体（中文/英文可独立配置）
                size_pt=size,
                bold=bold,
            )

    def render_abstract_heading(self, text: str) -> None:
        """渲染摘要/Abstract 标题"""
        if not text:
            return
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(12)
        p.paragraph_format.space_after = Pt(6)
        self._add_run_with_font(
            p, text,
            cn_font=CN_HEI, en_font=EN_TNR,
            size_pt=self._pt_value(self.fmt.heading1_size, 16),
            bold=True,
        )

    # --------------------------------------------------
    # 正文渲染
    # --------------------------------------------------
    def render_text(self, content: str, indent_first: bool = True,
                    cite_map: dict = None) -> None:
        """渲染正文段落（按 FormatSpec 设置字体、字号、行距）。"""
        if not content:
            return

        # V7.6: 将引用键 [key1,key2] 替换为编号 [1,2]
        if cite_map:
            content = self._resolve_citations(content, cite_map)

        p = self.doc.add_paragraph()
        p.paragraph_format.line_spacing = self.fmt.line_spacing
        if indent_first:
            p.paragraph_format.first_line_indent = Cm(self.fmt.indent_width)
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)

        # 将段落拆分为普通文本和引用片段（[1], [1-3] 等）
        segments = self._split_by_citations(content)

        for seg_text, is_citation in segments:
            if is_citation:
                # 引用片段：加上标
                self._add_run_with_font(
                    p, seg_text,
                    cn_font=CN_SONG, en_font=EN_TNR,
                    size_pt=self._pt_value(self.fmt.body_size, 12),
                    superscript=True,
                )
            else:
                # 普通文本：但需要处理其中的 LaTeX 公式
                self._render_text_with_latex(p, seg_text)

    def _split_by_citations(self, text: str) -> List[Tuple[str, bool]]:
        """将文本按 [1]、[1-3]、[1,2,3]、[1-3,5,7-9] 等引用模式切片。

        返回 [(segment, is_citation), ...]
        """
        if not text:
            return []

        segments = []
        # 引用模式：[数字]、[数字-数字]、[数字,数字]、[数字-数字,数字]
        pattern = re.compile(r'\[\d+(?:[-\u2013–][\d]+)?(?:[,、]\s*\d+(?:[-\u2013–][\d]+)?)*\]')
        last_end = 0
        for m in pattern.finditer(text):
            # 添加之前的普通文本
            if m.start() > last_end:
                segments.append((text[last_end:m.start()], False))
            # 添加引用
            segments.append((m.group(), True))
            last_end = m.end()
        # 添加剩余
        if last_end < len(text):
            segments.append((text[last_end:], False))

        # 如果没有找到任何引用，整段作为普通文本
        if not segments:
            segments.append((text, False))
        return segments

    def _render_text_with_latex(self, paragraph, text: str) -> None:
        """在正文中渲染包含 LaTeX 的文本。

        策略：
        1. 对文本中的 $formula$ 片段用 RenderChunk 精细处理
        2. 对普通文本中的 _{letters}、^{text} 等数学下标/上标也进行识别和渲染
        3. V7.6: 对以 $$ 开头但无闭合 $$ 的行（多行公式片段），直接清洗后渲染
        """
        if not text:
            return

        # V7.6: 跳过纯 $$ / \end{aligned}$$ 等公式块标记行
        stripped = text.strip()
        if stripped in ('$$', r'\$\$', r'\end{aligned}$$', r'$$\end{aligned}',
                        r'\begin{aligned}$$', r'$$\begin{aligned}'):
            return
        # 跨行变体：\end{aligned}\n$$
        merged = stripped.replace('\n', '')
        if merged in (r'\end{aligned}$$', r'$$\end{aligned}',
                      r'\begin{aligned}$$', r'$$\begin{aligned}',
                      r'\endaligned$$', r'$$endaligned',
                      r'\beginaligned$$', r'$$beginaligned'):
            return
        # V7.6: 跳过 LaTeX 表格浮动环境残渣（\end{table} / \begin{table} 剥离后残留）
        if stripped in ('table', r'\endtable', r'\end{table}', r'\begin{table}',
                        r'\begintable', r'\\endtable', r'\\begintable'):
            return

        # V7.6: 处理不完整的 $$ 公式块（仅开头有 $$ 无闭合）
        if stripped.startswith(r'$$') and not stripped.endswith(r'$$'):
            # 多行公式片段：用 chunk 渲染保留下标/上标格式
            formula = stripped.replace(r'$$', '', 1).strip()
            self._render_formula_chunks(paragraph, formula)
            return

        # V7.6: 检测无 $ 定界符的纯 LaTeX 公式行（如 aligned 内的 \phi_1=...\\）
        # 特征：以 \ 开头，包含数学结构（_ ^ = {），不含中文字符
        if (stripped.startswith('\\') and 
            not any('\u4e00' <= c <= '\u9fff' for c in stripped) and
            any(c in stripped for c in ('=', '_', '^', '{', '}', r'\frac'))):
            # 用 chunk 渲染保留下标/上标格式
            formula = stripped.replace(r'\\', '').replace(r'\&', '&')
            self._render_formula_chunks(paragraph, formula)
            return

        # 第一步：用 LaTeXHumanizer 拆分出公式区和非公式区
        chunks = LaTeXHumanizer.humanize_to_runs(text)

        # 第二步：对非公式的普通chunk，额外处理 \textbf{} 等格式命令和数学下标/上标
        final_chunks = []
        for chunk in chunks:
            if chunk.flags == 0 and '$' not in chunk.text:
                # 普通文本：先对 LaTeX 转义字符去转义
                text = LaTeXHumanizer._unescape_text(chunk.text)
                # V7.8: 先处理 \textbf{content}，保留加粗语义
                if r'\textbf{' in text:
                    fmt_chunks = self._split_latex_format_chunks(text)
                    for fc in fmt_chunks:
                        sub_chunks = self._extract_inline_subscripts(fc.text)
                        for sc in sub_chunks:
                            sc.flags |= fc.flags
                        final_chunks.extend(sub_chunks)
                else:
                    # 无 \textbf{}，直接去掉残留 LaTeX 命令
                    text = re.sub(r'\\[a-zA-Z]+(?:\{[^}]*\})?', '', text)
                    # 检查其中的 X_{letters}、X^{text}、X_digit 等
                    sub_chunks = self._extract_inline_subscripts(text)
                    final_chunks.extend(sub_chunks)
            else:
                final_chunks.append(chunk)

        # V7.6: 合并孤儿下标/上标 — 当 humanize_to_runs 把 $φ$_i(v) 拆成
        # chunk[φ] + chunk[_i(v)] 时，将 _i(v) 合并为前一 chunk 的下标
        merged = []
        for chunk in final_chunks:
            if merged and chunk.flags == 0 and chunk.text and chunk.text[0] in ('_', '^'):
                prev = merged[-1]
                is_sub = chunk.text[0] == '_'
                body = chunk.text[1:].lstrip('{').rstrip('}')
                # 提取下标/上标文本（到第一个非字母数字字符或括号）
                m = re.match(r'([a-zA-Z0-9]+)', body)
                if m:
                    sub_text = m.group(1)
                    merged.append(LaTeXHumanizer.RenderChunk(
                        text=sub_text,
                        flags=LaTeXHumanizer.FLAG_SUBSCRIPT if is_sub else LaTeXHumanizer.FLAG_SUPERSCRIPT
                    ))
                    rest = body[m.end():]
                    if rest:
                        merged.append(LaTeXHumanizer.RenderChunk(text=rest, flags=0))
                else:
                    merged.append(chunk)
            else:
                merged.append(chunk)
        final_chunks = merged

        # 第三步：渲染所有 chunk
        for chunk in final_chunks:
            flags = chunk.flags
            is_sup = bool(flags & LaTeXHumanizer.FLAG_SUPERSCRIPT)
            is_sub = bool(flags & LaTeXHumanizer.FLAG_SUBSCRIPT)
            is_bold = bool(flags & LaTeXHumanizer.FLAG_BOLD)
            is_italic = bool(flags & LaTeXHumanizer.FLAG_ITALIC)
            # V6.7: 含数学标志时使用 Cambria Math 字体
            is_math = is_sup or is_sub or is_italic or is_bold or (flags != 0)

            self._add_run_with_font(
                paragraph, chunk.text,
                cn_font=CN_SONG, en_font=MATH_FONT if is_math else EN_TNR,
                size_pt=self._pt_value(self.fmt.body_size, 12),
                bold=is_bold,
                italic=is_italic,
                superscript=is_sup,
                subscript=is_sub,
                math_mode=is_math,
            )

    def _render_formula_chunks(self, paragraph, formula: str) -> None:
        """V7.6: 用 chunk 渲染单行公式，保留下标/上标/粗体/斜体格式。
        
        相比 _render_single 返回纯文本，此方法通过 RenderChunk 的 
        FLAG_SUBSCRIPT / FLAG_SUPERSCRIPT 标志，在 Word 中使用真正的
        font.subscript / font.superscript 属性。
        """
        if not formula or not formula.strip():
            return
        chunks = LaTeXHumanizer._render_to_chunks(formula)
        if not chunks:
            return
        
        body_size = self._pt_value(self.fmt.body_size, 12)
        self._add_run_with_font(paragraph, ' ', cn_font=CN_SONG, en_font=MATH_FONT,
                                size_pt=body_size, math_mode=True)
        for chunk in chunks:
            flags = chunk.flags
            self._add_run_with_font(
                paragraph, chunk.text,
                cn_font=CN_SONG, en_font=MATH_FONT,
                size_pt=body_size,
                bold=bool(flags & LaTeXHumanizer.FLAG_BOLD),
                italic=bool(flags & LaTeXHumanizer.FLAG_ITALIC),
                superscript=bool(flags & LaTeXHumanizer.FLAG_SUPERSCRIPT),
                subscript=bool(flags & LaTeXHumanizer.FLAG_SUBSCRIPT),
                math_mode=True,
            )
        self._add_run_with_font(paragraph, ' ', cn_font=CN_SONG, en_font=MATH_FONT,
                                size_pt=body_size, math_mode=True)

    def _extract_inline_subscripts(self, text: str) -> List:
        """从普通文本中提取数学下标/上标（通用扫描+正则搜索）。

        支持的格式（按优先级排序）：
        1. T_{core}, P_{measured}, f_{ij}  - LaTeX 花括号下标
        2. T{core}, T{eff}, P{total}       - 无下划线花括号下标
        3. x^{2}, E^{2}                    - LaTeX 花括号上标
        4. x_1, f_2                        - 单字母+数字下标
        5. x^2, E^2                        - 单字母+数字上标
        6. T_eff, P_total, E_max           - 多字母下标
        7. E_w, P_t, L_b, G_t              - 单字母下标
        8. α_i, β_{ij}, γ_k               - 希腊字母开头的下标

        base 字符定义：ASCII 单个字母(a-z, A-Z)或希腊字母(α, β, γ, δ, ε, ζ, η, θ, ι, κ, λ, μ, ν, ξ, π, ρ, σ, τ, υ, φ, χ, ψ, ω)

        返回 RenderChunk 列表（带 FLAG_SUBSCRIPT / FLAG_SUPERSCRIPT 标志）。
        """
        if not text:
            return []

        # Base 字符正则：单个 ASCII 字母 + 常用希腊字母
        base_pattern = r'[a-zA-ZαβγδεζηθικλμνξπρστυφχψωΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ]'

        # 模式定义（按优先级排序，先匹配更具体的模式）
        # 每个元组: (regex, group_idx_base, group_idx_content, flag)
        # 模式 1-5：LaTeX 花括号格式 / 纯数字下标 / 纯数字上标（严格模式，不会误匹配普通文本）
        # 模式 6-7：无下划线花括号下标 / 单字母下标（严格，只在特定上下文中出现）
        # 模式 8-9：多字母下标 / 单字母下标（需要严格的单词边界，避免误匹配代码路径）
        #
        # 关键：对于多字母下标，使用 \b 或 (?![a-zA-Z/]) 确保不会匹配文件路径如 hf_assessment/
        # 同时避免 "word_end_another_word" 这类普通英语连字符
        patterns = [
            # 1. LaTeX 花括号下标 + 数字上标: T_{core}^2, E_{max}^2
            (r'(' + base_pattern + r')_\{([a-zA-Z0-9]+)\}\^(\d)', 1, None, LaTeXHumanizer.FLAG_SUBSCRIPT, 3, LaTeXHumanizer.FLAG_SUPERSCRIPT),
            # 2. LaTeX 花括号下标 + 花括号上标: T_{core}^{max}
            (r'(' + base_pattern + r')_\{([a-zA-Z0-9]+)\}\^\{([^}]+)\}', 1, None, LaTeXHumanizer.FLAG_SUBSCRIPT, 3, LaTeXHumanizer.FLAG_SUPERSCRIPT),
            # 3. LaTeX 花括号下标: T_{core}, β_{ij}
            (r'(' + base_pattern + r')_\{([a-zA-Z0-9]+)\}', 1, None, LaTeXHumanizer.FLAG_SUBSCRIPT, None, 0),
            # 4. 无下划线花括号下标: T{core}, P{total}
            (r'(' + base_pattern + r')\{([a-zA-Z0-9]+)\}', 1, None, LaTeXHumanizer.FLAG_SUBSCRIPT, None, 0),
            # 5. LaTeX 花括号上标: x^{2}, E^{max}
            (r'(' + base_pattern + r')\^\{([^}]+)\}', 1, None, LaTeXHumanizer.FLAG_SUPERSCRIPT, None, 0),
            # 6. 数字下标: x_1, f_2
            (r'(' + base_pattern + r')_(\d)', 1, None, LaTeXHumanizer.FLAG_SUBSCRIPT, None, 0),
            # 7. 数字上标: x^2
            (r'(' + base_pattern + r')\^(\d)', 1, None, LaTeXHumanizer.FLAG_SUPERSCRIPT, None, 0),
            # 8. 多字母下标: T_eff, P_total, E_max, G_h
            #    严格检查：base 是大写字母或希腊字母，subscript 以小写字母开头
            #    后面不是字母也不是 /（避免匹配代码路径）
            (r'([A-Z]|[αβγδεζηθικλμνξπρστυφχψωΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ])_([a-zA-Z][a-zA-Z0-9]*)(?![a-zA-Z/])', 1, None, LaTeXHumanizer.FLAG_SUBSCRIPT, None, 0),
            # 9. 单字母下标: E_w, P_t, L_b, G_t, P_i
            #    同样要求 base 是大写字母或希腊字母
            #    后面不是字母也不是 /
            (r'([A-Z]|[αβγδεζηθικλμνξπρστυφχψωΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ])_([a-zA-Z])(?![a-zA-Z/])', 1, None, LaTeXHumanizer.FLAG_SUBSCRIPT, None, 0),
            # 10. 转义下划线 + 多字母下标: E\_w, P\_i, G\_t
            #     处理已经被 escape_text 转义过的下划线
            (r'([A-Z]|[αβγδεζηθικλμνξπρστυφχψωΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ])\\_([a-zA-Z][a-zA-Z0-9]*)', 1, None, LaTeXHumanizer.FLAG_SUBSCRIPT, None, 0),
            # 11. 转义下划线 + 单字母下标: E\_w, P\_i
            (r'([A-Z]|[αβγδεζηθικλμνξπρστυφχψωΑΒΓΔΕΖΗΘΙΚΛΜΝΞΟΠΡΣΤΥΦΧΨΩ])\\_([a-zA-Z])', 1, None, LaTeXHumanizer.FLAG_SUBSCRIPT, None, 0),
            # 12. 转义下划线 + 数字下标: P\_1, T\_2
            (r'(' + base_pattern + r')\\_(\d)', 1, None, LaTeXHumanizer.FLAG_SUBSCRIPT, None, 0),
            # 13. 转义下划线 + 数字上标: x\^2
            (r'(' + base_pattern + r')\^\\(\d)', 1, None, LaTeXHumanizer.FLAG_SUPERSCRIPT, None, 0),
        ]

        chunks = []
        pos = 0
        n = len(text)

        while pos < n:
            remaining = text[pos:]

            # 搜索所有模式，找到最靠前的匹配
            best_match = None
            best_start = len(remaining)

            for item in patterns:
                regex = item[0]
                g1 = item[1]
                g2_sub_idx = item[2] if item[2] is not None else 2
                flag_sub = item[3]
                g3_sup_idx = item[4]
                flag_sup = item[5]

                m = re.search(regex, remaining)
                if m and m.start() < best_start:
                    best_start = m.start()
                    best_match = (m, g1, g2_sub_idx, flag_sub, g3_sup_idx, flag_sup)

            if best_match is None:
                # 没有匹配，剩余全部作为普通文本
                chunks.append(LaTeXHumanizer.RenderChunk(text=remaining, flags=0))
                break

            m, g1, g2_sub_idx, flag_sub, g3_sup_idx, flag_sup = best_match
            start = m.start()
            end = m.end()

            # 匹配前的普通文本
            if start > 0:
                chunks.append(LaTeXHumanizer.RenderChunk(text=remaining[:start], flags=0))

            # 处理 base 字母
            base = m.group(g1)
            chunks.append(LaTeXHumanizer.RenderChunk(text=base, flags=0))

            # 处理下标内容
            if g2_sub_idx is not None:
                sub_content = m.group(g2_sub_idx)
                chunks.append(LaTeXHumanizer.RenderChunk(text=sub_content, flags=flag_sub))

            # 处理上标内容（如果是组合模式）
            if g3_sup_idx is not None and flag_sup != 0:
                sup_content = m.group(g3_sup_idx)
                chunks.append(LaTeXHumanizer.RenderChunk(text=sup_content, flags=flag_sup))

            # 移动 pos
            pos += end

        return chunks

    def _split_latex_format_chunks(self, text: str) -> List[LaTeXHumanizer.RenderChunk]:
        """将包含 \\textbf{} 等 LaTeX 格式命令的文本拆分为带格式标志的片段。

        例如 "经济含义是\\textbf{核心稳定性}定理" →
        [Chunk("经济含义是", 0), Chunk("核心稳定性", FLAG_BOLD), Chunk("定理", 0)]
        """
        chunks = []
        # 匹配 \textbf{...}、\textit{...}、\emph{...}
        pattern = re.compile(r'\\(textbf|textit|emph)\{([^}]*)\}')
        last_end = 0
        for m in pattern.finditer(text):
            # 添加匹配之前的普通文本（清理其他 LaTeX 命令）
            if m.start() > last_end:
                before = text[last_end:m.start()]
                before = re.sub(r'\\[a-zA-Z]+(?:\{[^}]*\})?', '', before)
                if before:
                    chunks.append(LaTeXHumanizer.RenderChunk(text=before, flags=0))
            # 添加格式化文本
            cmd = m.group(1)
            content = m.group(2)
            flag_map = {
                'textbf': LaTeXHumanizer.FLAG_BOLD,
                'textit': LaTeXHumanizer.FLAG_ITALIC,
                'emph': LaTeXHumanizer.FLAG_ITALIC,
            }
            flag = flag_map.get(cmd, 0)
            if content:
                chunks.append(LaTeXHumanizer.RenderChunk(text=content, flags=flag))
            last_end = m.end()
        # 添加剩余文本
        if last_end < len(text):
            after = text[last_end:]
            after = re.sub(r'\\[a-zA-Z]+(?:\{[^}]*\})?', '', after)
            if after:
                chunks.append(LaTeXHumanizer.RenderChunk(text=after, flags=0))
        return chunks

    # --------------------------------------------------
    # 图表、引用、关键词等
    # --------------------------------------------------
    def render_image_caption(self, caption: str, idx: int = 1) -> None:
        """渲染图片图注：图X ..."""
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        self._add_run_with_font(
            p, f"图{idx} {caption}",
            cn_font=CN_SONG, en_font=EN_TNR,
            size_pt=self._pt_value(self.fmt.caption_size, 10.5),
        )

    @staticmethod
    def _normalize_table_caption(caption: str, idx: int) -> str:
        """V7.6: 标准化表格标题。
        
        规则：
        1. 如果 caption 为空 → "Table N"（中文模板 "表N"）
        2. 如果 caption 以 "表" 开头且含数字 → "表N caption_text"
        3. 如果 caption 以 "Table" 开头且含数字 → "Table N caption_text"  
        4. 否则 → "Table N caption"
        """
        _re = re
        clean = caption.strip() if caption else ""
        
        if not clean:
            return f"Table {idx}"
        
        # 检查是否已含"表N "前缀（中文）
        m = _re.match(r'^表\s*\d+\s*[：:.\s]?\s*(.*)', clean)
        if m:
            body = m.group(1).strip()
            return f"表{idx} {body}" if body else f"表{idx}"
        
        # 检查是否已含"Table N"前缀（英文）
        m = _re.match(r'^Table\s*\d+\s*[：:.\s]?\s*(.*)', clean, _re.IGNORECASE)
        if m:
            body = m.group(1).strip()
            return f"Table {idx} {body}" if body else f"Table {idx}"
        
        # 否则，添加 "Table N " 前缀
        return f"Table {idx} {clean}"

    def render_table_caption(self, caption: str, idx: int = 1) -> None:
        """渲染表格标题：Table N / 表N ...
        
        V7.6: 如果 caption 本身已含"表N"或"Table N"前缀，则规范化后显示；
        否则生成 "Table N caption" 格式。
        """
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        
        # V7.6: 标准化 caption —— 如果 caption 已含表/Table 编号前缀则提取纯文本
        display_text = self._normalize_table_caption(caption, idx)
        
        self._add_run_with_font(
            p, display_text,
            cn_font=CN_SONG, en_font=EN_TNR,
            size_pt=self._pt_value(self.fmt.caption_size, 10.5),
        )

    def insert_image(self, image_path: str, width_cm: float = 14.0) -> None:
        """插入图片"""
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run()
        if os.path.exists(image_path):
            try:
                run.add_picture(image_path, width=Cm(width_cm))
            except Exception:
                run.add_text(f"[图片: {os.path.basename(image_path)}]")
                run.font.name = CN_SONG
        else:
            run.add_text(f"[图片缺失: {os.path.basename(image_path)}]")
            run.font.name = CN_SONG

    def insert_table(
        self,
        headers: List[str],
        rows: List[List[str]],
        caption: str = "",
        idx: int = 0,
    ) -> None:
        """插入三线表。

        三线表格式：
        - 顶线：1.5pt 粗线
        - 表头底线：0.75pt 细线
        - 表格底线：1.5pt 粗线
        - 无其他网格线
        
        V7.6: 始终在表格上方显示 "Table N caption" 标题。
        """
        # V7.6: 始终渲染表格标题
        self.render_table_caption(caption, idx)
        if not headers and not rows:
            return

        n_cols = len(headers) if headers else (len(rows[0]) if rows else 1)
        table = self.doc.add_table(
            rows=len(rows) + (1 if headers else 0), cols=n_cols,
        )
        table.alignment = WD_TABLE_ALIGNMENT.CENTER

        # 清除默认样式，设置为三线表
        # 顶线（第一行的上边）
        if headers:
            first_row = table.rows[0]
            self._set_table_row_borders(first_row, top_line=True, bottom_line=True, top_width=15, bottom_width=7)
            for i, header_text in enumerate(headers):
                cell = first_row.cells[i]
                cell.text = ""
                # V7.6: 表格文本经过 LaTeX 人读化处理
                display_text = LaTeXHumanizer.humanize_plain_text(header_text)
                run = cell.paragraphs[0].add_run(display_text)
                run.font.name = CN_SONG
                run.font.size = Pt(self._pt_value(self.fmt.caption_size, 10.5))
                run.bold = True
                self._set_run_font_xml(run, CN_SONG, EN_TNR)
                cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER

        # 数据行
        data_start = 1 if headers else 0
        total_rows = len(rows) + (1 if headers else 0)
        for row_idx, row_data in enumerate(rows):
            doc_row_idx = row_idx + data_start
            doc_row = table.rows[doc_row_idx]
            # 最后一行设置底线（1.5pt 粗）
            is_last = (doc_row_idx == total_rows - 1)
            self._set_table_row_borders(doc_row, bottom_line=is_last, bottom_width=15 if is_last else 0)

            for col_idx, cell_text in enumerate(row_data):
                if col_idx < n_cols:
                    cell = doc_row.cells[col_idx]
                    cell.text = ""
                    # V7.6: 表格文本经过 LaTeX 人读化处理
                    display_text = LaTeXHumanizer.humanize_plain_text(cell_text)
                    run = cell.paragraphs[0].add_run(display_text)
                    run.font.name = CN_SONG
                    run.font.size = Pt(self._pt_value(self.fmt.body_size, 11))
                    self._set_run_font_xml(run, CN_SONG, EN_TNR)
                    cell.paragraphs[0].alignment = WD_ALIGN_PARAGRAPH.CENTER

    def _set_table_row_borders(self, row, top_line=False, bottom_line=False, top_width=0, bottom_width=0):
        """设置表格行的边框（用于三线表）。

        width: 线条宽度，单位为 1/8 pt（Word 的单位）
               0 = 无边框，7 ≈ 0.75pt (细线), 15 ≈ 1.5pt (粗线)
        """
        from docx.oxml.ns import qn
        for cell in row.cells:
            tc_pr = cell._tc.get_or_add_tcPr()
            # 清除所有现有的 tcBorders
            for existing in tc_pr.findall(qn('w:tcBorders')):
                tc_pr.remove(existing)

            borders = OxmlElement('w:tcBorders')
            if top_line:
                top = OxmlElement('w:top')
                top.set(qn('w:val'), 'single')
                top.set(qn('w:sz'), str(top_width))
                top.set(qn('w:space'), '0')
                top.set(qn('w:color'), 'auto')
                borders.append(top)
            else:
                # 无边框
                top = OxmlElement('w:top')
                top.set(qn('w:val'), 'none')
                borders.append(top)

            if bottom_line:
                bottom = OxmlElement('w:bottom')
                bottom.set(qn('w:val'), 'single')
                bottom.set(qn('w:sz'), str(bottom_width))
                bottom.set(qn('w:space'), '0')
                bottom.set(qn('w:color'), 'auto')
                borders.append(bottom)
            else:
                bottom = OxmlElement('w:bottom')
                bottom.set(qn('w:val'), 'none')
                borders.append(bottom)

            # 左右边框去掉
            for side in ['left', 'right']:
                elem = OxmlElement(f'w:{side}')
                elem.set(qn('w:val'), 'none')
                borders.append(elem)

            tc_pr.append(borders)

    def render_references_heading(self, title: str = "参考文献") -> None:
        """渲染参考文献标题"""
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(18)
        p.paragraph_format.space_after = Pt(6)
        self._add_run_with_font(
            p, title,
            cn_font=CN_HEI, en_font=EN_TNR,
            size_pt=self._pt_value(self.fmt.heading1_size, 16),
            bold=True,
        )

    def render_reference_item(self, text: str, ref_number: int = 0) -> None:
        """渲染单条参考文献

        如果 ref_number > 0，会在文本前添加 "[N] " 编号。
        """
        p = self.doc.add_paragraph()
        p.paragraph_format.line_spacing = 1.0
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.left_indent = Cm(0.74)
        p.paragraph_format.first_line_indent = Cm(-0.74)
        # 添加编号（如 [1]）
        if ref_number and ref_number > 0:
            self._add_run_with_font(
                p, f"[{ref_number}] ",
                cn_font=CN_SONG, en_font=EN_TNR,
                size_pt=self._pt_value(self.fmt.ref_size, 10.5),
            )
        # 主体内容（已去除可能的 [N] 前缀）
        body = text.strip()
        # 如果 body 自身已经以 [N] 开头，则不再添加
        if ref_number and ref_number > 0:
            import re as _re
            body = _re.sub(r'^\s*\[\d+\]\s*', '', body)
        # V7.6: 参考文献文本经过 LaTeX 人读化处理
        body = LaTeXHumanizer.humanize_plain_text(body)
        self._add_run_with_font(
            p, body,
            cn_font=CN_SONG, en_font=EN_TNR,
            size_pt=self._pt_value(self.fmt.ref_size, 10.5),
        )

    def render_abstract_content(self, content: str) -> None:
        """渲染摘要内容"""
        if not content:
            return
        # V7.8: 清除 \textbf{} 等 LaTeX 格式命令
        content = re.sub(r'\\textbf\{([^}]*)\}', r'\1', content)
        content = re.sub(r'\\(?:textit|texttt|emph)\{([^}]*)\}', r'\1', content)
        p = self.doc.add_paragraph()
        p.paragraph_format.line_spacing = self.fmt.line_spacing
        p.paragraph_format.first_line_indent = Cm(self.fmt.indent_width)
        self._add_run_with_font(
            p, content,
            cn_font=CN_SONG, en_font=EN_TNR,
            size_pt=self._pt_value(self.fmt.body_size, 12),
        )

    def render_keywords(self, content: str) -> None:
        """渲染关键词"""
        if not content:
            return
        # V7.8: 清除 \textbf{} 等 LaTeX 格式命令
        content = re.sub(r'\\textbf\{([^}]*)\}', r'\1', content)
        content = re.sub(r'\\(?:textit|texttt|emph)\{([^}]*)\}', r'\1', content)
        p = self.doc.add_paragraph()
        p.paragraph_format.line_spacing = self.fmt.line_spacing
        p.paragraph_format.first_line_indent = Cm(self.fmt.indent_width)
        # "关键词" 加粗
        prefix = "关键词" if "关键词" in content else "Keywords"
        if prefix in content:
            idx = content.find(prefix)
            label = content[:idx + len(prefix) + 1] if idx + len(prefix) + 1 <= len(content) and content[idx + len(prefix)] in ":：" else content[:idx + len(prefix)] + "："
            body = content[len(label):].strip() if content[len(label):] else content[len(prefix):].strip()
            self._add_run_with_font(
                p, label,
                cn_font=CN_SONG, en_font=EN_TNR,
                size_pt=self._pt_value(self.fmt.body_size, 12),
                bold=True,
            )
            if body:
                self._add_run_with_font(
                    p, body,
                    cn_font=CN_SONG, en_font=EN_TNR,
                    size_pt=self._pt_value(self.fmt.body_size, 12),
                )
        else:
            self._add_run_with_font(
                p, content,
                cn_font=CN_SONG, en_font=EN_TNR,
                size_pt=self._pt_value(self.fmt.body_size, 12),
            )

    # --------------------------------------------------
    # 目录渲染
    # --------------------------------------------------
    def render_toc(self, headings: List[HeadingEntry]) -> None:
        """渲染目录。"""
        if not headings:
            return
        toc_title = "Contents" if self.fmt.language == "en" else "目 录"
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.space_before = Pt(18)
        p.paragraph_format.space_after = Pt(12)
        self._add_run_with_font(
            p, toc_title,
            cn_font=CN_HEI, en_font=EN_TNR,
            size_pt=self._pt_value(self.fmt.heading1_size, 16),
            bold=True,
        )

        for entry in headings:
            p = self.doc.add_paragraph()
            p.paragraph_format.line_spacing = self.fmt.line_spacing
            indent = (entry.level - 1) * 0.5
            if indent > 0:
                p.paragraph_format.left_indent = Cm(indent)

            # 序号 + 标题文本（number 已包含末尾的点号）
            title_text = f"{entry.number} {entry.text}".strip()
            self._add_run_with_font(
                p, title_text,
                cn_font=CN_SONG, en_font=EN_TNR,
                size_pt=self._pt_value(self.fmt.body_size, 12),
                bold=(entry.level == 1),
            )

    # --------------------------------------------------
    # 辅助
    # --------------------------------------------------
    @staticmethod
    def _pt_value(size_str: str, default: float = 12) -> float:
        """字号字符串 → pt 数值"""
        if not size_str:
            return float(default)
        font_size_map = {
            "初号": 42, "小初": 36, "一号": 26, "小一": 24,
            "二号": 22, "小二": 18, "三号": 16, "小三": 15,
            "四号": 14, "小四": 12, "五号": 10.5, "小五": 9,
            "六号": 7.5, "小六": 6.5, "七号": 5.5, "八号": 5,
        }
        if size_str in font_size_map:
            return font_size_map[size_str]
        try:
            clean = size_str.replace("pt", "").replace("PT", "").strip()
            return float(clean)
        except (ValueError, TypeError):
            return float(default)

    @staticmethod
    def _resolve_citations(text: str, cite_map: dict) -> str:
        """将引用键 [key1,key2] 替换为编号 [1,2]，无法匹配的移除。"""
        import re as _re
        def _repl(m):
            keys = [k.strip() for k in m.group(1).split(',')]
            nums = []
            for k in keys:
                if k in cite_map:
                    nums.append(str(cite_map[k]))
            if nums:
                return '[' + ','.join(nums) + ']'
            return m.group(0)  # 保持原样（理论上不应发生，所有键已在首次扫描中映射）
        # 匹配 [key,key] 但排除 [数字] 和 [数字-数字]
        return _re.sub(r'\[([a-z][a-z0-9]*(?:\s*,\s*[a-z][a-z0-9]*)*)\]', _repl, text)


# ============================================================
# WordDocumentBuilder: 从 blocks 构建 Word 文档
# ============================================================

class WordDocumentBuilder:
    """Word 文档构建器"""

    def __init__(self, format_spec: FormatSpec = None):
        self.doc = Document()
        self.renderer = WordFormatRenderer(self.doc, format_spec)
        self.fmt = format_spec or FormatSpec()

    def build_from_blocks(
        self,
        blocks: List[Block],
        title: Optional[str] = None,
        author: str = "",
        output_dir: str = ".",
        filename: str = "paper",
        images_map: Optional[dict] = None,
        tables_map: Optional[dict] = None,
    ) -> str:
        """从 blocks 构建 Word 文档。"""
        images_map = images_map or {}
        tables_map = tables_map or {}

        # 第一阶段：收集所有 heading（用于目录）
        headings = self._collect_headings(blocks)

        # V7.6: 构建引用键 → 编号映射（按首次出现顺序）
        # 遍历所有 text block，收集 [key1,key2] 格式的引用键
        cite_map = {}
        _cite_key_re = re.compile(r'\[([a-z][a-z0-9]*(?:\s*,\s*[a-z][a-z0-9]*)*)\]')
        for block in blocks:
            if block.type == "text" and block.content:
                for m in _cite_key_re.finditer(block.content):
                    keys = [k.strip() for k in m.group(1).split(',')]
                    for k in keys:
                        if k not in cite_map:
                            cite_map[k] = len(cite_map) + 1

        # 第二阶段：渲染内容
        # 应用文档级配置
        self.renderer.apply_document_defaults()

        # 追踪计数器
        figure_idx = 0
        table_idx = 0
        # 已渲染的 reference-item 列表（用于自动分配编号）
        blocks_seen = []

        # 1. 渲染标题
        if title:
            self.renderer.render_title(title)
        else:
            for block in blocks:
                if block.type == "title":
                    self.renderer.render_title(block.content)
                    break
            else:
                self.renderer.render_title("论文")

        # 标题后插入分页符（第一页只有标题）
        self._add_page_break()

        # 2. 渲染目录（在正文前，单独一页）
        self.renderer.render_toc(headings)

        # 3. 目录后插入分页符（正文从新页开始）
        self._add_page_break()

        # 4. 遍历 blocks 渲染正文
        for block in blocks:
            if block.type == "title":
                continue

            elif block.type == "heading":
                # 一级章节前插入分页符
                level = getattr(block, "level", 1)
                if level == 1:
                    self._add_page_break()
                self._render_block_heading(block)

            elif block.type == "abstract":
                content = block.content
                if "摘要" in content.strip()[:10] or "Abstract" in content.strip()[:10]:
                    self.renderer.render_abstract_heading(content.strip())
                else:
                    self.renderer.render_abstract_content(content)

            elif block.type == "abstract-en":
                content = block.content
                if "Abstract" in content.strip()[:15]:
                    self.renderer.render_abstract_heading(content.strip())
                else:
                    self.renderer.render_abstract_content(content)

            elif block.type == "keywords":
                self.renderer.render_keywords(block.content)

            elif block.type == "text":
                self.renderer.render_text(block.content, indent_first=True, cite_map=cite_map)

            elif block.type == "image":
                figure_idx += 1
                img_obj = block.data.get("image_obj") if block.data else None
                if img_obj is None and block.idx in images_map:
                    img_obj = images_map[block.idx]

                if img_obj is not None:
                    img_path = self._resolve_image_path(img_obj, output_dir)
                    if img_path:
                        self.renderer.insert_image(img_path, width_cm=14.0)
                    else:
                        self._insert_image_placeholder(figure_idx)
                else:
                    self._insert_image_placeholder(figure_idx)

                caption = ""
                if block.data and block.data.get("caption"):
                    caption = block.data["caption"]
                if img_obj and getattr(img_obj, "caption", ""):
                    caption = img_obj.caption
                if caption:
                    self.renderer.render_image_caption(caption, figure_idx)

            elif block.type == "table":
                table_idx += 1
                headers = []
                rows = []
                caption = ""

                table_obj = block.data.get("table_obj") if block.data else None
                if table_obj is None and block.idx in tables_map:
                    table_obj = tables_map[block.idx]

                if table_obj is not None:
                    headers = getattr(table_obj, "headers", [])
                    rows = getattr(table_obj, "rows", [])
                    caption = getattr(table_obj, "caption", "") or block.data.get("caption", "")

                if not caption:
                    caption = block.data.get("caption", "") if block.data else ""

                self.renderer.insert_table(
                    headers=headers, rows=rows, caption=caption, idx=table_idx,
                )

            elif block.type == "references-heading":
                # 参考文献单开一页
                self._add_page_break()
                self.renderer.render_references_heading(block.title or "参考文献")

            elif block.type == "reference-item":
                # 提取编号（可能为 None，新加文献）
                ref_num = None
                if block.data and "ref_number" in block.data:
                    ref_num = block.data.get("ref_number")
                # 重新计算编号：如果原编号是 None 或与当前序号不一致，重新分配
                # 这是为了确保排版时编号连续递增
                if ref_num is None:
                    # 用前一条的 ref_number + 1，或者 1
                    prev_num = 0
                    for prev in reversed(blocks_seen):
                        if prev.type == "reference-item" and prev.data and prev.data.get("ref_number"):
                            prev_num = prev.data.get("ref_number")
                            break
                    ref_num = prev_num + 1
                    block.data = dict(block.data or {})
                    block.data["ref_number"] = ref_num
                self.renderer.render_reference_item(block.content, ref_number=ref_num)
                blocks_seen.append(block)

        # 保存文档
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, f"{filename}.docx")
        self.doc.save(output_path)
        return output_path

    def _collect_headings(self, blocks: List[Block]) -> List[HeadingEntry]:
        """收集所有标题块（用于目录生成）。

        保留原文中的序号（如 "1. "、"1.1 " 等），
        如果原文没有序号，则根据 level 自动生成。
        也包括 references-heading 类型。
        """
        entries = []
        counters = [0, 0, 0, 0, 0]  # 各级计数器

        for block in blocks:
            block_type = getattr(block, "type", "")
            if block_type == "heading":
                level = getattr(block, "level", 1)
                level = min(max(level, 1), 4)
                title = getattr(block, "title", "") or getattr(block, "content", "")

                # 尝试从 title 中提取序号（如 "1."、"1.1"、"1.1.1"）
                number = ""
                clean_text = title.strip()
                # V7.8: 清除标题中的 LaTeX 格式命令（\textbf{}、\textit{} 等）
                clean_text = re.sub(r'\\textbf\{([^}]*)\}', r'\1', clean_text)
                clean_text = re.sub(r'\\(?:textit|texttt|emph)\{([^}]*)\}', r'\1', clean_text)
                match = re.match(r'^(\d+(?:\.\d+){0,3})\s*[\.\、]?\s*', clean_text)
                if match:
                    number = match.group(1)
                    if not number.endswith('.'):
                        number += '.'
                    clean_text = clean_text[match.end():].strip()
                else:
                    # 自动生成序号
                    counters[level - 1] += 1
                    for i in range(level, len(counters)):
                        counters[i] = 0
                    parts = [str(counters[i]) for i in range(level)]
                    number = '.'.join(parts) + '.'

                entries.append(HeadingEntry(
                    level=level,
                    number=number,
                    text=clean_text,
                ))

            elif block_type == "references-heading":
                # 参考文献：作为 level=1 加入目录
                title = getattr(block, "title", "") or "参考文献"
                # V7.8: 清除 LaTeX 格式命令
                title = re.sub(r'\\textbf\{([^}]*)\}', r'\1', title)
                title = re.sub(r'\\(?:textit|texttt|emph)\{([^}]*)\}', r'\1', title)
                counters[0] += 1
                for i in range(1, len(counters)):
                    counters[i] = 0
                entries.append(HeadingEntry(
                    level=1,
                    number=f"{counters[0]}.",
                    text=title,
                ))

        return entries

    def _render_block_heading(self, block: Block) -> None:
        """渲染 heading block，保留原文序号。"""
        level = getattr(block, "level", 1)
        title = getattr(block, "title", "") or getattr(block, "content", "")
        # 完整渲染（不剥离序号）
        self.renderer.render_heading(title.strip(), level)

    def _add_page_break(self) -> None:
        """插入分页符。"""
        from docx.oxml.ns import qn
        p = self.doc.add_paragraph()
        run = p.add_run()
        # 添加分页符
        br = OxmlElement('w:br')
        br.set(qn('w:type'), 'page')
        run._r.append(br)

    @staticmethod
    def _resolve_image_path(img_obj, output_dir: str) -> Optional[str]:
        """解析图片路径"""
        rel_path = getattr(img_obj, "extracted_path", "")
        if not rel_path:
            return None
        candidates = [
            os.path.join(output_dir, rel_path),
            os.path.join(os.path.dirname(output_dir), rel_path),
            rel_path,
            os.path.abspath(rel_path),
        ]
        for candidate in candidates:
            if os.path.isfile(candidate):
                return candidate
        return None

    def _insert_image_placeholder(self, idx: int) -> None:
        """插入图片占位符"""
        p = self.doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(f"[图片{idx}]")
        run.font.name = self.fmt.body_font or CN_SONG
        run.font.size = Pt(self._pt_value(self.fmt.body_size, 12))
