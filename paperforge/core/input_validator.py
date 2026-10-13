# -*- coding: utf-8 -*-
"""
入口检测模块 —— 文档读取后、排版前的质量校验。

检测内容：
- 结构完整性：标题层级、章节结构、摘要/参考文献存在性
- 引用完整性：图片引用、表格引用、参考文献引用
- 图片质量：格式、可读性、分辨率、尺寸
- 表格质量：结构完整性、内容合理性
- 文本质量：空文档、乱码、特殊字符

设计原则：
1. 检测即报告，不中断流程（致命错误除外）
2. 报告同时输出到终端和 JSON 文件
3. 重点检测：引用完整性、结构完整性
"""

import os
import re
import json
from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any
from enum import Enum

from core.types import DocumentContent, DocxImage, DocxTable, Block


class InputIssueSeverity(Enum):
    FATAL = "fatal"       # 致命错误，终止排版
    ERROR = "error"       # 严重错误，可能导致排版失败
    WARNING = "warning"   # 警告，建议修复
    INFO = "info"         # 信息，仅记录


@dataclass
class InputIssue:
    """单条检测问题"""
    severity: InputIssueSeverity
    category: str          # 检测类别：structure / reference / image / table / text
    sub_category: str      # 子类别
    message: str
    location: str = ""     # 位置描述
    suggestion: str = ""   # 修复建议


@dataclass
class InputValidationReport:
    """入口检测总报告"""
    source_file: str = ""
    total_blocks: int = 0
    total_images: int = 0
    total_tables: int = 0

    issues: List[InputIssue] = field(default_factory=list)

    @property
    def fatal_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == InputIssueSeverity.FATAL)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == InputIssueSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == InputIssueSeverity.WARNING)

    @property
    def info_count(self) -> int:
        return sum(1 for i in self.issues if i.severity == InputIssueSeverity.INFO)

    @property
    def can_proceed(self) -> bool:
        """是否可以继续排版（无致命错误）"""
        return self.fatal_count == 0

    def to_dict(self) -> Dict[str, Any]:
        """转为可序列化的字典"""
        return {
            "source_file": self.source_file,
            "statistics": {
                "total_blocks": self.total_blocks,
                "total_images": self.total_images,
                "total_tables": self.total_tables,
            },
            "summary": {
                "fatal": self.fatal_count,
                "error": self.error_count,
                "warning": self.warning_count,
                "info": self.info_count,
                "can_proceed": self.can_proceed,
            },
            "issues": [
                {
                    "severity": i.severity.value,
                    "category": i.category,
                    "sub_category": i.sub_category,
                    "message": i.message,
                    "location": i.location,
                    "suggestion": i.suggestion,
                }
                for i in self.issues
            ],
        }

    def save_json(self, output_path: str) -> None:
        """保存为 JSON 文件"""
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    def print_summary(self) -> None:
        """打印终端摘要"""
        _print = print
        _print(f"  文档: {self.source_file}")
        _print(f"  Blocks: {self.total_blocks} | 图片: {self.total_images} | 表格: {self.total_tables}")
        _print(f"  检测结果: "
               f"致命={self.fatal_count}, "
               f"错误={self.error_count}, "
               f"警告={self.warning_count}, "
               f"信息={self.info_count}")

        if self.fatal_count > 0:
            _print("  状态: FAIL（致命错误，终止排版）")
        elif self.error_count > 0:
            _print("  状态: WARN（有错误，继续排版但可能失败）")
        elif self.warning_count > 0:
            _print("  状态: PASS（有警告，可继续排版）")
        else:
            _print("  状态: PASS（全部通过）")

        # 打印前 5 条最严重问题
        serious = [i for i in self.issues
                   if i.severity in (InputIssueSeverity.FATAL, InputIssueSeverity.ERROR)]
        if serious:
            _print("  严重问题:")
            for issue in serious[:5]:
                _print(f"    [{issue.severity.value.upper()}] {issue.category}.{issue.sub_category}: {issue.message}")
                if issue.suggestion:
                    _print(f"      建议: {issue.suggestion}")


class InputValidator:
    """入口检测执行器"""

    def __init__(self, images_dir: Optional[str] = None):
        """
        Args:
            images_dir: 图片提取目录，用于图片质量检测
        """
        self.images_dir = images_dir
        self.report = InputValidationReport()

    def validate(self, doc: DocumentContent, images_dir: Optional[str] = None) -> InputValidationReport:
        """
        执行完整入口检测。

        Args:
            doc: 文档内容
            images_dir: 图片目录（优先使用此参数，其次使用构造时传入的）

        Returns:
            InputValidationReport
        """
        img_dir = images_dir or self.images_dir
        self.report = InputValidationReport(
            source_file=doc.source_file,
            total_blocks=len(doc.blocks),
            total_images=len(doc.images),
            total_tables=len(doc.tables),
        )

        # 1. 空文档检测（最优先）
        self._check_empty_doc(doc)
        if not self.report.can_proceed:
            return self.report

        # 2. 结构完整性检测（重点）
        self._check_structure(doc)

        # 3. 引用完整性检测（重点）
        self._check_references(doc)

        # 4. 图片质量检测
        self._check_images(doc, img_dir)

        # 5. 表格质量检测
        self._check_tables(doc)

        # 6. 文本质量检测
        self._check_text_quality(doc)

        return self.report

    # ========================================================================
    # 1. 空文档检测
    # ========================================================================
    def _check_empty_doc(self, doc: DocumentContent) -> None:
        if len(doc.blocks) == 0:
            self.report.issues.append(InputIssue(
                severity=InputIssueSeverity.FATAL,
                category="structure",
                sub_category="empty_document",
                message="文档为空，无任何内容块",
                suggestion="请检查输入文件是否正确，或文件是否损坏",
            ))
            return

        text_blocks = [b for b in doc.blocks if b.type in ("text", "paragraph") and b.content.strip()]
        if not text_blocks:
            self.report.issues.append(InputIssue(
                severity=InputIssueSeverity.FATAL,
                category="structure",
                sub_category="no_text_content",
                message="文档无正文内容",
                suggestion="请检查文档是否包含正文文本",
            ))

    # ========================================================================
    # 2. 结构完整性检测（重点）
    # ========================================================================
    def _check_structure(self, doc: DocumentContent) -> None:
        issues = self.report.issues

        # 2.1 标题层级检测
        headings = [b for b in doc.blocks if b.type == "heading"]
        if not headings:
            issues.append(InputIssue(
                severity=InputIssueSeverity.WARNING,
                category="structure",
                sub_category="no_headings",
                message="未检测到任何标题，文档结构可能不完整",
                suggestion="建议添加章节标题以改善排版效果",
            ))
        else:
            # 一级标题检测
            h1 = [h for h in headings if h.level == 1]
            if not h1:
                issues.append(InputIssue(
                    severity=InputIssueSeverity.WARNING,
                    category="structure",
                    sub_category="no_level1_heading",
                    message="未检测到一级标题",
                    suggestion="建议添加一级标题（如 '一、XXX' 或 '第一章 XXX'）",
                ))
            elif len(h1) < 2:
                issues.append(InputIssue(
                    severity=InputIssueSeverity.INFO,
                    category="structure",
                    sub_category="few_level1_headings",
                    message=f"仅检测到 {len(h1)} 个一级标题，结构可能较简单",
                ))

            # 标题层级跳跃检测（如直接从 h1 跳到 h3）
            levels = sorted(set(h.level for h in headings))
            for i in range(len(levels) - 1):
                if levels[i + 1] - levels[i] > 1:
                    issues.append(InputIssue(
                        severity=InputIssueSeverity.WARNING,
                        category="structure",
                        sub_category="heading_level_jump",
                        message=f"标题层级跳跃：从 level{levels[i]} 直接到 level{levels[i+1]}",
                        suggestion="建议标题层级逐级递增，避免越级",
                    ))
                    break

        # 2.2 摘要存在性检测
        has_abstract = any(b.type in ("abstract", "abstract-en") for b in doc.blocks)
        if not has_abstract:
            # 尝试在内容中找"摘要"关键词
            abstract_text_found = any(
                b.type in ("text", "paragraph") and re.search(r"^\s*摘\s*要", b.content)
                for b in doc.blocks
            )
            if abstract_text_found:
                issues.append(InputIssue(
                    severity=InputIssueSeverity.INFO,
                    category="structure",
                    sub_category="abstract_not_detected",
                    message="检测到'摘要'文本但未被识别为摘要块",
                    suggestion="可能是摘要格式不标准，建议检查摘要标题格式",
                ))
            else:
                issues.append(InputIssue(
                    severity=InputIssueSeverity.WARNING,
                    category="structure",
                    sub_category="no_abstract",
                    message="未检测到摘要",
                    suggestion="学术论文通常需要包含摘要",
                ))

        # 2.3 参考文献存在性检测
        has_refs_heading = any(b.type == "references-heading" for b in doc.blocks)
        has_ref_items = any(b.type == "reference-item" for b in doc.blocks)
        if not has_refs_heading and not has_ref_items:
            issues.append(InputIssue(
                severity=InputIssueSeverity.WARNING,
                category="structure",
                sub_category="no_references",
                message="未检测到参考文献",
                suggestion="学术论文通常需要包含参考文献",
            ))
        elif has_refs_heading and not has_ref_items:
            issues.append(InputIssue(
                severity=InputIssueSeverity.WARNING,
                category="structure",
                sub_category="references_empty",
                message="检测到参考文献标题但无具体条目",
                suggestion="请确认参考文献内容是否完整",
            ))

        # 2.4 正文占比检测
        text_content = sum(
            len(b.content) for b in doc.blocks
            if b.type in ("text", "paragraph") and b.content.strip()
        )
        total_text_len = sum(
            len(b.content) + len(b.title) for b in doc.blocks
            if b.content or b.title
        )
        if total_text_len > 0 and text_content / total_text_len < 0.3:
            issues.append(InputIssue(
                severity=InputIssueSeverity.WARNING,
                category="structure",
                sub_category="low_body_ratio",
                message=f"正文内容占比偏低（{text_content/total_text_len:.0%}）",
                suggestion="文档可能以标题/表格/图片为主，正文内容较少",
            ))

    # ========================================================================
    # 3. 引用完整性检测（重点）
    # ========================================================================
    def _check_references(self, doc: DocumentContent) -> None:
        issues = self.report.issues

        # 收集全文本（用于引用检测）
        full_text_parts = []
        for b in doc.blocks:
            if b.content:
                full_text_parts.append(b.content)
            if b.title:
                full_text_parts.append(b.title)
        full_text = "\n".join(full_text_parts)

        # 3.1 图片引用完整性
        # 检测正文中的 "图X" / "Figure X" 引用
        # 规则："图" 后面跟数字编号（可含点/横线），且后面不是跟其他数字或汉字
        fig_refs = set()
        # 中文：图1、图 1、图 1-1、图 1.1
        # 边界：图号后面必须是空白、标点或句子结束，避免把"图1000人"中的1000当图号
        for m in re.finditer(r"[图Fig][\s]*(\d+(?:[.\-]\d+)*)(?=[\s，。；,.;:：\)\]）】]|$)", full_text, re.IGNORECASE):
            fig_refs.add(m.group(1))

        # 实际提取的图片数
        actual_img_count = len(doc.images)

        if fig_refs and actual_img_count == 0:
            issues.append(InputIssue(
                severity=InputIssueSeverity.ERROR,
                category="reference",
                sub_category="image_ref_missing",
                message=f"正文中引用了 {len(fig_refs)} 处图片，但未提取到任何图片",
                location=f"引用的图号: {', '.join(sorted(fig_refs)[:10])}",
                suggestion="请确认图片是否正确嵌入文档，或图片格式是否支持",
            ))
        elif fig_refs:
            # 尝试判断引用数量和实际数量是否匹配（粗略判断）
            max_ref_num = 0
            for ref in fig_refs:
                try:
                    main_num = int(re.match(r"(\d+)", ref).group(1))
                    max_ref_num = max(max_ref_num, main_num)
                except (ValueError, AttributeError):
                    pass
            if max_ref_num > actual_img_count:
                issues.append(InputIssue(
                    severity=InputIssueSeverity.WARNING,
                    category="reference",
                    sub_category="image_count_mismatch",
                    message=f"正文引用最高图号为图{max_ref_num}，但仅提取到 {actual_img_count} 张图片",
                    suggestion="部分图片可能未被正确提取，请检查图片格式或嵌入方式",
                ))

        # 3.2 表格引用完整性
        tbl_refs = set()
        for m in re.finditer(r"[表Table][\s]*(\d+(?:[.\-]\d+)*)(?=[\s，。；,.;:：\)\]）】]|$)", full_text, re.IGNORECASE):
            tbl_refs.add(m.group(1))

        actual_tbl_count = len(doc.tables)

        if tbl_refs and actual_tbl_count == 0:
            issues.append(InputIssue(
                severity=InputIssueSeverity.ERROR,
                category="reference",
                sub_category="table_ref_missing",
                message=f"正文中引用了 {len(tbl_refs)} 处表格，但未提取到任何表格",
                location=f"引用的表号: {', '.join(sorted(tbl_refs)[:10])}",
                suggestion="请确认表格是否正确嵌入文档，或表格格式是否支持",
            ))
        elif tbl_refs:
            max_tbl_num = 0
            for ref in tbl_refs:
                try:
                    main_num = int(re.match(r"(\d+)", ref).group(1))
                    max_tbl_num = max(max_tbl_num, main_num)
                except (ValueError, AttributeError):
                    pass
            if max_tbl_num > actual_tbl_count:
                issues.append(InputIssue(
                    severity=InputIssueSeverity.WARNING,
                    category="reference",
                    sub_category="table_count_mismatch",
                    message=f"正文引用最高表号为表{max_tbl_num}，但仅提取到 {actual_tbl_count} 个表格",
                    suggestion="部分表格可能未被正确提取，请检查表格格式",
                ))

        # 3.3 参考文献引用完整性
        # 检测正文 "[数字]" 引用
        cite_refs = set()
        for m in re.finditer(r"\[(\d+)\]", full_text):
            cite_refs.add(int(m.group(1)))

        ref_items = [b for b in doc.blocks if b.type == "reference-item"]
        actual_ref_count = len(ref_items)

        if cite_refs and actual_ref_count == 0:
            issues.append(InputIssue(
                severity=InputIssueSeverity.ERROR,
                category="reference",
                sub_category="citation_ref_missing",
                message=f"正文中有 {len(cite_refs)} 处文献引用，但无参考文献条目",
                location=f"引用编号: {', '.join(str(x) for x in sorted(cite_refs)[:10])}",
                suggestion="请添加参考文献列表，确保正文引用都有对应条目",
            ))
        elif cite_refs:
            max_cite = max(cite_refs) if cite_refs else 0
            if max_cite > actual_ref_count:
                missing = sorted([n for n in cite_refs if n > actual_ref_count])
                issues.append(InputIssue(
                    severity=InputIssueSeverity.ERROR,
                    category="reference",
                    sub_category="citation_missing_entry",
                    message=f"正文引用 [{max_cite}] 超过参考文献数量（{actual_ref_count} 条）",
                    location=f"缺失的引用编号: {', '.join(str(x) for x in missing[:10])}",
                    suggestion="请确保所有正文引用都有对应的参考文献条目",
                ))

        # 3.4 未引用的图片/表格
        if actual_img_count > 0 and not fig_refs:
            issues.append(InputIssue(
                severity=InputIssueSeverity.INFO,
                category="reference",
                sub_category="images_not_cited",
                message=f"有 {actual_img_count} 张图片但正文中未检测到图片引用",
                suggestion="建议在正文中引用图片（如图1、Figure 1 等）",
            ))

        if actual_tbl_count > 0 and not tbl_refs:
            issues.append(InputIssue(
                severity=InputIssueSeverity.INFO,
                category="reference",
                sub_category="tables_not_cited",
                message=f"有 {actual_tbl_count} 个表格但正文中未检测到表格引用",
                suggestion="建议在正文中引用表格（如表1、Table 1 等）",
            ))

    # ========================================================================
    # 4. 图片质量检测
    # ========================================================================
    def _check_images(self, doc: DocumentContent, images_dir: Optional[str]) -> None:
        issues = self.report.issues
        images = doc.images

        if not images:
            return

        # 4.1 图片文件存在性 & 格式检测
        valid_extensions = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif", ".svg", ".webp"}
        bad_format_images = []
        missing_images = []
        large_images = []
        small_images = []

        for img in images:
            if not img.extracted_path:
                missing_images.append(f"image{img.idx}")
                continue

            ext = os.path.splitext(img.extracted_path)[1].lower()
            if ext not in valid_extensions:
                bad_format_images.append(f"image{img.idx} ({ext})")

            # 文件大小检测
            if images_dir:
                full_path = os.path.join(images_dir, img.extracted_path)
                if os.path.exists(full_path):
                    size_bytes = os.path.getsize(full_path)
                    if size_bytes > 10 * 1024 * 1024:  # > 10MB
                        large_images.append(f"image{img.idx} ({size_bytes/1024/1024:.1f}MB)")
                    elif size_bytes < 1024:  # < 1KB
                        small_images.append(f"image{img.idx} ({size_bytes}B)")

                    # 图片尺寸检测（需要 PIL，可选）
                    if img.width > 0 and img.height > 0:
                        # 低分辨率检测（假设 300dpi，A4 宽度约 2480 像素）
                        if img.width < 300:
                            issues.append(InputIssue(
                                severity=InputIssueSeverity.WARNING,
                                category="image",
                                sub_category="low_resolution",
                                message=f"image{img.idx} 宽度仅 {img.width}px，分辨率可能偏低",
                                suggestion=f"建议图片宽度至少 600px 以保证打印清晰度",
                            ))

        if missing_images:
            issues.append(InputIssue(
                severity=InputIssueSeverity.ERROR,
                category="image",
                sub_category="image_file_missing",
                message=f"{len(missing_images)} 张图片路径缺失",
                location=", ".join(missing_images[:5]),
                suggestion="图片可能未正确提取",
            ))

        if bad_format_images:
            issues.append(InputIssue(
                severity=InputIssueSeverity.WARNING,
                category="image",
                sub_category="bad_format",
                message=f"{len(bad_format_images)} 张图片格式可能不支持",
                location=", ".join(bad_format_images[:5]),
                suggestion=f"支持的格式: {', '.join(sorted(valid_extensions))}",
            ))

        if large_images:
            issues.append(InputIssue(
                severity=InputIssueSeverity.WARNING,
                category="image",
                sub_category="too_large",
                message=f"{len(large_images)} 张图片文件过大（>10MB）",
                location=", ".join(large_images[:5]),
                suggestion="建议压缩图片以减小 PDF 体积和加快编译速度",
            ))

        if small_images:
            issues.append(InputIssue(
                severity=InputIssueSeverity.INFO,
                category="image",
                sub_category="too_small",
                message=f"{len(small_images)} 张图片文件过小（<1KB）",
                location=", ".join(small_images[:5]),
                suggestion="可能是图标或占位图，请注意检查",
            ))

    # ========================================================================
    # 5. 表格质量检测
    # ========================================================================
    def _check_tables(self, doc: DocumentContent) -> None:
        issues = self.report.issues
        tables = doc.tables

        if not tables:
            return

        empty_tables = []
        single_row_tables = []
        single_col_tables = []
        mismatched_rows = []

        for tbl in tables:
            rows = tbl.rows
            headers = tbl.headers

            # 空表
            if not rows and not headers:
                empty_tables.append(f"table{tbl.idx}")
                continue

            # 单行表（只有表头）
            if len(rows) <= 1 and headers:
                single_row_tables.append(f"table{tbl.idx}")

            # 单列或更少列
            col_count = len(headers) if headers else (len(rows[0]) if rows else 0)
            if col_count <= 1:
                single_col_tables.append(f"table{tbl.idx}")

            # 行列不匹配
            if rows and headers:
                for ri, row in enumerate(rows):
                    if len(row) != len(headers):
                        mismatched_rows.append(f"table{tbl.idx} 第{ri+1}行")
                        break

        if empty_tables:
            issues.append(InputIssue(
                severity=InputIssueSeverity.WARNING,
                category="table",
                sub_category="empty_table",
                message=f"{len(empty_tables)} 个空表格",
                location=", ".join(empty_tables[:5]),
                suggestion="空表格可能是误识别，请确认是否需要",
            ))

        if single_col_tables:
            issues.append(InputIssue(
                severity=InputIssueSeverity.INFO,
                category="table",
                sub_category="single_column",
                message=f"{len(single_col_tables)} 个单列表格",
                location=", ".join(single_col_tables[:5]),
                suggestion="单列表格可能是列表被误识别为表格",
            ))

        if mismatched_rows:
            issues.append(InputIssue(
                severity=InputIssueSeverity.ERROR,
                category="table",
                sub_category="column_mismatch",
                message=f"{len(mismatched_rows)} 个表格行列数不匹配",
                location=", ".join(mismatched_rows[:5]),
                suggestion="表格结构不完整，可能导致 LaTeX 编译错误",
            ))

    # ========================================================================
    # 6. 文本质量检测
    # ========================================================================
    def _check_text_quality(self, doc: DocumentContent) -> None:
        issues = self.report.issues

        # 收集所有文本
        all_text = "\n".join(
            b.content for b in doc.blocks
            if b.type in ("text", "paragraph", "abstract", "abstract-en")
        )

        if not all_text.strip():
            return

        # 6.1 乱码检测（异常字符比例）
        # 常见异常字符：替换符 U+FFFD、控制字符（除常见空白）
        replacement_chars = all_text.count("\ufffd")
        control_chars = len(re.findall(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", all_text))
        total_chars = len(all_text)

        if total_chars > 0:
            if replacement_chars > 0:
                ratio = replacement_chars / total_chars
                if ratio > 0.01:
                    issues.append(InputIssue(
                        severity=InputIssueSeverity.ERROR,
                        category="text",
                        sub_category="garbled_text",
                        message=f"检测到 {replacement_chars} 个乱码替换符（U+FFFD），占比 {ratio:.2%}",
                        suggestion="文档可能存在编码问题，建议检查原始文件编码",
                    ))
                else:
                    issues.append(InputIssue(
                        severity=InputIssueSeverity.WARNING,
                        category="text",
                        sub_category="minor_garbled",
                        message=f"检测到少量乱码字符（{replacement_chars} 个）",
                    ))

            if control_chars > 5:
                issues.append(InputIssue(
                    severity=InputIssueSeverity.WARNING,
                    category="text",
                    sub_category="control_chars",
                    message=f"检测到 {control_chars} 个控制字符",
                    suggestion="文档可能包含异常格式，建议清理后再排版",
                ))

        # 6.2 特殊字符检测（LaTeX 敏感字符）
        # 大量未转义的特殊字符可能导致编译失败
        special_chars_pattern = re.compile(r"[&%$#_{}^~\\]")
        special_count = len(special_chars_pattern.findall(all_text))
        if total_chars > 0 and special_count / total_chars > 0.05:
            issues.append(InputIssue(
                severity=InputIssueSeverity.WARNING,
                category="text",
                sub_category="many_special_chars",
                message=f"特殊字符比例较高（{special_count} 个，{special_count/total_chars:.2%}）",
                suggestion="LaTeX 特殊字符（& % $ # _ { } ^ ~ \\）将被自动转义，如有意保留请确认",
            ))

        # 6.3 非常长段落检测
        long_paragraphs = []
        for b in doc.blocks:
            if b.type in ("text", "paragraph") and len(b.content) > 2000:
                long_paragraphs.append(f"block{b.idx} ({len(b.content)}字)")

        if long_paragraphs:
            issues.append(InputIssue(
                severity=InputIssueSeverity.INFO,
                category="text",
                sub_category="very_long_paragraph",
                message=f"{len(long_paragraphs)} 个超长段落（>2000字）",
                location=", ".join(long_paragraphs[:3]),
                suggestion="长段落不影响排版，但建议适当分段以提高可读性",
            ))
