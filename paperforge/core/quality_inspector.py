# -*- coding: utf-8 -*-
"""
输出质量检查器 —— 解析编译日志，生成质量报告。

设计原则：
1. 输入编译输出目录，输出 QualityReport（严格类型对齐）
2. 单一职责：仅做质量检查，不涉及模板选择或渲染
3. 所有检查规则配置化，禁止硬编码阈值
"""

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional

from core.types import QualityReport, CompileIssue, IssueSeverity


class QualityInspector:
    """输出质量检查器"""

    def inspect(self, build_dir: str) -> QualityReport:
        """
        检查编译输出质量。

        Args:
            build_dir: 编译输出目录（包含 paper.tex, paper.log, paper.pdf 等）

        Returns:
            QualityReport: 包含 PDF 状态、编译错误、警告等
        """
        issues: List[CompileIssue] = []
        pdf_exists = False
        pdf_pages = 0

        # 1. 检查 PDF 是否存在
        pdf_path = os.path.join(build_dir, "paper.pdf")
        pdf_exists = os.path.exists(pdf_path)

        # 2. 解析日志文件
        log_path = os.path.join(build_dir, "paper.log")
        if os.path.exists(log_path):
            log_issues, pages = self._parse_log(log_path)
            issues.extend(log_issues)
            if pages > 0:
                pdf_pages = pages

        # 3. 综合判断
        success = pdf_exists and len([i for i in issues if i.severity == IssueSeverity.ERROR]) == 0

        return QualityReport(
            success=success,
            pdf_exists=pdf_exists,
            pdf_pages=pdf_pages,
            issues=issues
        )

    def _parse_log(self, log_path: str) -> tuple[List[CompileIssue], int]:
        """
        解析 xelatex 日志文件。

        Returns:
            (issues, pages): 问题列表和页数
        """
        issues: List[CompileIssue] = []
        pages = 0

        try:
            with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                lines = content.split("\n")
        except Exception:
            return issues, pages

        # 1. 提取致命错误（以 ! 开头）
        for i, line in enumerate(lines):
            if line.startswith("!"):
                issues.append(CompileIssue(
                    severity=IssueSeverity.ERROR,
                    category="fatal_error",
                    message=line[1:].strip(),
                    location=f"line {i+1}"
                ))

        # 2. 提取字体缺失警告
        font_missing_pattern = re.compile(r"Font shape `([^']+)' undefined", re.IGNORECASE)
        for match in font_missing_pattern.finditer(content):
            issues.append(CompileIssue(
                severity=IssueSeverity.WARNING,
                category="font_missing",
                message=f"字体缺失: {match.group(1)}",
                location=""
            ))

        # 3. 提取字符缺失警告
        char_missing_pattern = re.compile(r"Missing character: There is no ([^\s]+) in font", re.IGNORECASE)
        char_counts: dict[str, int] = {}
        for match in char_missing_pattern.finditer(content):
            char = match.group(1)
            char_counts[char] = char_counts.get(char, 0) + 1

        for char, count in char_counts.items():
            issues.append(CompileIssue(
                severity=IssueSeverity.INFO,
                category="char_missing",
                message=f"字符缺失: {char} ({count} 次)",
                location=""
            ))

        # 4. 提取 overfull/underfull 警告（仅记录，不影响质量判断）
        overfull_count = len(re.findall(r"Overfull \\hbox", content))
        underfull_count = len(re.findall(r"Underfull \\hbox", content))
        if overfull_count > 0:
            issues.append(CompileIssue(
                severity=IssueSeverity.INFO,
                category="layout",
                message=f"Overfull hbox: {overfull_count} 处",
                location=""
            ))
        if underfull_count > 0:
            issues.append(CompileIssue(
                severity=IssueSeverity.INFO,
                category="layout",
                message=f"Underfull hbox: {underfull_count} 处",
                location=""
            ))

        # 5. 提取页数
        pages_match = re.search(r"Output written on .+\.pdf \((\d+) pages", content)
        if pages_match:
            pages = int(pages_match.group(1))

        return issues, pages

    def generate_report_text(self, report: QualityReport) -> str:
        """生成人类可读的报告文本"""
        lines = [
            "=" * 60,
            "质量检查报告",
            "=" * 60,
            f"PDF 状态: {'✓ 已生成' if report.pdf_exists else '✗ 未生成'}",
            f"页数: {report.pdf_pages}",
            f"整体状态: {'✓ 通过' if report.success else '✗ 失败'}",
            "",
        ]

        if report.errors:
            lines.append(f"错误 ({len(report.errors)} 个):")
            for issue in report.errors:
                lines.append(f"  - [{issue.category}] {issue.message}")
            lines.append("")

        if report.warnings:
            lines.append(f"警告 ({len(report.warnings)} 个):")
            for issue in report.warnings:
                lines.append(f"  - [{issue.category}] {issue.message}")
            lines.append("")

        info_issues = [i for i in report.issues if i.severity == IssueSeverity.INFO]
        if info_issues:
            lines.append(f"提示 ({len(info_issues)} 个):")
            for issue in info_issues[:5]:  # 只显示前 5 个
                lines.append(f"  - [{issue.category}] {issue.message}")
            if len(info_issues) > 5:
                lines.append(f"  ... 还有 {len(info_issues) - 5} 个")
            lines.append("")

        lines.append("=" * 60)
        return "\n".join(lines)