# -*- coding: utf-8 -*-
r"""
通用 Word 文档读取器 (核心 skill 组件)

输入：.docx 文件路径
输出：DocumentContent 对象
    - .blocks: 按原文顺序的结构化块列表
    - .text: 向后兼容的纯文本拼接
    - .images: 从 docx 提取的图片列表
    - .source_file

Block 类型定义:
    title, heading(level), abstract, abstract-en, keywords,
    text, image, table, references-heading, reference-item

设计原则:
    1. 使用正则在 document.xml 上精确拆分段落与表格
    2. 按原文顺序保持 blocks 顺序
    3. image rId 与 target 映射正确提取
"""

import os
import re
import zipfile
from dataclasses import dataclass
from typing import List, Optional, Dict, Any

from core.types import Block, DocxImage, DocxTable, DocumentContent


# ============================================================
# 正则常量
# ============================================================
_PARA_OPEN_RE = re.compile(r"<w:p[\s>]", re.IGNORECASE)
_PARA_CLOSE_RE = re.compile(r"</w:p>", re.IGNORECASE)
_TBL_OPEN_RE = re.compile(r"<w:tbl[\s>]", re.IGNORECASE)
_TBL_CLOSE_RE = re.compile(r"</w:tbl>", re.IGNORECASE)
_T_RE = re.compile(r"<w:t[^>]*>([^<]*)</w:t>", re.IGNORECASE)
_PSTYLE_RE = re.compile(r'<w:pStyle[^>]*\bval="([^"]+)"', re.IGNORECASE)
_RID_EMBED_RE = re.compile(r'r:embed="([^"]+)"', re.IGNORECASE)
_RID_ID_RE = re.compile(r'r:id="([^"]+)"', re.IGNORECASE)

# Run 级别格式提取
_RUN_OPEN_RE = re.compile(r"<w:r[\s>]", re.IGNORECASE)
_RUN_CLOSE_RE = re.compile(r"</w:r>", re.IGNORECASE)
_COLOR_RE = re.compile(r'<w:color[^>]*\bval="([^"]+)"', re.IGNORECASE)
_BOLD_RE = re.compile(r"<w:b(?:\s[^>]*)?/>", re.IGNORECASE)
_ITALIC_RE = re.compile(r"<w:i(?:\s[^>]*)?/>", re.IGNORECASE)
_UNDERLINE_RE = re.compile(r"<w:u(?:\s[^>]*)?>", re.IGNORECASE)
_HIGHLIGHT_RE = re.compile(r'<w:highlight[^>]*\bval="([^"]+)"', re.IGNORECASE)
_FONTSIZE_RE = re.compile(r'<w:sz[^>]*\bval="([^"]+)"', re.IGNORECASE)
_FONTFAMILY_RE = re.compile(r'<w:rFonts[^>]*\bascii="([^"]+)"', re.IGNORECASE)

_RELS_RE = re.compile(
    r'<Relationship\s+Id="([^"]+)"\s+Type="([^"]+)"\s+Target="([^"]+)"',
    re.IGNORECASE,
)

# ============================================================
# 公式检测正则（OMML / MathType）
# ============================================================
_OMML_RE = re.compile(r"<m:oMath\b.*?</m:oMath>", re.DOTALL | re.IGNORECASE)
_OMML_TEXT_RE = re.compile(r"<m:t[^>]*>([^<]*)</m:t>", re.IGNORECASE)
_W_OBJECT_RE = re.compile(r"<w:object\b.*?</w:object>", re.DOTALL | re.IGNORECASE)
_W_OBJ_NAME_RE = re.compile(r'<v:imagedata[^>]*o:title="([^"]+)"', re.IGNORECASE)

_NUMBERED_HEADING_RE = re.compile(r"^(?:\d+(?:\.\d+){0,3})\s+(.+)$")
_UNIT_AFTER_NUM_RE = re.compile(r"^\s*(MHz|GHz|kHz|Hz|km|mm|°C|dB|kPa|%)\b", re.IGNORECASE)

# 日期/年份模式：数字后跟"届/年/月"等，不是标题
_DATE_LIKE_RE = re.compile(r"^\d{2,4}\s*\d{0,4}\s*(届|年|月)")
_FIGURE_CAPTION_RE = re.compile(
    r"^(?:图\s*\d+|Figure\s*\d+|Fig\.?\s*\d+)\s*[：:\-.]?\s*(.+?)\s*[：:\-]?\s*$",
    re.IGNORECASE,
)
_TABLE_CAPTION_RE = re.compile(
    r"^(?:表\s*\d+|Table\s*\d+|Tab\.?\s*\d+)\s*[：:\-.]?\s*(.+?)\s*[：:\-]?\s*$",
    re.IGNORECASE,
)
_REF_ITEM_RE = re.compile(r"^\s*\[(\d+)\]\s*(.+)$")
# 匹配 [整条文献] 形式（外层方括号包裹整条文献，常见于手工注入的新文献）
# 例如：[崔启升; 赵庆鑫. IRI2020模型在MSNA区域的适用性分析[J]. 大地测量与地球动力学, 2026.]
_REF_BRACKETED_RE = re.compile(r"^\s*\[([^\[\]]+)\]\s*$")
_REFS_HEADING_RE = re.compile(
    r"^\s*(References?|参考文献|Bibliography)\s*[:：]?\s*$", re.IGNORECASE
)
_ABSTRACT_RE = re.compile(r"^\s*(摘\s*要|Abstract|ABSTRACT)\s*[:：]?\s*$", re.IGNORECASE)
_ACK_RE = re.compile(r"^\s*(致\s*谢|Acknowledg?ments?)\s*[:：]?\s*$", re.IGNORECASE)
# Word 原文目录标题（"目  录"、"目    录"、"Contents" 等）
_TOC_HEADING_RE = re.compile(r"^\s*(目\s*录|Contents?)\s*[:：]?\s*$", re.IGNORECASE)
# 目录条目特征：末尾是 1-3 位页码（允许前面有引导点或空格）
_TOC_ENTRY_RE = re.compile(r".+\.{2,}\s*\d{1,3}$|.{2,}\s+\d{1,3}$")
# 论文末尾常见的特殊标题/声明（独立成段的短标题）
_DECLARATION_RE = re.compile(
    r"^\s*("
    r"人工智能辅助声明|AI\s*辅助声明|AI辅助声明|"  # AI 辅助声明
    r"数据可用性声明|数据可用性|Data\s+Availability|"
    r"利益冲突声明|Conflict\s+of\s+Interest|"
    r"作者贡献|Author\s+Contributions?|"
    r"基金|Funding|"
    r"ORCID|"
    r"作者信息|Author\s+Information|"
    r"出版信息|Publisher'?s?\s+Note|"
    r"补充材料|Supplementary\s+Material"
    r")\s*[:：]?\s*$",
    re.IGNORECASE
)

# ============================================================
# Run 级别格式提取
# ============================================================

@dataclass
class RichTextSegment:
    """富文本片段：包含文本内容和格式信息"""
    text: str
    bold: bool = False
    italic: bool = False
    underline: bool = False
    color: str = ""          # 十六进制颜色，如 "2C2C36"（空=默认颜色）
    highlight: str = ""     # 高亮颜色，如 "yellow"（空=无高亮）
    font_size: str = ""     # 字号，如 "21" 表示 10.5pt
    font_family: str = ""   # 字体名，如 "Times New Roman"


def _extract_formulas_from_para(p_xml: str) -> List[str]:
    """从段落 XML 中提取 OMML / MathType 公式的纯文本内容。

    返回一个列表，每个元素是一个公式文本。
    这些文本随后会在 latex_builder.py 中被 math_aware_escape
    自动包裹为 $...$ 或作为独立行间公式处理。
    """
    formulas: List[str] = []
    # 1) OMML 公式（Office Open XML Math）
    for omml_match in _OMML_RE.finditer(p_xml):
        omml_xml = omml_match.group(0)
        texts = _OMML_TEXT_RE.findall(omml_xml)
        formula_text = "".join(texts).strip()
        if formula_text:
            formulas.append(formula_text)
    # 2) MathType OLE 对象：尝试提取对象标题（通常包含公式描述）
    for obj_match in _W_OBJECT_RE.finditer(p_xml):
        obj_xml = obj_match.group(0)
        name_match = _W_OBJ_NAME_RE.search(obj_xml)
        if name_match:
            title = name_match.group(1).strip()
            if title and len(title) > 1:
                formulas.append(f"[MathType:{title}]")
    return formulas


def _extract_rich_text_from_para(p_xml: str) -> tuple:
    """从段落 XML 中提取富文本信息。

    返回 (plain_text, rich_segments, dominant_color, has_format_changes)
    - plain_text: 纯文本内容
    - rich_segments: List[RichTextSegment] 每个 run 的格式片段
    - dominant_color: 段落主色调（出现最多的颜色）
    - has_format_changes: 是否有格式变化（颜色/bold/italic等）
    """
    segments = []
    pos = 0

    while True:
        # 找下一个 run
        r_open = _RUN_OPEN_RE.search(p_xml, pos)
        if r_open is None:
            break

        r_close = _RUN_CLOSE_RE.search(p_xml, r_open.start())
        if r_close is None:
            break

        r_xml = p_xml[r_open.start():r_close.end()]

        # 提取文本
        texts = _T_RE.findall(r_xml)
        text = "".join(texts)
        # XML 转义还原：&amp; 必须最先；&lt; &gt; &quot; &apos;
        text = (
            text.replace("&amp;", "&")
                .replace("&lt;", "<")
                .replace("&gt;", ">")
                .replace("&quot;", "\"")
                .replace("&apos;", "'")
        )

        # 提取格式属性
        color_match = _COLOR_RE.search(r_xml)
        bold_match = _BOLD_RE.search(r_xml)
        italic_match = _ITALIC_RE.search(r_xml)
        underline_match = _UNDERLINE_RE.search(r_xml)
        highlight_match = _HIGHLIGHT_RE.search(r_xml)
        fontsize_match = _FONTSIZE_RE.search(r_xml)
        fontfamily_match = _FONTFAMILY_RE.search(r_xml)

        color = color_match.group(1) if color_match else ""
        highlight = highlight_match.group(1) if highlight_match else ""
        font_size = fontsize_match.group(1) if fontsize_match else ""
        font_family = fontfamily_match.group(1) if fontfamily_match else ""

        # Word 字号是 half-points，乘以0.5得到pt值
        if font_size:
            try:
                font_size = str(int(font_size) // 2)  # 转为 pt
            except ValueError:
                font_size = ""

        # 判断粗体：<w:b/> 或 <w:b w:val="1"/> 表示加粗
        bold = False
        if bold_match:
            # 检查是否有 w:val="0" 表示不加粗
            bold_text = bold_match.group(0)
            if 'w:val="0"' not in bold_text:
                bold = True

        # 判断斜体
        italic = False
        if italic_match:
            italic_text = italic_match.group(0)
            if 'w:val="0"' not in italic_text:
                italic = True

        # 判断下划线
        underline = False
        if underline_match:
            underline_text = underline_match.group(0)
            if 'w:val="0"' not in underline_text and 'val="none"' not in underline_text:
                underline = True

        if text:  # 只添加有内容的片段
            segments.append(RichTextSegment(
                text=text,
                bold=bold,
                italic=italic,
                underline=underline,
                color=color,
                highlight=highlight,
                font_size=font_size,
                font_family=font_family,
            ))

        pos = r_close.end()

    if not segments:
        return "", [], "", False

    # 纯文本
    plain_text = "".join(s.text for s in segments)

    # 主色调（出现最多的非空颜色）
    color_counts: Dict[str, int] = {}
    for seg in segments:
        if seg.color and seg.color not in ("2C2C36", "000000", "FFFFFF"):
            # 忽略默认黑色和白色
            color_counts[seg.color] = color_counts.get(seg.color, 0) + 1
    dominant_color = ""
    if color_counts:
        dominant_color = max(color_counts, key=color_counts.get)

    # 是否有格式变化（仅用于判断是否需要 rich_segments）
    # 只要有任何 run 有非默认格式，就认为需要 rich_segments
    has_changes = False
    for seg in segments:
        if seg.bold or seg.italic or seg.underline:
            has_changes = True
            break
        if seg.color and seg.color not in ("2C2C36", "000000", "FFFFFF", ""):
            has_changes = True
            break

    return plain_text, segments, dominant_color, has_changes


# ============================================================
# 参考文献行精细拆分器
# ============================================================

# 判断续行：以下列模式开头的文本视为上一条参考文献的续行
# - 小写字母开头（如 "procedure..."）
# - URL 开头（http/https）
# - DOI 开头
# - 括号开头的英文翻译补充（如 "(ZHANGJinzhu..."）
_CONTINUATION_PREFIXES = re.compile(
    r"^("
    r"[a-z]"
    r"|http"
    r"|DOI[:：]"
    r"|https"
    r"|\("
    r"|（"
    r"|procedure"
    r"|[（(][A-Z]"
    r")"
)

# 判断新参考开始：以下列模式开头的文本视为新参考文献
# - 英文大写字母开头后跟字母（作者名）
# - 中文字符后紧跟中文标点（作者名）
_REF_START_RE = re.compile(
    r"^("
    r"[A-Z][A-Za-z'\-]+"
    r"|[\u4e00-\u9fff]+[，,．.]"
    r")"
)


def _is_new_reference_start(text: str) -> bool:
    """判断一段文本是否像是一条新参考文献的开始。"""
    if not text:
        return False
    # 去除 [数字] 前缀后再判断
    stripped = re.sub(r"^\s*\[\d+\]\s*", "", text).strip()
    if not stripped:
        return False
    # 匹配续行前缀 -> 不是新开始
    if _CONTINUATION_PREFIXES.match(stripped):
        return False
    # 匹配作者名格式 -> 是新开始
    if _REF_START_RE.match(stripped):
        return True
    # 非典型格式但也不像续行，默认算新开始
    return True


def _split_and_append_refs(text: str, blocks: list):
    """将一行参考文献文本追加到 block 列表。

    策略：
    - 如果文本像续行（小写/URL/DOI/括号开头），合并到上一条 reference-item
    - 否则创建新的 reference-item
    """
    if not text:
        return

    def _last_ref():
        for b in reversed(blocks):
            if b.type == "reference-item":
                return b
        return None

    prev_ref = _last_ref()
    if prev_ref and not _is_new_reference_start(text):
        # 续行：合并到上一条
        prev_ref.content = prev_ref.content + " " + text.strip()
    else:
        # 新参考文献：创建新条目
        blocks.append(Block(type="reference-item", content=text))


# ============================================================
# 主入口
# ============================================================
def read_document(file_path: str, output_dir: Optional[str] = None) -> DocumentContent:
    ext = os.path.splitext(file_path)[-1].lower()
    if ext == ".docx":
        return _read_docx(file_path, output_dir or os.path.dirname(file_path))
    elif ext == ".txt":
        content = open(file_path, "r", encoding="utf-8").read()
        blocks = _parse_text_blocks(content)
        text = "\n\n".join(b.content for b in blocks if b.content)
        return DocumentContent(blocks=blocks, text=text, source_file=file_path)
    else:
        raise ValueError(f"不支持的文件格式: {ext}，仅支持 .docx 和 .txt")


# ============================================================
# .docx 核心读取
# ============================================================
def _read_docx(file_path: str, output_dir: str) -> DocumentContent:
    os.makedirs(output_dir, exist_ok=True)
    images_dir = os.path.join(output_dir, "images")
    os.makedirs(images_dir, exist_ok=True)

    with zipfile.ZipFile(file_path) as zf:
        # 1) 读主文档 XML 与 rels
        xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
        try:
            rels_xml = zf.read("word/_rels/document.xml.rels").decode("utf-8", errors="ignore")
        except KeyError:
            rels_xml = ""

        # 2) 构建 rId → (type, target) 映射
        rid_map: Dict[str, tuple] = {}
        for m in _RELS_RE.finditer(rels_xml):
            rid = m.group(1)
            rtype = m.group(2).lower()
            target = m.group(3)
            rid_map[rid] = (rtype, target)

        # 3) 提取图片并落盘
        extracted_images: Dict[int, DocxImage] = {}
        img_counter = 0
        # 构建 rid → image_idx 的索引
        rid_to_image_idx: Dict[str, int] = {}
        for rid, (rtype, target) in rid_map.items():
            if "image" in rtype or "image" in target.lower():
                try:
                    data = zf.read("word/" + target if not target.startswith("word/") else target)
                except Exception:
                    try:
                        data = zf.read(target)
                    except Exception:
                        continue
                img_counter += 1
                ext = os.path.splitext(target)[-1] or ".png"
                local_fn = f"image{img_counter:02d}{ext}"
                local_full = os.path.join(images_dir, local_fn)
                with open(local_full, "wb") as f:
                    f.write(data)
                extracted_images[img_counter] = DocxImage(
                    idx=img_counter,
                    rid=rid,
                    extracted_path=os.path.join("images", local_fn).replace("\\", "/"),
                    caption="",
                    paragraph_index=-1,
                )
                rid_to_image_idx[rid] = img_counter

    # 4) 扫描 XML，按出现顺序生成 raw_items（段落 + 表格）
    raw_items: List[Dict[str, Any]] = []
    paragraph_counter = 0

    # 使用指针遍历 XML：找到所有 <w:p> 和 <w:tbl> 的边界
    pos = 0
    while pos < len(xml):
        # 找下一个段落的起点
        p_match = _PARA_OPEN_RE.search(xml, pos)
        tbl_match = _TBL_OPEN_RE.search(xml, pos)

        candidates = []
        if p_match is not None:
            candidates.append(("p", p_match.start(), p_match))
        if tbl_match is not None:
            candidates.append(("tbl", tbl_match.start(), tbl_match))

        if not candidates:
            break

        # 谁先出现就先处理谁
        candidates.sort(key=lambda x: x[1])
        tag_type, tag_start, match_obj = candidates[0]

        if tag_type == "p":
            # 找对应的 </w:p>
            close_match = _PARA_CLOSE_RE.search(xml, tag_start)
            if close_match is None:
                break
            p_xml = xml[tag_start:close_match.end()]
            paragraph_counter += 1

            # 提取富文本信息（包含颜色、bold、italic等）
            text_content, rich_segments, dominant_color, has_format_changes = \
                _extract_rich_text_from_para(p_xml)

            # 提取公式（OMML / MathType）
            formulas = _extract_formulas_from_para(p_xml)

            # 提取样式
            style_match = _PSTYLE_RE.search(p_xml)
            style_name = style_match.group(1) if style_match else ""
            # 提取段落内图片 rId
            rids_in_para = _RID_EMBED_RE.findall(p_xml)
            if not rids_in_para:
                rids_in_para = _RID_ID_RE.findall(p_xml)
            image_indices_in_para = [
                rid_to_image_idx[r] for r in rids_in_para if r in rid_to_image_idx
            ]

            item = {
                "kind": "text",
                "text": text_content.strip(),
                "style": style_name,
                "paragraph_index": paragraph_counter,
                "images": image_indices_in_para,
                "formulas": formulas,
            }

            # 保存富文本信息（如果有任何格式信息）
            if rich_segments:
                # 检查是否有任何非默认格式
                has_formatting = False
                for seg in rich_segments:
                    if seg.bold or seg.italic or seg.underline or \
                       (seg.color and seg.color not in ('2C2C36', '000000', 'FFFFFF', '')):
                        has_formatting = True
                        break
                if has_formatting:
                    item["rich_segments"] = rich_segments
                    if dominant_color:
                        item["dominant_color"] = dominant_color

            raw_items.append(item)
            pos = close_match.end()
        else:  # table
            close_match = _TBL_CLOSE_RE.search(xml, tag_start)
            if close_match is None:
                break
            tbl_xml = xml[tag_start:close_match.end()]
            headers, rows = _parse_table_xml(tbl_xml)
            raw_items.append({
                "kind": "table_raw",
                "idx": 0,  # 稍后赋值
                "headers": headers,
                "rows": rows,
                "paragraph_index": paragraph_counter,
            })
            pos = close_match.end()

    # 5) 给表格按顺序编号
    table_counter = 0
    for item in raw_items:
        if item["kind"] == "table_raw":
            table_counter += 1
            item["idx"] = table_counter

    # 6) second pass: 转换为 blocks
    blocks: List[Block] = []
    tables_final: Dict[int, DocxTable] = {}
    in_references = False
    in_toc = False  # Word 原文目录模式：跳过目录条目

    for idx, item in enumerate(raw_items):
        if item["kind"] == "text":
            text = item["text"]
            style = item["style"] or ""
            imgs = item["images"] or []

            # 如果该段落有图片，先插入图片 block
            for img_idx in imgs:
                if img_idx in extracted_images:
                    img = extracted_images[img_idx]
                    img.paragraph_index = item["paragraph_index"]
                    blocks.append(Block(
                        type="image",
                        idx=img_idx,
                        data={"image_obj": img, "caption": ""},
                    ))

            if not text:
                continue

            # 参考文献区内的条目
            if in_references:
                # 检测是否遇到"致谢"/"附录"等标题，退出参考文献模式
                stripped_for_exit = text.strip()
                if _ACK_RE.match(stripped_for_exit):
                    in_references = False
                    blocks.append(Block(type="heading", level=1, title=stripped_for_exit))
                    continue
                # 附录标题检测（"附录"、"附  录"、"Appendix"、"附录一:xxx"、"附录二：xxx" 等）
                if re.match(r"^\s*(附\s*录[一二三四五六七八九十\d]*\s*[:：]?.*|Appendix\s*[A-Z\d]*\s*[:：]?.*)$", stripped_for_exit, re.IGNORECASE):
                    in_references = False
                    blocks.append(Block(type="heading", level=1, title=stripped_for_exit))
                    continue
                if _REF_ITEM_RE.match(text):
                    blocks.append(Block(
                        type="reference-item",
                        content=text.strip(),
                        data={"ref_number": int(_REF_ITEM_RE.match(text).group(1))},
                    ))
                    continue
                # 整条被方括号包裹的参考文献：[作者. 标题[J]. 期刊, 年份.]
                if _REF_BRACKETED_RE.match(text.strip()):
                    inner = _REF_BRACKETED_RE.match(text.strip()).group(1).strip()
                    # 编号留空，由 process_lunwen_v4 自动分配（= 当前 ref 计数 + 1）
                    blocks.append(Block(
                        type="reference-item",
                        content=inner,
                        data={"ref_number": None, "bracketed": True},
                    ))
                    continue
                # 非编号行：先用精细启发式规则拆分，再按规则追加/合并
                _split_and_append_refs(text.strip(), blocks)
                continue

            # 图片 caption: 若前方最近一个 image block 还未设置 caption，且文本是图片 caption 形式
            is_caption = False
            cap = _try_parse_figure_caption(text)
            if cap is not None and blocks and blocks[-1].type == "image" and not blocks[-1].data.get("caption"):
                blocks[-1].data["caption"] = cap
                # 同步更新 image_obj
                if blocks[-1].idx in extracted_images:
                    extracted_images[blocks[-1].idx].caption = cap
                is_caption = True
            if is_caption:
                continue

            # 表格 caption
            cap_tbl = _try_parse_table_caption(text)
            if cap_tbl is not None:
                # 向后查找最近的空 caption table block
                found = False
                for look_idx in range(len(blocks) - 1, -1, -1):
                    cand = blocks[look_idx]
                    if cand.type == "table" and not cand.data.get("caption"):
                        cand.data["caption"] = cap_tbl
                        if cand.idx in tables_final:
                            tables_final[cand.idx].caption = cap_tbl
                        found = True
                        break
                if not found:
                    # 向后看 raw_items 中后续是否有 table_raw
                    for next_idx in range(idx + 1, min(idx + 3, len(raw_items))):
                        if raw_items[next_idx]["kind"] == "table_raw":
                            # 记录到该 table 的数据里，稍后插入时会带上
                            raw_items[next_idx]["pending_caption"] = cap_tbl
                            found = True
                            break
                if found:
                    continue

            # Word 原文目录过滤：检测到"目  录"标题后，跳过目录条目
            stripped_text = text.strip()
            if _TOC_HEADING_RE.match(stripped_text):
                in_toc = True
                continue  # 跳过目录标题本身
            if in_toc:
                # 在目录模式下：先检查是否是 heading 或特殊标题（退出目录模式）
                lv_check = _detect_heading_level(style, text)
                is_special = (_ABSTRACT_RE.match(stripped_text) or
                              _REFS_HEADING_RE.match(stripped_text) or
                              _ACK_RE.match(stripped_text) or
                              _TOC_HEADING_RE.match(stripped_text))
                if lv_check > 0 or is_special:
                    # 遇到真正的标题，退出目录模式
                    in_toc = False
                    # 不 continue，继续往下处理
                elif len(stripped_text) > 50:
                    # 长文本（>50字符），是正文，退出目录模式
                    in_toc = False
                    # 不 continue，继续往下处理
                else:
                    # 短文本（<=50字符），认为是目录条目，跳过
                    continue

            # heading 识别
            lv = _detect_heading_level(style, text)
            if lv > 0:
                blocks.append(Block(type="heading", level=lv, title=text.strip()))
                continue

            # 论文标题（第一段非空且非 heading 的文本）：先去除BOM，再去除 markdown "# "前缀
            if not blocks and text:
                clean = text.replace("\ufeff", "").strip()
                clean = re.sub(r"^#+\s*", "", clean).strip()
                blocks.append(Block(type="title", content=clean))
                continue

            # 摘要：区分中文摘要和英文摘要
            if _ABSTRACT_RE.match(text):
                stripped = text.strip()
                if re.match(r"^\s*摘\s*要\s*$", stripped):
                    blocks.append(Block(type="abstract", content=stripped))
                else:
                    blocks.append(Block(type="abstract-en", content=stripped))
                continue

            # 摘要内容（以"摘要："开头的段落，将"摘要："作为标题，剩余内容作为摘要正文）
            m_abstract_body = re.match(r"^\s*摘\s*要\s*[:：]\s*(.+)$", text)
            if m_abstract_body and not any(b.type == "abstract" for b in blocks):
                blocks.append(Block(type="abstract", content="摘要"))
                blocks.append(Block(type="text", content=m_abstract_body.group(1).strip()))
                continue

            # 英文摘要内容（以"Abstract:"开头的段落）
            m_abstract_en_body = re.match(r"^\s*(Abstract|ABSTRACT)\s*[:：]\s*(.+)$", text, re.IGNORECASE)
            if m_abstract_en_body and not any(b.type == "abstract-en" for b in blocks):
                blocks.append(Block(type="abstract-en", content=m_abstract_en_body.group(1)))
                blocks.append(Block(type="text", content=m_abstract_en_body.group(2).strip()))
                continue

            # 参考文献区标题
            if _REFS_HEADING_RE.match(text):
                blocks.append(Block(type="references-heading", level=1, title=text.strip()))
                in_references = True
                continue

            # 致谢
            if _ACK_RE.match(text):
                blocks.append(Block(type="heading", level=1, title=text.strip()))
                continue

            # 论文末尾的声明类独立标题（如"人工智能辅助声明"、"数据可用性声明"等）
            if _DECLARATION_RE.match(text):
                blocks.append(Block(type="text", content=text.strip()))
                continue

            # 默认 text
            # 将富文本信息传递给 block
            block_data = {}
            if "rich_segments" in item:
                block_data["rich_segments"] = item["rich_segments"]
            if "dominant_color" in item:
                block_data["dominant_color"] = item["dominant_color"]
            if item.get("formulas"):
                block_data["formulas"] = item["formulas"]
            blocks.append(Block(
                type="text",
                content=text.strip(),
                data=block_data if block_data else {}
            ))

        elif item["kind"] == "table_raw":
            cap = item.get("pending_caption", "")
            table = DocxTable(
                idx=item["idx"],
                headers=item["headers"],
                rows=item["rows"],
                caption=cap,
                paragraph_index=item["paragraph_index"],
            )
            tables_final[item["idx"]] = table
            blocks.append(Block(
                type="table",
                idx=item["idx"],
                data={"table_obj": table, "caption": cap},
            ))

    # 7) 向后兼容 text 字段
    compat_lines: List[str] = []
    for b in blocks:
        if b.type == "title":
            compat_lines.append(b.content)
        elif b.type == "heading":
            compat_lines.append(b.title)
        elif b.type == "text":
            compat_lines.append(b.content)
        elif b.type == "image":
            compat_lines.append(f"[IMAGE:{b.idx}]")
        elif b.type == "table":
            compat_lines.append(f"[TABLE:{b.idx}]")
        elif b.type in ("abstract", "abstract-en"):
            compat_lines.append(b.content)
        elif b.type == "keywords":
            compat_lines.append(b.content)
        elif b.type == "references-heading":
            compat_lines.append(b.title)
        elif b.type == "reference-item":
            compat_lines.append(b.content)

    text = "\n\n".join(cl for cl in compat_lines if cl)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    return DocumentContent(
        blocks=blocks,
        text=text,
        images=list(extracted_images.values()),
        tables=list(tables_final.values()),
        source_file=file_path,
    )


# ============================================================
# 表格 XML 解析
# ============================================================
def _parse_table_xml(tbl_xml: str):
    """从 <w:tbl>...</w:tbl> 中提取行列，支持合并单元格"""
    tr_re = re.compile(r"<w:tr\b.*?</w:tr>", re.DOTALL)
    tc_re = re.compile(r"<w:tc\b.*?</w:tc>", re.DOTALL)
    t_re = re.compile(r"<w:t[^>]*>([^<]*)</w:t>", re.IGNORECASE)
    gridspan_re = re.compile(r"<w:gridSpan\b[^>]*w:val=\"(\d+)\"", re.IGNORECASE)
    vmerge_re = re.compile(r"<w:vMerge\b[^>]*(?:w:val=\"(\w+)\")?", re.IGNORECASE)

    rows_xml = tr_re.findall(tbl_xml)
    if not rows_xml:
        return [], []

    parsed_rows = []
    for row_xml in rows_xml:
        cells_xml = tc_re.findall(row_xml)
        if not cells_xml:
            continue
        
        # 检查是否有 vMerge（垂直合并）的单元格需要处理
        cell_texts = []
        for cell_xml in cells_xml:
            texts = t_re.findall(cell_xml)
            text = "".join(texts).strip()
            
            # 检查 gridSpan：跨越多列的单元格需要重复文本
            gridspan = gridspan_re.search(cell_xml)
            if gridspan:
                span = int(gridspan.group(1))
                cell_texts.extend([text] * span)
            else:
                cell_texts.append(text)
        
        if any(cell_texts):
            parsed_rows.append(cell_texts)

    if not parsed_rows:
        return [], []
    
    # 返回第一行作为 headers，其余作为数据行
    return parsed_rows[0], parsed_rows[1:]


# ============================================================
# 辅助：标题层级识别
# ============================================================
def _detect_heading_level(para_style: str, para_text: str) -> int:
    """返回 0 表示非标题。"""
    if para_style:
        key = para_style.strip().lower()
        m = re.search(r"heading\s*(\d+)|标题\s*(\d+)|一级标题|二级标题|三级标题", key)
        if m:
            if m.group(1):
                return int(m.group(1))
            if m.group(2):
                return int(m.group(2))
            if "一级" in key:
                return 1
            if "二级" in key:
                return 2
            if "三级" in key:
                return 3

    # 日期/年份过滤："20 10 届"、"2010 年 6月" 不是标题
    if _DATE_LIKE_RE.match(para_text.strip()):
        return 0

    # 目录条目过滤：编号开头 + 末尾页码（1-3位数字）→ 不是标题
    stripped = para_text.strip()
    if re.match(r"^[一二三四五六七八九十\d]+[、.\s　].+\d{1,3}$", stripped):
        # 但 "1.1、工程名称" 这种末尾无纯数字的不会被过滤
        # 只有末尾是纯数字（页码）的才过滤
        tail = re.search(r"(\d{1,3})$", stripped)
        head = stripped[:-len(tail.group(1))].rstrip() if tail else ""
        if head and not re.search(r"[）)\]]$", head):
            return 0

    # 正文编号列表项过滤："1、内容：长文本" / "2.1 内容：长文本" → 不是标题
    if re.match(r"^(\d+(?:\.\d+)*)[、.\s　].+[:：].{10,}", stripped):
        return 0

    # 数字编号启发式 "1 引言" / "1.1 小节" / "1.研究背景" / "1.1、标题"（支持中文句号和顿号）
    m = re.match(r"^(\d+(?:\.\d+){0,3})[\s.．、](.+)$", stripped)
    if m:
        after_num = m.group(2).strip()
        num_part = m.group(1)
        # 如果数字后紧跟单位，不是标题
        if _UNIT_AFTER_NUM_RE.match(after_num):
            return 0
        # 长文本过滤：编号后超过30字符 → 合同条款，不是标题
        if len(after_num) > 30:
            return 0
        # 句末标点过滤：标题不以句号/分号结尾
        if re.search(r"[。；;]$", after_num):
            return 0
        # 冒号结尾过滤：标题不以冒号结尾（通常是列表引导句）
        if re.search(r"[:：]$", after_num):
            return 0
        # 逗号+长度过滤：含逗号且超过20字符 → 是句子，不是标题
        if ("，" in after_num or "," in after_num) and len(after_num) > 20:
            return 0
        # 合同条款子项过滤：单数字编号（如"1 材料验收"）+ 内容含"验收"/"制度"等词
        # 这些是条款内的子项，不是独立章节标题（论文一级标题用中文编号"一、二"）
        if re.match(r"^\d+$", num_part) and len(after_num) <= 20:
            if re.search(r"(验收|制度|规范|清单|一览表|方案|标准)", after_num):
                return 0
        dots = m.group(1).count(".")
        # 中文论文：纯数字编号（如"1. 小车"）默认为 level=2，而非 level=1
        # 因为中文论文的一级标题通常是中文编号（一、二、三）
        # 只有带子编号的（如"1.1 xxx"）才根据点数确定层级
        if dots == 0:
            # "1 xxx" 形式 → level=2（二级标题）
            return 2
        return min(dots + 2, 4)

    # 中文编号标题："一、项目概况" / "二、研究大纲" / "二．设计流程" → level=1
    m_cn = re.match(r"^([一二三四五六七八九十]+)[、.\s　．](.+)$", stripped)
    if m_cn:
        after_cn = m_cn.group(2).strip()
        # 长文本过滤
        if len(after_cn) > 30:
            return 0
        # 句末标点过滤
        if re.search(r"[。；;]$", after_cn):
            return 0
        # 冒号结尾过滤
        if re.search(r"[:：]$", after_cn):
            return 0
        # 逗号+长度过滤
        if ("，" in after_cn or "," in after_cn) and len(after_cn) > 20:
            return 0
        return 1

    # 中文括号编号标题："（一）xxx" / "（二）xxx" → level=2
    m_cn_paren = re.match(r"^[（(]([一二三四五六七八九十]+)[）)]\s*(.+)$", stripped)
    if m_cn_paren:
        after_cn = m_cn_paren.group(2).strip()
        if len(after_cn) > 30:
            return 0
        if re.search(r"[。；;]$", after_cn):
            return 0
        if re.search(r"[:：]$", after_cn):
            return 0
        if ("，" in after_cn or "," in after_cn) and len(after_cn) > 20:
            return 0
        return 2

    # 数字括号编号标题："（1）xxx" / "(2) xxx" → level=3
    m_num_paren = re.match(r"^[（(](\d+)[）)]\s*(.+)$", stripped)
    if m_num_paren:
        after_num = m_num_paren.group(2).strip()
        if len(after_num) > 30:
            return 0
        if re.search(r"[。；;]$", after_num):
            return 0
        if re.search(r"[:：]$", after_num):
            return 0
        if ("，" in after_num or "," in after_num) and len(after_num) > 20:
            return 0
        return 3

    # 附录标题："附录"、"附录一:xxx"、"附录二：xxx"、"Appendix A" 等 → level=1
    if re.match(r"^\s*(附\s*录[一二三四五六七八九十\d]*\s*[:：]?.*|Appendix\s*[A-Z\d]*\s*[:：]?.*)$", stripped, re.IGNORECASE):
        return 1

    return 0


# ============================================================
# 辅助：caption 解析
# ============================================================
def _try_parse_figure_caption(text: str) -> Optional[str]:
    m = _FIGURE_CAPTION_RE.match(text.strip())
    if m:
        return m.group(1).strip()
    return None


def _try_parse_table_caption(text: str) -> Optional[str]:
    m = _TABLE_CAPTION_RE.match(text.strip())
    if m:
        return m.group(1).strip()
    return None


# ============================================================
# .txt 解析
# ============================================================
def _parse_text_blocks(content: str) -> List[Block]:
    lines = content.split("\n")
    blocks: List[Block] = []
    in_refs = False

    for line in lines:
        line = line.strip()
        if not line:
            continue

        if not blocks and line:
            clean = re.sub(r"^#\s*", "", line).replace("\ufeff", "").strip()
            blocks.append(Block(type="title", content=clean))
            continue

        if _REFS_HEADING_RE.match(line):
            blocks.append(Block(type="references-heading", level=1, title=line))
            in_refs = True
            continue

        if in_refs:
            m = _REF_ITEM_RE.match(line)
            if m:
                blocks.append(Block(type="reference-item", content=line.strip(),
                                     data={"ref_number": int(m.group(1))}))
                continue

        lv = _detect_heading_level("", line)
        if lv > 0:
            blocks.append(Block(type="heading", level=lv, title=line))
            continue

        blocks.append(Block(type="text", content=line))
    return blocks
