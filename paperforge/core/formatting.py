# -*- coding: utf-8 -*-
r"""
LaTeX 格式化与排版模块。

提供差异化排版功能，包括：
- FormatSpec: 排版格式规格
- FormatSpecParser: Word 排版要求解析器
- DifferentiatedRenderer: 差异化排版渲染器
"""

import re
import zipfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class FormatSpec:
    """排版格式规格"""
    # 文档类型
    doc_type: str = "academic"  # academic, journal, conference

    # 字体设置
    font_family: str = "宋体"
    font_size: str = "12pt"
    line_spacing: float = 1.5

    # 标题样式
    title_font: str = "黑体"
    title_size: str = "22pt"
    title_bold: bool = True

    # 章节样式
    heading1_font: str = "黑体"
    heading1_size: str = "16pt"
    heading1_bold: bool = True

    heading2_font: str = "楷体"
    heading2_size: str = "14pt"
    heading2_bold: bool = True

    heading3_font: str = "楷体"
    heading3_size: str = "13pt"
    heading3_bold: bool = True

    heading4_font: str = "宋体"
    heading4_size: str = "12pt"
    heading4_bold: bool = False

    # 正文样式
    body_font: str = "宋体"
    body_size: str = "12pt"
    body_paragraph_spacing: float = 0.0

    # 图表样式
    caption_font: str = "楷体"
    caption_size: str = "10pt"
    caption_bold: bool = False

    # LaTeX 渲染选项
    image_width: str = "0.9\\textwidth"  # 图片宽度（双列模板可设为 0.9\\columnwidth）
    table_env: str = "table"              # 表格环境（双列模板可设为 table*）
    figure_caption_position: str = "bottom"  # 图片标题位置：bottom（下）/ top（上）
    table_caption_position: str = "top"      # 表格标题位置：top（上）/ bottom（下）

    # 双列布局智能决策阈值（仅双列模板生效）
    image_aspect_threshold: float = 1.5    # 图片宽高比 >= 此值时占双列（横宽图）
    table_column_threshold: int = 4        # 表格列数 >= 此值时占双列（宽表）

    # 参考文献样式
    ref_font: str = "宋体"
    ref_size: str = "10.5pt"

    # 边距
    top_margin: float = 2.5
    bottom_margin: float = 2.5
    left_margin: float = 3.0
    right_margin: float = 2.5

    # 其他
    indent_first_line: bool = True
    indent_width: float = 0.74  # 首行缩进（两个字符）
    abstract_keywords: List[str] = field(default_factory=lambda: ["摘要", "Abstract", "关键词", "Keywords"])
    language: str = "zh"  # zh 或 en

    def validate(self) -> List[str]:
        """验证配置合法性"""
        errors = []
        if not self.font_family:
            errors.append("font_family 不能为空")
        if not re.match(r"^\d+(?:\.\d+)?pt$", self.font_size):
            errors.append(f"无效的字号格式: {self.font_size}")
        if self.line_spacing <= 0:
            errors.append(f"无效的行距: {self.line_spacing}")
        if self.top_margin < 0 or self.bottom_margin < 0:
            errors.append("边距不能为负数")
        return errors


class FormatSpecParser:
    """从 Word 文档解析排版格式要求"""

    def parse(self, docx_path: str) -> FormatSpec:
        """
        解析 Word 格式要求文档，返回 FormatSpec。

        Args:
            docx_path: Word 文档路径

        Returns:
            FormatSpec: 排版规格
        """
        spec = FormatSpec()

        try:
            with zipfile.ZipFile(docx_path) as zf:
                xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")

            paras = self._extract_paragraphs(xml)
            spec = self._parse_format_from_paragraphs(paras, spec)

        except Exception as e:
            print(f"[警告] 格式解析失败，使用默认规格: {e}")

        return spec

    def _extract_paragraphs(self, xml: str) -> List[Dict[str, str]]:
        """从 XML 中提取段落信息"""
        paras = []
        para_open = re.compile(r"<w:p[\s>]", re.IGNORECASE)
        para_close = re.compile(r"</w:p>", re.IGNORECASE)
        text_re = re.compile(r"<w:t[^>]*>([^<]*)</w:t>", re.IGNORECASE)
        style_re = re.compile(r'<w:pStyle[^>]*\bval="([^"]+)"', re.IGNORECASE)

        pos = 0
        while True:
            m = para_open.search(xml, pos)
            if m is None:
                break
            c = para_close.search(xml, m.start())
            if c is None:
                break

            pxml = xml[m.start():c.end()]
            texts = text_re.findall(pxml)
            style_m = style_re.search(pxml)

            para_text = "".join(texts).strip()
            style = style_m.group(1) if style_m else ""

            if para_text:
                paras.append({"text": para_text, "style": style})

            pos = c.end()

        return paras

    def _parse_format_from_paragraphs(
        self,
        paras: List[Dict[str, str]],
        spec: FormatSpec
    ) -> FormatSpec:
        """从段落内容中解析格式规格"""
        full_text = "\n".join(p["text"] for p in paras)

        font_patterns = [
            (r"字体[：:]\s*(.+?)(?:\n|$)", "font_family"),
            (r"[宋黑楷体隶]+[体]*(?:宋|黑|楷|隶)?", "font_family"),
            (r"字号[：:]\s*(\d+(?:\.\d+)?pt?)", "font_size"),
            (r"行距[：:]\s*(\d+(?:\.\d+)?)", "line_spacing"),
            (r"边距[：:]\s*(\d+(?:\.\d+)?)cm?", "margins"),
        ]

        for pattern, field_name in font_patterns:
            m = re.search(pattern, full_text)
            if m:
                value = m.group(1)
                if field_name == "font_size":
                    spec.font_size = value
                elif field_name == "line_spacing":
                    try:
                        spec.line_spacing = float(value)
                    except ValueError:
                        pass
                elif field_name == "margins":
                    try:
                        spec.top_margin = float(value)
                    except ValueError:
                        pass

        if "期刊" in full_text or "journal" in full_text.lower():
            spec.doc_type = "journal"
        elif "会议" in full_text or "conference" in full_text.lower():
            spec.doc_type = "conference"

        return spec

    def parse_from_dict(self, params: Dict[str, Any]) -> FormatSpec:
        """从字典参数创建 FormatSpec"""
        spec = FormatSpec()

        mapping = {
            "doc_type": "doc_type",
            "font_family": "font_family",
            "font_size": "font_size",
            "line_spacing": "line_spacing",
            "title_font": "title_font",
            "title_size": "title_size",
            "title_bold": "title_bold",
            "heading1_font": "heading1_font",
            "heading1_size": "heading1_size",
            "heading1_bold": "heading1_bold",
            "heading2_font": "heading2_font",
            "heading2_size": "heading2_size",
            "heading2_bold": "heading2_bold",
            "heading3_font": "heading3_font",
            "heading3_size": "heading3_size",
            "heading3_bold": "heading3_bold",
            "heading4_font": "heading4_font",
            "heading4_size": "heading4_size",
            "heading4_bold": "heading4_bold",
            "body_font": "body_font",
            "body_size": "body_size",
            "caption_font": "caption_font",
            "caption_size": "caption_size",
            "caption_bold": "caption_bold",
            "ref_font": "ref_font",
            "ref_size": "ref_size",
            "top_margin": "top_margin",
            "bottom_margin": "bottom_margin",
            "left_margin": "left_margin",
            "right_margin": "right_margin",
        }

        for src, dst in mapping.items():
            if src in params:
                setattr(spec, dst, params[src])

        return spec


class DifferentiatedRenderer:
    """差异化排版渲染器"""

    def __init__(self, format_spec: FormatSpec = None):
        self.format_spec = format_spec or FormatSpec()

    def apply_format_spec(self, tex_lines: List[str]) -> List[str]:
        """根据 FormatSpec 调整 LaTeX 内容"""
        spec = self.format_spec
        lines = tex_lines[:]

        # 1. 调整文档类
        for i, line in enumerate(lines):
            if "\\documentclass" in line:
                if spec.doc_type == "journal":
                    lines[i] = "\\documentclass[12pt,a4paper]{article}"
                elif spec.doc_type == "conference":
                    lines[i] = "\\documentclass[12pt,a4paper]{IEEEtran}"
                else:
                    lines[i] = "\\documentclass[12pt,a4paper]{report}"
                break

        # 2. 调整 geometry（边距）
        for i, line in enumerate(lines):
            if "\\geometry" in line:
                lines[i] = (
                    f"\\geometry{{a4paper, "
                    f"top={spec.top_margin}cm, "
                    f"bottom={spec.bottom_margin}cm, "
                    f"left={spec.left_margin}cm, "
                    f"right={spec.right_margin}cm}}"
                )
                break

        # 3. 添加行距设置
        if spec.line_spacing != 1.0:
            for i, line in enumerate(lines):
                if "\\begin{document}" in line:
                    if spec.doc_type == "journal":
                        lines.insert(i, f"\\linespread{{{spec.line_spacing:.1f}}}")
                    break

        return lines

    def render_title(self, title: str) -> str:
        """渲染论文标题"""
        spec = self.format_spec
        return f"\\{spec.title_font}{{}}\\{spec.title_size}{{}}\\textbf{{{title}}}"

    def render_heading(self, text: str, level: int) -> str:
        """渲染章节标题"""
        spec = self.format_spec
        commands = {
            1: (spec.heading1_font, spec.heading1_size, spec.heading1_bold),
            2: (spec.heading2_font, spec.heading2_size, spec.heading2_bold),
        }
        font, size, bold = commands.get(level, ("宋体", "12pt", False))

        if bold:
            return f"\\{font}{{}}\\{size}{{}}\\textbf{{{text}}}"
        return f"\\{font}{{}}\\{size}{{{text}}}"

    def render_paragraph(
        self,
        text: str,
        indent: bool = True,
        spacing_after: float = 0.0
    ) -> List[str]:
        """渲染正文段落"""
        spec = self.format_spec
        lines = []

        if indent and spec.indent_first_line:
            indent_cmd = f"\\hspace{{{spec.indent_width}cm}}"
        else:
            indent_cmd = ""

        if spacing_after > 0:
            lines.append(f"\\vspace{{{spacing_after}pt}}")

        lines.append(f"{indent_cmd}{text}")
        return lines

    def render_caption(self, caption: str, caption_type: str = "fig") -> str:
        """渲染图表标题"""
        spec = self.format_spec
        prefix = "图" if caption_type == "fig" else "表"

        if spec.caption_bold:
            bold_part = "\\textbf{" + prefix + " " + caption + "}"
        else:
            bold_part = prefix + " " + caption

        inner = "\\" + spec.caption_size + "{" + bold_part + "}"
        outer = "\\" + spec.caption_font + "{" + inner + "}"
        return "\\caption{" + outer + "}"

    def render_reference_item(self, text: str, index: int) -> str:
        """渲染参考文献条目"""
        spec = self.format_spec
        bibitem = "\\bibitem{ref" + str(index) + "} "
        font_cmd = "\\" + spec.ref_font + "{\\" + spec.ref_size + "{" + text + "}}"
        return bibitem + font_cmd


# 预设格式规格
PRESET_FORMATS: Dict[str, FormatSpec] = {}


def register_preset(name: str, spec: FormatSpec) -> None:
    """注册预设格式"""
    PRESET_FORMATS[name] = spec


def _init_presets() -> None:
    """初始化预设格式 —— 每个模板对应独立的 FormatSpec。"""

    # ──────────────────────────────────────────
    # 中文模板（nsfc / sci / thesis / humanities）
    # ──────────────────────────────────────────

    # 1. NSFC 国自然基金
    register_preset("nsfc", FormatSpec(
        doc_type="academic",
        font_family="宋体",
        font_size="12pt",
        line_spacing=1.5,
        title_font="黑体",
        title_size="22pt",
        title_bold=True,
        heading1_font="黑体",
        heading1_size="16pt",
        heading1_bold=True,
        heading2_font="楷体",
        heading2_size="14pt",
        heading2_bold=True,
        heading3_font="楷体",
        heading3_size="13pt",
        heading3_bold=True,
        heading4_font="宋体",
        heading4_size="12pt",
        heading4_bold=False,
        body_font="宋体",
        body_size="12pt",
        caption_font="楷体",
        caption_size="10pt",
        caption_bold=False,
        ref_font="宋体",
        ref_size="10.5pt",
        top_margin=2.5,
        bottom_margin=2.5,
        left_margin=3.0,
        right_margin=2.5,
    ))

    # 2. SCI 中文期刊（复用 nsfc 格式，可独立调整）
    register_preset("sci", FormatSpec(
        doc_type="journal",
        font_family="宋体",
        font_size="12pt",
        line_spacing=1.5,
        title_font="黑体",
        title_size="18pt",
        title_bold=True,
        heading1_font="黑体",
        heading1_size="14pt",
        heading1_bold=True,
        heading2_font="楷体",
        heading2_size="12pt",
        heading2_bold=True,
        heading3_font="楷体",
        heading3_size="12pt",
        heading3_bold=True,
        heading4_font="宋体",
        heading4_size="12pt",
        heading4_bold=False,
        body_font="宋体",
        body_size="12pt",
        caption_font="楷体",
        caption_size="10pt",
        caption_bold=False,
        ref_font="宋体",
        ref_size="10.5pt",
        top_margin=2.0,
        bottom_margin=2.0,
        left_margin=2.5,
        right_margin=2.5,
    ))

    # 3. 学位论文（与 nsfc 基本一致，标题更大）
    register_preset("thesis", FormatSpec(
        doc_type="academic",
        font_family="宋体",
        font_size="12pt",
        line_spacing=1.5,
        title_font="黑体",
        title_size="26pt",
        title_bold=True,
        heading1_font="黑体",
        heading1_size="16pt",
        heading1_bold=True,
        heading2_font="楷体",
        heading2_size="14pt",
        heading2_bold=True,
        heading3_font="楷体",
        heading3_size="13pt",
        heading3_bold=True,
        heading4_font="宋体",
        heading4_size="12pt",
        heading4_bold=False,
        body_font="宋体",
        body_size="12pt",
        caption_font="楷体",
        caption_size="10pt",
        caption_bold=False,
        ref_font="宋体",
        ref_size="10.5pt",
        top_margin=2.5,
        bottom_margin=2.5,
        left_margin=3.0,
        right_margin=2.5,
    ))

    # 4. 人文社科期刊
    register_preset("humanities", FormatSpec(
        doc_type="journal",
        font_family="宋体",
        font_size="12pt",
        line_spacing=1.5,
        title_font="黑体",
        title_size="18pt",
        title_bold=True,
        heading1_font="黑体",
        heading1_size="14pt",
        heading1_bold=True,
        heading2_font="楷体",
        heading2_size="12pt",
        heading2_bold=False,
        heading3_font="楷体",
        heading3_size="12pt",
        heading3_bold=False,
        heading4_font="宋体",
        heading4_size="12pt",
        heading4_bold=False,
        body_font="宋体",
        body_size="12pt",
        caption_font="楷体",
        caption_size="10pt",
        caption_bold=False,
        ref_font="宋体",
        ref_size="10.5pt",
        top_margin=2.0,
        bottom_margin=2.0,
        left_margin=2.5,
        right_margin=2.5,
    ))

    # ──────────────────────────────────────────
    # 学位论文模板（thesis / renai）
    # ──────────────────────────────────────────

    # 5. 天津仁爱学院毕业论文
    register_preset("renai", FormatSpec(
        doc_type="thesis",
        font_family="宋体",
        font_size="12pt",
        line_spacing=1.5,
        title_font="黑体",
        title_size="22pt",
        title_bold=True,
        heading1_font="黑体",
        heading1_size="15pt",
        heading1_bold=True,
        heading2_font="黑体",
        heading2_size="14pt",
        heading2_bold=True,
        heading3_font="黑体",
        heading3_size="14pt",
        heading3_bold=True,
        heading4_font="宋体",
        heading4_size="12pt",
        heading4_bold=False,
        body_font="宋体",
        body_size="12pt",
        caption_font="宋体",
        caption_size="10.5pt",
        caption_bold=False,
        ref_font="宋体",
        ref_size="10.5pt",
        top_margin=2.54,
        bottom_margin=2.54,
        left_margin=3.18,
        right_margin=3.18,
        language="zh",
        figure_caption_position="bottom",
        table_caption_position="top",
    ))

    # ──────────────────────────────────────────
    # 英文会议模板（ieee / icml / cvpr / neurips / acl）
    # ──────────────────────────────────────────

    # 6. IEEE 会议（双栏，10pt）
    register_preset("ieee", FormatSpec(
        doc_type="conference",
        font_family="Times New Roman",
        font_size="10pt",
        line_spacing=1.0,
        title_font="Times New Roman",
        title_size="14pt",
        title_bold=True,
        heading1_font="Times New Roman",
        heading1_size="12pt",
        heading1_bold=True,
        heading2_font="Times New Roman",
        heading2_size="11pt",
        heading2_bold=False,
        heading3_font="Times New Roman",
        heading3_size="10pt",
        heading3_bold=True,
        heading4_font="Times New Roman",
        heading4_size="10pt",
        heading4_bold=False,
        body_font="Times New Roman",
        body_size="10pt",
        caption_font="Times New Roman",
        caption_size="9pt",
        caption_bold=False,
        ref_font="Times New Roman",
        ref_size="9pt",
        top_margin=2.5,
        bottom_margin=2.5,
        left_margin=2.5,
        right_margin=2.5,
        language="en",
        image_width="0.9\\columnwidth",
        table_env="table*",
    ))

    # 7. ICML 2025（单栏，10pt）
    register_preset("icml2025", FormatSpec(
        doc_type="conference",
        font_family="Times New Roman",
        font_size="10pt",
        line_spacing=1.0,
        title_font="Times New Roman",
        title_size="14pt",
        title_bold=True,
        heading1_font="Times New Roman",
        heading1_size="12pt",
        heading1_bold=True,
        heading2_font="Times New Roman",
        heading2_size="11pt",
        heading2_bold=False,
        heading3_font="Times New Roman",
        heading3_size="10pt",
        heading3_bold=True,
        heading4_font="Times New Roman",
        heading4_size="10pt",
        heading4_bold=False,
        body_font="Times New Roman",
        body_size="10pt",
        caption_font="Times New Roman",
        caption_size="9pt",
        caption_bold=False,
        ref_font="Times New Roman",
        ref_size="9pt",
        top_margin=2.5,
        bottom_margin=2.5,
        left_margin=2.5,
        right_margin=2.5,
        language="en",
    ))

    # 8. CVPR 2024（单栏，10pt）
    register_preset("cvpr2024", FormatSpec(
        doc_type="conference",
        font_family="Times New Roman",
        font_size="10pt",
        line_spacing=1.0,
        title_font="Times New Roman",
        title_size="14pt",
        title_bold=True,
        heading1_font="Times New Roman",
        heading1_size="12pt",
        heading1_bold=True,
        heading2_font="Times New Roman",
        heading2_size="11pt",
        heading2_bold=False,
        heading3_font="Times New Roman",
        heading3_size="10pt",
        heading3_bold=True,
        heading4_font="Times New Roman",
        heading4_size="10pt",
        heading4_bold=False,
        body_font="Times New Roman",
        body_size="10pt",
        caption_font="Times New Roman",
        caption_size="9pt",
        caption_bold=False,
        ref_font="Times New Roman",
        ref_size="9pt",
        top_margin=2.5,
        bottom_margin=2.5,
        left_margin=2.5,
        right_margin=2.5,
        language="en",
    ))

    # 9. NeurIPS 2024（单栏，10pt）
    register_preset("neurips2024", FormatSpec(
        doc_type="conference",
        font_family="Times New Roman",
        font_size="10pt",
        line_spacing=1.0,
        title_font="Times New Roman",
        title_size="14pt",
        title_bold=True,
        heading1_font="Times New Roman",
        heading1_size="12pt",
        heading1_bold=True,
        heading2_font="Times New Roman",
        heading2_size="11pt",
        heading2_bold=False,
        heading3_font="Times New Roman",
        heading3_size="10pt",
        heading3_bold=True,
        heading4_font="Times New Roman",
        heading4_size="10pt",
        heading4_bold=False,
        body_font="Times New Roman",
        body_size="10pt",
        caption_font="Times New Roman",
        caption_size="9pt",
        caption_bold=False,
        ref_font="Times New Roman",
        ref_size="9pt",
        top_margin=2.5,
        bottom_margin=2.5,
        left_margin=2.5,
        right_margin=2.5,
        language="en",
    ))

    # 10. ACL 2024（单栏，11pt）
    register_preset("acl2024", FormatSpec(
        doc_type="conference",
        font_family="Times New Roman",
        font_size="11pt",
        line_spacing=1.0,
        title_font="Times New Roman",
        title_size="14pt",
        title_bold=True,
        heading1_font="Times New Roman",
        heading1_size="12pt",
        heading1_bold=True,
        heading2_font="Times New Roman",
        heading2_size="11pt",
        heading2_bold=False,
        heading3_font="Times New Roman",
        heading3_size="11pt",
        heading3_bold=True,
        heading4_font="Times New Roman",
        heading4_size="11pt",
        heading4_bold=False,
        body_font="Times New Roman",
        body_size="11pt",
        caption_font="Times New Roman",
        caption_size="10pt",
        caption_bold=False,
        ref_font="Times New Roman",
        ref_size="10pt",
        top_margin=2.5,
        bottom_margin=2.5,
        left_margin=2.5,
        right_margin=2.5,
        language="en",
    ))

    # 保留向后兼容的旧预设名
    register_preset("academic", PRESET_FORMATS["nsfc"])
    register_preset("chinese_journal", PRESET_FORMATS["sci"])
    register_preset("ieee_conference", PRESET_FORMATS["ieee"])


# 初始化预设
_init_presets()


def parse_format_from_docx(docx_path: str) -> FormatSpec:
    """从 Word 文档解析排版格式"""
    parser = FormatSpecParser()
    return parser.parse(docx_path)


def parse_format_from_dict(params: Dict[str, Any]) -> FormatSpec:
    """从参数字典创建排版规格"""
    parser = FormatSpecParser()
    return parser.parse_from_dict(params)