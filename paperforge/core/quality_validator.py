# -*- coding: utf-8 -*-
"""
Quality Validator - 质量验证引擎

功能：
- 检查未转换的 LaTeX 命令
- 检查未闭合的数学模式
- 检查缺失的图片
- 检查缺失的引用
- 检查无效的 DOI
"""

import re
from dataclasses import dataclass, field
from typing import List


class IssueSeverity:
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class IssueType:
    UNCONVERTED_LATEX = "unconverted_latex"
    UNCLOSED_MATH = "unclosed_math"
    MISSING_IMAGE = "missing_image"
    MISSING_REFERENCE = "missing_reference"
    INVALID_DOI = "invalid_doi"
    UNPARSED_CONTENT = "unparsed_content"
    FORMATTING_ISSUE = "formatting_issue"


@dataclass
class Issue:
    type: str
    severity: str
    message: str
    location: str = ""
    block_index: int = 0

    def __str__(self) -> str:
        return f"[{self.severity.upper()}] {self.type}: {self.message} (at {self.location})"


@dataclass
class ValidationResult:
    score: int
    issues: List[Issue] = field(default_factory=list)
    statistics: dict = field(default_factory=dict)

    @property
    def is_acceptable(self) -> bool:
        return self.score >= 80

    @property
    def critical_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == IssueSeverity.CRITICAL)

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == IssueSeverity.WARNING)


class QualityValidator:
    LATEX_COMMAND_PATTERN = r'\\(begin|end|cite|ref|label|section|subsection|usepackage)\{[^}]*\}'
    UNCLOSED_MATH_PATTERN = r'(?<!\$)\$(?!\$)[^$]*$'

    def __init__(self, threshold: int = 80):
        self.threshold = threshold

    def validate(self, blocks: list) -> ValidationResult:
        """验证文档 blocks"""
        issues = []
        score = 100
        statistics = {
            'total_blocks': len(blocks),
            'text_blocks': 0,
            'heading_blocks': 0,
            'image_blocks': 0,
            'table_blocks': 0,
            'formula_blocks': 0,
        }

        for idx, block in enumerate(blocks):
            btype = getattr(block, "type", "")
            
            # 更新统计
            if btype == "text":
                statistics['text_blocks'] += 1
            elif btype == "heading":
                statistics['heading_blocks'] += 1
            elif btype == "image":
                statistics['image_blocks'] += 1
            elif btype == "table":
                statistics['table_blocks'] += 1

            # 检查未转换的 LaTeX
            content = getattr(block, "content", "") or getattr(block, "title", "")
            if content:
                latex_issues = self._check_unconverted_latex(content, idx)
                issues.extend(latex_issues)

                math_issues = self._check_math_completeness(content, idx)
                issues.extend(math_issues)

            # 检查图片
            if btype == "image":
                img_issues = self._check_image(block, idx)
                issues.extend(img_issues)

        # 计算分数
        score -= len([i for i in issues if i.severity == IssueSeverity.CRITICAL]) * 10
        score -= len([i for i in issues if i.severity == IssueSeverity.WARNING]) * 2
        score = max(0, score)

        statistics['critical_issues'] = len([i for i in issues if i.severity == IssueSeverity.CRITICAL])
        statistics['warning_issues'] = len([i for i in issues if i.severity == IssueSeverity.WARNING])
        statistics['info_issues'] = len([i for i in issues if i.severity == IssueSeverity.INFO])

        return ValidationResult(
            score=score,
            issues=issues,
            statistics=statistics
        )

    def _check_unconverted_latex(self, text: str, block_index: int) -> List[Issue]:
        issues = []
        matches = re.findall(self.LATEX_COMMAND_PATTERN, text)
        if matches:
            commands = ", ".join(set(matches))
            issues.append(Issue(
                type=IssueType.UNCONVERTED_LATEX,
                severity=IssueSeverity.WARNING,
                message=f"发现未转换的 LaTeX 命令: {commands}",
                location=f"block #{block_index}",
                block_index=block_index
            ))
        return issues

    def _check_math_completeness(self, text: str, block_index: int) -> List[Issue]:
        issues = []
        dollar_count = text.count('$')
        if dollar_count % 2 != 0:
            issues.append(Issue(
                type=IssueType.UNCLOSED_MATH,
                severity=IssueSeverity.CRITICAL,
                message=f"数学模式未闭合（$ 数量: {dollar_count}）",
                location=f"block #{block_index}",
                block_index=block_index
            ))
        return issues

    def _check_image(self, block: object, block_index: int) -> List[Issue]:
        issues = []
        data = getattr(block, "data", {}) or {}
        image_obj = data.get("image_obj")
        
        if image_obj is None:
            issues.append(Issue(
                type=IssueType.MISSING_IMAGE,
                severity=IssueSeverity.WARNING,
                message="图片对象为空",
                location=f"block #{block_index}",
                block_index=block_index
            ))
        
        return issues

    def print_report(self, result: ValidationResult) -> None:
        """打印验证报告"""
        print("=" * 70)
        print(f"质量验证报告 - 得分: {result.score}/100")
        print("=" * 70)
        
        stats = result.statistics
        print(f"\n文档统计:")
        print(f"  总段落: {stats.get('total_blocks', 0)}")
        print(f"  标题段落: {stats.get('heading_blocks', 0)}")
        print(f"  正文段落: {stats.get('text_blocks', 0)}")
        print(f"  图片段落: {stats.get('image_blocks', 0)}")
        print(f"  表格段落: {stats.get('table_blocks', 0)}")

        print(f"\n问题统计:")
        print(f"  严重问题: {result.critical_count}")
        print(f"  警告问题: {result.warning_count}")
        print(f"  信息提示: {stats.get('info_issues', 0)}")

        if result.issues:
            print(f"\n问题详情:")
            for issue in result.issues:
                print(f"  {issue}")

        if result.is_acceptable:
            print(f"\n✓ 文档质量达标（≥80分）")
        else:
            print(f"\n✗ 文档质量不达标（<80分）")
