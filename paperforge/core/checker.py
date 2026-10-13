# -*- coding: utf-8 -*-
r"""
LaTeX 静态检查器。

提供 LaTeX 编译前的静态错误检测，包括：
- 未转义特殊字符检测
- 括号匹配检查
- 环境完整性验证
- 重复标签检查
- 未定义引用检查
"""

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List


class LaTeXErrorType(Enum):
    """LaTeX 错误类型"""
    UNESCAPED_SPECIAL = "unescaped_special"      # 未转义的特殊字符
    UNBALANCED_BRACES = "unbalanced_braces"     # 花括号不匹配
    UNBALANCED_MATH = "unbalanced_math"         # 数学模式不匹配
    EMPTY_COMMAND = "empty_command"              # 空命令
    INVALID_CHARS = "invalid_chars"              # 非法字符
    MISSING_REQUIRED = "missing_required"        # 缺少必需内容
    UNCLOSED_ENV = "unclosed_environment"       # 未闭合环境
    DUPLICATE_LABEL = "duplicate_label"          # 重复标签
    UNDEFINED_REF = "undefined_reference"         # 未定义引用


class DiagnosticSeverity(Enum):
    """诊断严重级别"""
    ERROR = "error"       # 必须修复
    WARNING = "warning"   # 建议修复
    INFO = "info"         # 仅记录


@dataclass
class LaTeXError:
    """检测到的 LaTeX 错误"""
    error_type: LaTeXErrorType
    message: str
    line: int = 0
    severity: DiagnosticSeverity = DiagnosticSeverity.WARNING

    def __str__(self) -> str:
        location = f"行 {self.line}: " if self.line else ""
        return f"[{self.severity.value}] {location}{self.message}"


class LaTeXChecker:
    """
    LaTeX 编译前自查器。

    在编译前检测常见的 LaTeX 错误，减少编译失败次数。
    """

    # LaTeX 特殊字符列表
    SPECIAL_CHARS = ["&", "%", "#", "$", "_", "{", "}"]

    def __init__(self, strict: bool = False):
        """
        初始化检查器。

        Args:
            strict: 是否启用严格模式（将更多问题标记为错误）
        """
        self.strict = strict
        self.errors: List[LaTeXError] = []
        self._comments_stripped_lines: List[str] = []

    def check(self, tex_content: str) -> List[LaTeXError]:
        """
        对 LaTeX 内容进行编译前检查。

        Args:
            tex_content: LaTeX 源文件内容

        Returns:
            List[LaTeXError]: 检测到的错误列表
        """
        self.errors = []
        lines = tex_content.split("\n")

        # 预处理：去除注释行
        self._comments_stripped_lines = [
            self._strip_comment(line) for line in lines
        ]

        # 逐行检查
        for i, line in enumerate(lines, 1):
            self._check_line(line, i)

        # 检查整体结构
        self._check_structure(tex_content)

        # 检查重复标签
        self._check_duplicate_labels(tex_content)

        # 检查未定义引用
        self._check_undefined_refs(tex_content)

        return self.errors

    def _strip_comment(self, line: str) -> str:
        """去除行内注释"""
        # 处理连续的 %（避免 %% 开头的注释被误处理）
        idx = 0
        in_math = False
        result = []
        for i, ch in enumerate(line):
            if ch == "$":
                in_math = not in_math
            if ch == "%" and not in_math:
                break
            result.append(ch)
        return "".join(result)

    def _check_line(self, line: str, line_num: int) -> None:
        """检查单行内容"""
        stripped = self._comments_stripped_lines[line_num - 1]

        # 检查未转义的特殊字符
        self._check_unescaped_chars(stripped, line_num)

        # 检查空命令
        self._check_empty_commands(stripped, line_num)

        # 检查花括号匹配
        self._check_braces_balance(stripped, line_num)

    def _check_unescaped_chars(self, line: str, line_num: int) -> None:
        """检查未转义的特殊字符"""
        for ch in self.SPECIAL_CHARS:
            # 简单检查：未转义的字符（前面不是反斜杠）
            pattern = rf'(?<!\\){re.escape(ch)}'
            matches = list(re.finditer(pattern, line))
            if matches:
                # 统计不在字符串内的匹配
                for match in matches:
                    pos = match.start()
                    # 检查是否在 \verb|...| 或类似环境中
                    if self._is_in_verb(line, pos):
                        continue

                    severity = DiagnosticSeverity.ERROR if self.strict else DiagnosticSeverity.WARNING
                    self.errors.append(LaTeXError(
                        LaTeXErrorType.UNESCAPED_SPECIAL,
                        f"未转义字符 '{ch}'",
                        line_num,
                        severity
                    ))
                    break  # 每行只报告一次

    def _is_in_verb(self, line: str, pos: int) -> bool:
        """检查位置是否在 \\verb 命令内"""
        before = line[:pos]
        # 简单检查：是否有未闭合的 \verb
        verb_matches = list(re.finditer(r'\\verb([^\w])', before))
        if not verb_matches:
            return False
        last_verb = verb_matches[-1]
        delim = last_verb.group(1)
        # 检查 delimiter 之后是否有闭合
        rest = before[last_verb.end():]
        return delim not in rest

    def _check_empty_commands(self, line: str, line_num: int) -> None:
        """检查空命令"""
        if re.search(r'\\text\w*\{\s*\}', line):
            self.errors.append(LaTeXError(
                LaTeXErrorType.EMPTY_COMMAND,
                "检测到空命令",
                line_num,
                DiagnosticSeverity.WARNING
            ))

    def _check_braces_balance(self, line: str, line_num: int) -> None:
        """检查花括号平衡（简化版本）"""
        open_braces = line.count("{") - line.count("\\{")
        close_braces = line.count("}") - line.count("\\}")

        if open_braces < 0:
            self.errors.append(LaTeXError(
                LaTeXErrorType.UNBALANCED_BRACES,
                f"多余右括号 '}}' (差 {abs(open_braces)} 个)",
                line_num,
                DiagnosticSeverity.ERROR if self.strict else DiagnosticSeverity.WARNING
            ))

    def _check_structure(self, content: str) -> None:
        """检查整体结构完整性"""
        # 检查 document 环境
        if "\\begin{document}" not in content:
            self.errors.append(LaTeXError(
                LaTeXErrorType.MISSING_REQUIRED,
                "缺少 \\begin{document}",
                severity=DiagnosticSeverity.ERROR
            ))
        if "\\end{document}" not in content:
            self.errors.append(LaTeXError(
                LaTeXErrorType.MISSING_REQUIRED,
                "缺少 \\end{document}",
                severity=DiagnosticSeverity.ERROR
            ))

        # 检查 thebibliography 环境
        if "\\begin{thebibliography}" in content and "\\end{thebibliography}" not in content:
            self.errors.append(LaTeXError(
                LaTeXErrorType.UNCLOSED_ENV,
                "thebibliography 环境未正确关闭",
                severity=DiagnosticSeverity.ERROR
            ))

        # 检查未闭合的环境
        self._check_unclosed_envs(content)

    def _check_unclosed_envs(self, content: str) -> None:
        """检查未闭合的环境"""
        begin_pattern = re.compile(r"\\begin\{(\w+)\}")
        end_pattern = re.compile(r"\\end\{(\w+)\}")

        begins = begin_pattern.findall(content)
        ends = end_pattern.findall(content)

        from collections import Counter
        begin_counts = Counter(begins)
        end_counts = Counter(ends)

        for env in set(list(begin_counts.keys()) + list(end_counts.keys())):
            diff = begin_counts.get(env, 0) - end_counts.get(env, 0)
            if diff > 0:
                self.errors.append(LaTeXError(
                    LaTeXErrorType.UNCLOSED_ENV,
                    f"未闭合环境: '{env}' (缺少 {diff} 个 \\end{{{env}}})",
                    severity=DiagnosticSeverity.ERROR
                ))
            elif diff < 0:
                self.errors.append(LaTeXError(
                    LaTeXErrorType.UNCLOSED_ENV,
                    f"多余的 \\end{{{env}}} (没有匹配的 \\begin{{{env}}})",
                    severity=DiagnosticSeverity.WARNING
                ))

    def _check_duplicate_labels(self, content: str) -> None:
        """检查重复的 \\label"""
        labels = re.findall(r"\\label\{([^}]+)\}", content)
        from collections import Counter
        label_counts = Counter(labels)

        for label, count in label_counts.items():
            if count > 1:
                self.errors.append(LaTeXError(
                    LaTeXErrorType.DUPLICATE_LABEL,
                    f"重复的 label: '{label}' (出现 {count} 次)",
                    severity=DiagnosticSeverity.WARNING
                ))

    def _check_undefined_refs(self, content: str) -> None:
        """检查未定义的引用"""
        refs = set(re.findall(r"\\(?:ref|eqref|cref|autoref)\{([^}]+)\}", content))
        labels = set(re.findall(r"\\label\{([^}]+)\}", content))

        # 处理多引用
        all_refs = set()
        for r in refs:
            for part in r.split(","):
                all_refs.add(part.strip())

        undefined = all_refs - labels
        for u in sorted(undefined):
            self.errors.append(LaTeXError(
                LaTeXErrorType.UNDEFINED_REF,
                f"未定义的引用: '{u}'",
                severity=DiagnosticSeverity.WARNING
            ))

    def get_summary(self) -> str:
        """获取检查结果摘要"""
        error_count = sum(1 for e in self.errors if e.severity == DiagnosticSeverity.ERROR)
        warning_count = sum(1 for e in self.errors if e.severity == DiagnosticSeverity.WARNING)

        lines = [f"LaTeX 检查结果: {len(self.errors)} 个问题"]
        if error_count > 0:
            lines.append(f"  - {error_count} 个错误")
        if warning_count > 0:
            lines.append(f"  - {warning_count} 个警告")

        if not self.errors:
            lines.append("  ✓ 未检测到问题")

        return "\n".join(lines)

    def has_errors(self) -> bool:
        """是否有严重错误"""
        return any(e.severity == DiagnosticSeverity.ERROR for e in self.errors)

    def has_warnings(self) -> bool:
        """是否有警告"""
        return any(e.severity == DiagnosticSeverity.WARNING for e in self.errors)


class LaTeXStaticChecker:
    """
    静态检查器（便捷方法集合）。

    提供静态方法进行单项检查。
    """

    @staticmethod
    def check_unescaped_chars(content: str) -> List[str]:
        """检查未转义的特殊字符"""
        checker = LaTeXChecker()
        checker._check_unescaped_chars(content, 0)
        return [e.message for e in checker.errors]

    @staticmethod
    def check_unclosed_envs(content: str) -> List[str]:
        """检查未闭合的环境"""
        checker = LaTeXChecker()
        checker._check_unclosed_envs(content)
        return [e.message for e in checker.errors]

    @staticmethod
    def check_duplicate_labels(content: str) -> List[str]:
        """检查重复的 \\label"""
        checker = LaTeXChecker()
        checker._check_duplicate_labels(content)
        return [e.message for e in checker.errors]

    @staticmethod
    def check_undefined_refs(content: str) -> List[str]:
        """检查未定义的引用"""
        checker = LaTeXChecker()
        checker._check_undefined_refs(content)
        return [e.message for e in checker.errors]

    @staticmethod
    def check_all(content: str) -> dict:
        """运行所有静态检查"""
        return {
            "unclosed_envs": LaTeXStaticChecker.check_unclosed_envs(content),
            "duplicate_labels": LaTeXStaticChecker.check_duplicate_labels(content),
            "undefined_refs": LaTeXStaticChecker.check_undefined_refs(content),
            "unescaped_chars": LaTeXStaticChecker.check_unescaped_chars(content),
        }
