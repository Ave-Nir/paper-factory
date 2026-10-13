# -*- coding: utf-8 -*-
r"""
LaTeX 编译重试器。

提供带自动修复功能的编译重试机制，包括：
- Overfull/Underfull hbox 自动修复
- 编码问题处理
- 非法字符清理
- 字体问题处理
"""

import os
import re
import subprocess
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from .utils.miktex import MikTeXResolver


@dataclass
class CompileResult:
    """编译结果"""
    success: bool
    pdf_path: str = ""
    log_content: str = ""
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    attempts: int = 0


class CompilationError(Exception):
    """编译异常"""
    def __init__(self, message: str, errors: List[str] = None):
        super().__init__(message)
        self.errors = errors or []


class CompilationRetryer:
    """
    编译重试器，带自动修复功能。

    当编译失败时，自动识别错误类型并尝试修复。
    """

    def __init__(self, max_attempts: int = 3, miktex_path: str = None, timeout: int = 120):
        """
        初始化重试器。

        Args:
            max_attempts: 最大尝试次数
            miktex_path: MiKTeX 安装路径
            timeout: 单次编译超时时间（秒）
        """
        self.max_attempts = max_attempts
        self.timeout = timeout
        self.miktex_resolver = MikTeXResolver(custom_path=miktex_path)
        self._error_fixers: Dict[str, Callable[[str], Tuple[str, bool]]] = {}
        self._register_default_fixers()

    def _register_default_fixers(self) -> None:
        """注册默认的错误修复器"""
        # Overfull hbox - 通常是表格/长单词问题
        self._error_fixers[r"Overfull"] = self._fix_overfull_hbox
        # Underfull hbox - 通常是断行问题
        self._error_fixers[r"Underfull"] = self._fix_underfull_hbox
        # Missing font - 字体问题
        self._error_fixers[r"Font.*not found"] = self._fix_missing_font
        # Encoding issues
        self._error_fixers[r"Unicode"] = self._fix_encoding
        # Missing \end{citation}
        self._error_fixers[r"Illegal"] = self._fix_illegal_char

    def compile_with_retry(
        self,
        tex_path: str,
        engine: str = "xelatex",
    ) -> CompileResult:
        """
        带重试的编译。

        Args:
            tex_path: .tex 文件路径
            engine: LaTeX 引擎（xelatex/pdflatex）

        Returns:
            CompileResult: 编译结果
        """
        result = CompileResult(success=False, attempts=0)
        config = self.miktex_resolver.resolve(engine)

        for attempt in range(1, self.max_attempts + 1):
            result.attempts = attempt

            # 执行编译
            success, log = self._run_compilation(tex_path, config)
            result.log_content = log
            result.errors = self._extract_errors(log)
            result.warnings = self._extract_warnings(log)

            # 检查是否成功
            pdf_path = tex_path.replace(".tex", ".pdf")
            if success and os.path.exists(pdf_path):
                result.success = True
                result.pdf_path = pdf_path
                return result

            # 如果失败，尝试自动修复
            if attempt < self.max_attempts:
                fixed = self._try_fix_errors(tex_path, result.errors, log)
                if not fixed:
                    break  # 无法自动修复，退出重试

        return result

    def _run_compilation(
        self,
        tex_path: str,
        config,
    ) -> Tuple[bool, str]:
        """
        执行单次编译。

        Args:
            tex_path: .tex 文件路径
            config: MikTeXConfig 配置对象

        Returns:
            Tuple[bool, str]: (是否成功, 日志内容)
        """
        tex_dir = os.path.dirname(tex_path) or "."

        cmd = [config.engine_path, "-interaction=nonstopmode", os.path.basename(tex_path)]
        env = self.miktex_resolver.get_env(config)

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                cwd=tex_dir,
                env=env,
                timeout=self.timeout,
            )
            return result.returncode == 0, result.stdout + "\n" + result.stderr

        except subprocess.TimeoutExpired:
            return False, f"编译超时 ({self.timeout}秒)"

        except FileNotFoundError:
            return False, f"找不到 LaTeX 引擎: {config.engine_path}"

        except Exception as e:
            return False, f"编译异常: {e}"

    def _extract_errors(self, log: str) -> List[str]:
        """从日志中提取错误"""
        errors = []
        for line in log.split("\n"):
            if line.startswith("!") or "Error" in line or "error" in line:
                # 清理 ANSI 颜色代码
                clean_line = self._strip_ansi(line.strip())
                if clean_line:
                    errors.append(clean_line)
        return errors[:20]  # 限制数量

    def _extract_warnings(self, log: str) -> List[str]:
        """从日志中提取警告"""
        warnings = []
        for line in log.split("\n"):
            if "Warning" in line or "warning" in line:
                clean_line = self._strip_ansi(line.strip())
                if clean_line:
                    warnings.append(clean_line)
        return warnings[:20]

    def _strip_ansi(self, text: str) -> str:
        """去除 ANSI 颜色代码"""
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        return ansi_escape.sub('', text)

    def _try_fix_errors(self, tex_path: str, errors: List[str], log: str) -> bool:
        """
        尝试自动修复错误。

        Args:
            tex_path: .tex 文件路径
            errors: 错误列表
            log: 编译日志

        Returns:
            bool: 是否成功修复
        """
        try:
            with open(tex_path, "r", encoding="utf-8") as f:
                content = f.read()
        except IOError:
            return False

        original = content
        fixed = False

        for error in errors:
            for pattern, fixer in self._error_fixers.items():
                if re.search(pattern, error, re.IGNORECASE):
                    content, was_fixed = fixer(content)
                    if was_fixed:
                        fixed = True

        if fixed:
            try:
                with open(tex_path, "w", encoding="utf-8") as f:
                    f.write(content)
                return True
            except IOError:
                pass

        return False

    def _fix_overfull_hbox(self, content: str) -> Tuple[str, bool]:
        """修复 Overfull hbox 问题"""
        if "\\usepackage{hyphenat}" not in content:
            content = content.replace(
                "\\begin{document}",
                "\\usepackage{hyphenat}\\n\\begin{document}"
            )
            return content, True

        # 如果已经有 hyphenat，尝试调整断行设置
        if "\\tolerance" not in content:
            content = content.replace(
                "\\begin{document}",
                "\\tolerance=1414\\n\\begin{document}"
            )
            return content, True

        return content, False

    def _fix_underfull_hbox(self, content: str) -> Tuple[str, bool]:
        """修复 Underfull hbox 问题"""
        if "\\raggedbottom" not in content:
            content = content.replace(
                "\\begin{document}",
                "\\raggedbottom\\n\\begin{document}"
            )
            return content, True

        if "\\vfuzz" not in content:
            content = content.replace(
                "\\begin{document}",
                "\\vfuzz=30pt\\n\\begin{document}"
            )
            return content, True

        return content, False

    def _fix_missing_font(self, content: str) -> Tuple[str, bool]:
        """修复缺失字体问题"""
        # 确保使用标准字体族
        if "\\usepackage{fontspec}" in content:
            # 检查是否设置了备用字体
            if "\\IfFontExistsTF" not in content:
                # 添加字体备用方案
                pass  # 字体问题通常需要更具体的处理

        return content, False

    def _fix_encoding(self, content: str) -> Tuple[str, bool]:
        """修复编码问题"""
        if "\\usepackage[UTF8]{ctex}" not in content:
            if "\\usepackage{ctex}" in content:
                content = content.replace(
                    "\\usepackage{ctex}",
                    "\\usepackage[UTF8]{ctex}"
                )
                return content, True
            elif "\\begin{document}" in content:
                content = content.replace(
                    "\\begin{document}",
                    "\\usepackage[UTF8]{ctex}\\n\\begin{document}"
                )
                return content, True

        return content, False

    def _fix_illegal_char(self, content: str) -> Tuple[str, bool]:
        """修复非法字符问题"""
        illegal_chars = [
            ("\u2018", "'"),   # 左单引号
            ("\u2019", "'"),   # 右单引号
            ("\u201c", '"'),   # 左双引号
            ("\u201d", '"'),   # 右双引号
            ("\u2014", "--"),  # 长破折号
            ("\u2013", "-"),   # 短破折号
            ("\u00a0", " "),   # 不间断空格
            ("\u00b2", "$^2$"),  # 上标2
            ("\u00b3", "$^3$"),  # 上标3
        ]

        fixed = False
        for illegal, replacement in illegal_chars:
            if illegal in content:
                content = content.replace(illegal, replacement)
                fixed = True

        return content, fixed

    def register_fixer(self, pattern: str, fixer: Callable[[str], Tuple[str, bool]]) -> None:
        """
        注册自定义错误修复器。

        Args:
            pattern: 错误模式（正则表达式）
            fixer: 修复函数，接收 tex 内容，返回 (修复后内容, 是否修复)
        """
        self._error_fixers[pattern] = fixer


def compile_with_retry(
    tex_path: str,
    engine: str = "xelatex",
    max_attempts: int = 3,
    miktex_path: str = None,
    timeout: int = 120,
) -> CompileResult:
    """
    便捷函数：带重试的编译。

    Args:
        tex_path: .tex 文件路径
        engine: LaTeX 引擎
        max_attempts: 最大尝试次数
        miktex_path: MiKTeX 路径
        timeout: 超时时间

    Returns:
        CompileResult: 编译结果
    """
    retryer = CompilationRetryer(
        max_attempts=max_attempts,
        miktex_path=miktex_path,
        timeout=timeout,
    )
    return retryer.compile_with_retry(tex_path, engine)
