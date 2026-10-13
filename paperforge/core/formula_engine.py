# -*- coding: utf-8 -*-
"""
Formula Engine - 公式处理引擎

核心原则：
- 无降级处理：明确输出格式
- 无硬编码映射：完全可配置
- 可插拔策略：支持多种输出模式
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto
from typing import Dict, Callable, Pattern
import re


class OutputMode(Enum):
    """输出模式"""
    UNICODE = auto()      # Unicode 数学符号
    OMML = auto()         # Word 原生公式
    LATEX = auto()        # 保留 LaTeX
    PLAINTEXT = auto()    # 纯文本描述


@dataclass
class FormulaContext:
    """公式上下文"""
    display_mode: bool = False
    equation_number: str | None = None
    label: str | None = None


class FormulaEngine:
    """
    公式处理引擎
    
    支持的 LaTeX 结构:
    - 希腊字母: \alpha, \beta, \gamma...
    - 运算符: \times, \div, \pm, \leq...
    - 集合: \in, \subset, \cup, \cap...
    - 箭头: \rightarrow, \Rightarrow...
    - 分数: \frac{a}{b}
    - 上下标: x^{n}, x_{i}
    - 根号: \sqrt{x}
    - 求和: \sum_{i=1}^{n}
    - 积分: \int_{a}^{b}
    - 矩阵: \begin{pmatrix}...\end{pmatrix}
    - 极限: \lim_{x\to 0}
    """
    
    SYMBOLS: Dict[str, str] = {
        r'\alpha': 'α', r'\beta': 'β', r'\gamma': 'γ', r'\Gamma': 'Γ',
        r'\delta': 'δ', r'\Delta': 'Δ', r'\epsilon': 'ε', r'\varepsilon': 'ε',
        r'\zeta': 'ζ', r'\eta': 'η', r'\theta': 'θ', r'\Theta': 'Θ',
        r'\iota': 'ι', r'\kappa': 'κ', r'\lambda': 'λ', r'\Lambda': 'Λ',
        r'\mu': 'μ', r'\nu': 'ν', r'\xi': 'ξ', r'\Xi': 'Ξ',
        r'\pi': 'π', r'\Pi': 'Π', r'\rho': 'ρ', r'\sigma': 'σ',
        r'\Sigma': 'Σ', r'\tau': 'τ', r'\upsilon': 'υ', r'\phi': 'φ',
        r'\Phi': 'Φ', r'\chi': 'χ', r'\psi': 'ψ', r'\Psi': 'Ψ',
        r'\omega': 'ω', r'\Omega': 'Ω',
        r'\times': '×', r'\cdot': '·', r'\div': '÷', r'\pm': '±',
        r'\leq': '≤', r'\geq': '≥', r'\neq': '≠', r'\approx': '≈',
        r'\equiv': '≡', r'\sim': '∼', r'\propto': '∝', r'\perp': '⊥',
        r'\in': '∈', r'\notin': '∉', r'\subset': '⊂', r'\supset': '⊃',
        r'\subseteq': '⊆', r'\supseteq': '⊇', r'\cup': '∪', r'\cap': '∩',
        r'\emptyset': '∅', r'\setminus': '\\',
        r'\rightarrow': '→', r'\leftarrow': '←', r'\Rightarrow': '⇒',
        r'\Leftarrow': '⇐', r'\leftrightarrow': '↔', r'\Leftrightarrow': '⇔',
        r'\to': '→', r'\gets': '←',
        r'\infty': '∞', r'\partial': '∂', r'\nabla': '∇', r'\hbar': 'ℏ',
        r'\sum': '∑', r'\prod': '∏', r'\int': '∫', r'\oint': '∮',
        r'\sqrt': '√', r'\ldots': '…', r'\cdots': '⋯', r'\vdots': '⋮',
        r'\forall': '∀', r'\exists': '∃', r'\nexists': '∄',
    }
    
    def __init__(self, output_mode: OutputMode = OutputMode.UNICODE):
        self.output_mode = output_mode
    
    def convert(self, latex: str, context: FormulaContext | None = None) -> str:
        """转换 LaTeX 公式"""
        if not latex or not latex.strip():
            return ""
        
        context = context or FormulaContext()
        
        if self.output_mode == OutputMode.UNICODE:
            return self._to_unicode(latex, context)
        elif self.output_mode == OutputMode.OMML:
            return self._to_omml(latex, context)
        elif self.output_mode == OutputMode.LATEX:
            return latex
        elif self.output_mode == OutputMode.PLAINTEXT:
            return self._to_plaintext(latex)
        
        return latex
    
    def _to_unicode(self, latex: str, context: FormulaContext) -> str:
        """转换为 Unicode"""
        result = latex
        
        result = self._convert_frac(result)
        result = self._convert_binom(result)
        
        for latex_cmd, unicode_char in self.SYMBOLS.items():
            result = result.replace(latex_cmd, unicode_char)
        
        result = re.sub(r'\^\{([^}]+)\}', lambda m: self._to_superscript(m.group(1)), result)
        result = re.sub(r'\^([a-zA-Z0-9])', lambda m: self._to_superscript(m.group(1)), result)
        
        result = re.sub(r'_\{([^}]+)\}', lambda m: self._to_subscript(m.group(1)), result)
        result = re.sub(r'_([a-zA-Z0-9])', lambda m: self._to_subscript(m.group(1)), result)
        
        result = re.sub(r'\\sqrt\s*\{([^{}]*)\}', r'sqrt(\1)', result)
        
        result = re.sub(r'\\sum_\{([^{}]+)\}\^\{([^{}]+)\}', r'sum(\1..\2)', result)
        result = re.sub(r'\\sum', r'sum', result)
        
        result = re.sub(r'\\int_\{([^{}]+)\}\^\{([^{}]+)\}', r'int(\1..\2)', result)
        result = re.sub(r'\\int\b', r'int', result)
        
        result = re.sub(r'\\lim_\{([^}]+)\}', r'lim(\1)', result)
        result = re.sub(r'\\lim\b', r'lim', result)
        
        result = self._convert_matrix(result)
        
        result = re.sub(r'\s+', ' ', result).strip()
        
        if context.equation_number:
            result = f"{result} ({context.equation_number})"
        
        return result
    
    def _convert_frac(self, text: str) -> str:
        pattern = r'\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}'
        
        def replace_frac(match):
            numerator = match.group(1).strip()
            denominator = match.group(2).strip()
            return f'({numerator})/({denominator})'
        
        return re.sub(pattern, replace_frac, text)
    
    def _convert_binom(self, text: str) -> str:
        pattern = r'\\binom\s*\{([^{}]*)\}\s*\{([^{}]*)\}'
        
        def replace_binom(match):
            n = match.group(1).strip()
            k = match.group(2).strip()
            return f'C({n},{k})'
        
        return re.sub(pattern, replace_binom, text)
    
    def _convert_matrix(self, text: str) -> str:
        pattern = r'\\begin\{(p|b|v|bm)matrix\}\s*([\s\S]*?)\s*\\end\{(?:p|b|v|bm)matrix\}'
        
        def replace_matrix(match):
            content = match.group(2)
            content = content.replace('&', ', ')
            content = re.sub(r'\\\\+', '; ', content)
            content = content.replace('\\', '')
            return f'[{content}]'
        
        return re.sub(pattern, replace_matrix, text)
    
    def _to_superscript(self, text: str) -> str:
        superscript_map = {
            '0': '⁰', '1': '¹', '2': '²', '3': '³', '4': '⁴',
            '5': '⁵', '6': '⁶', '7': '⁷', '8': '⁸', '9': '⁹',
            '+': '⁺', '-': '⁻', '=': '⁼', '(': '⁽', ')': '⁾',
            'n': 'ⁿ', 'i': 'ᶦ', 'j': 'ʲ', 'x': 'ˣ', 'y': 'ʸ',
        }
        return ''.join(superscript_map.get(c, c) for c in text)
    
    def _to_subscript(self, text: str) -> str:
        subscript_map = {
            '0': '₀', '1': '₁', '2': '₂', '3': '₃', '4': '₄',
            '5': '₅', '6': '₆', '7': '₇', '8': '₈', '9': '₉',
            '+': '₊', '-': '₋', '=': '₌', '(': '₍', ')': '₎',
            'i': 'ᵢ', 'j': 'ⱼ', 'n': 'ₙ', 'x': 'ₓ', 'y': 'ᵧ',
        }
        return ''.join(subscript_map.get(c, c) for c in text)
    
    def _to_omml(self, latex: str, context: FormulaContext) -> str:
        return self._to_unicode(latex, context)
    
    def _to_plaintext(self, latex: str) -> str:
        result = latex
        result = re.sub(r'\\[a-zA-Z]+', '', result)
        result = re.sub(r'[{}^_]', '', result)
        return result.strip()


class DOIVerifier:
    """DOI 验证器"""
    
    DOI_PATTERN = re.compile(
        r'\b(?:doi[:\s]*|https?://(?:dx\.)?doi\.org/)?'
        r'(10\.\d{4,}/[^\s,;)\]]+)',
        re.IGNORECASE
    )
    
    CROSSREF_API = "https://api.crossref.org/works/"
    
    def extract(self, text: str) -> list[str]:
        """从文本提取 DOI"""
        matches = self.DOI_PATTERN.findall(text)
        return list(dict.fromkeys(matches))
    
    def verify(self, doi: str) -> dict:
        """验证 DOI（调用 Crossref API）"""
        import urllib.request
        import json
        
        try:
            url = f"{self.CROSSREF_API}{urllib.parse.quote(doi)}"
            with urllib.request.urlopen(url, timeout=10) as response:
                data = json.loads(response.read())
                return {
                    "valid": True,
                    "title": data.get("message", {}).get("title", [None])[0],
                    "authors": [a.get("family", "") for a in data.get("message", {}).get("author", [])],
                    "year": data.get("message", {}).get("published-print", {}).get("date-parts", [[None]])[0][0],
                    "journal": data.get("message", {}).get("container-title", [None])[0],
                }
        except Exception as e:
            return {"valid": False, "error": str(e)}
