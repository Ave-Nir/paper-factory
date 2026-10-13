# -*- coding: utf-8 -*-
r"""
Markdown 文档读取器 (核心 skill 组件)

输入：.md 文件路径
输出：DocumentContent 对象
    - .blocks: 按原文顺序的结构化块列表
    - .text: 向后兼容的纯文本拼接
    - .images: 从 md 提取的图片列表（目前为空）
    - .tables: 从 md 提取的表格列表
    - .source_file

Block 类型定义与 document_reader.py 保持完全一致:
    title, heading(level), abstract, abstract-en, keywords,
    text, image, table, references-heading, reference-item

设计原则:
    1. 使用正则和行状态机在 markdown 文本上精确拆分段落与表格
    2. 按原文顺序保持 blocks 顺序
    3. 表格通过 | 分隔符解析，自动识别 header 分隔行
    4. 支持 $$...$$ 块级公式、``` 代码块、> 引用块、列表等
"""

import os
import re
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

from .document_reader import Block, DocxImage, DocxTable, DocumentContent


# ============================================================
# Markdown 解析核心
# ============================================================

_HEADING_RE = re.compile(r'^(#{1,6})\s+(.+?)\s*#*\s*$')
_TABLE_ROW_RE = re.compile(r'^\s*\|(.+)\|\s*$')
_TABLE_SEP_RE = re.compile(r'^[\s|:\-]+$')
_ORDERED_LIST_RE = re.compile(r'^(\s*)(\d+)\.\s+(.+)$')
_UNORDERED_LIST_RE = re.compile(r'^(\s*)[-*+]\s+(.+)$')
_FENCE_OPEN_RE = re.compile(r'^```(\w*)\s*$')
_FENCE_CLOSE_RE = re.compile(r'^```\s*$')
_BLOCK_MATH_OPEN_RE = re.compile(r'^\$\$\s*$')
_BLOCK_MATH_CLOSE_RE = re.compile(r'\$\$\s*$')
_QUOTE_RE = re.compile(r'^>\s*(.+)$')
_HR_RE = re.compile(r'^[-*_]{3,}\s*$')
_REFERENCE_ITEM_RE = re.compile(r'^\s*\[(\d+)\]\s+(.+)$')
_REFERENCES_HEADING_RE = re.compile(r'^(参考资料|参考文献|References|Bibliography|Bibliography\s*:?)\s*$', re.I)
_IMAGE_RE = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')

# 特殊声明标题关键词
_DECLARATION_RE = re.compile(
    r"^\s*("
    r"人工智能辅助声明|AI\s*辅助声明|AI辅助声明|"
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

# 致谢
_ACK_RE = re.compile(r"^\s*(致\s*谢|Acknowledg?ments?)\s*[:：]?\s*$", re.IGNORECASE)
# 附录
_APPENDIX_RE = re.compile(r"^\s*(附\s*录|Appendix)\s*[:：]?\s*$", re.IGNORECASE)

# 目录标题和条目
_TOC_HEADING_RE = re.compile(r"^\s*(目\s*录|Contents?)\s*[:：]?\s*$", re.IGNORECASE)
_TOC_ENTRY_RE = re.compile(r".+\.{2,}\s*\d{1,3}$|.{2,}\s+\d{1,3}$")


def _parse_table_row(line: str) -> List[str]:
    """解析单个 markdown 表格行"""
    content = line.strip()
    # 去除首尾 |
    if content.startswith('|'):
        content = content[1:]
    if content.endswith('|'):
        content = content[:-1]
    cells = content.split('|')
    return [c.strip() for c in cells]


def _is_table_separator(cells: List[str]) -> bool:
    """判断是否为 markdown 表格分隔行（|---|---|）"""
    if not cells:
        return False
    for c in cells:
        c = c.strip()
        if not c:
            return False
        # 必须只包含 : 和 -
        if not re.match(r'^:?-{2,}:?$|^-+$', c):
            return False
    return True


def _convert_md_bold_to_latex(text: str) -> str:
    """将 Markdown **bold** 语法转换为 LaTeX \\textbf{bold}。

    V7.7: 解决 Word 输出中显示 ** 包裹文本的问题。
    Markdown 的 **bold** 语法需要转换为 LaTeX 的 \\textbf{bold}，
    这样 LaTeXHumanizer 可以正确识别并渲染为 Word 粗体格式。

    注意：不处理已经包裹在 $...$ 中的 **，因为那是 LaTeX 数学模式。
    """
    if not text or '**' not in text:
        return text

    # 先提取所有 $...$ 和 $$...$$ 区域，避免处理数学模式中的 **
    math_regions = []
    # 匹配 $$...$$ (块级公式) - 使用更稳健的匹配方式
    # 处理单行和多行的 $$ 块
    i = 0
    while i < len(text):
        if text[i:i+2] == '$$':
            # 找到开始的 $$
            start = i
            # 查找结束的 $$
            j = i + 2
            while j < len(text):
                if text[j:j+2] == '$$':
                    # 找到结束的 $$
                    math_regions.append((start, j + 2))
                    i = j + 2
                    break
                j += 1
            else:
                # 没有找到结束的 $$，跳过
                i += 2
        else:
            i += 1

    # 匹配 $...$ (行内公式) - 不匹配 $$
    for m in re.finditer(r'(?<!\$)\$(?!\$)([^$]+?)\$(?!\$)', text):
        # 确保这个 $...$ 不在已识别的 $$ 块内
        start, end = m.start(), m.end()
        in_math_block = False
        for ms, me in math_regions:
            if ms <= start and end <= me:
                in_math_block = True
                break
        if not in_math_block:
            math_regions.append((start, end))

    # 按起始位置排序
    math_regions.sort(key=lambda x: x[0])

    # 构建结果：保留数学区域，转换其他区域的 **bold**
    result = []
    last_end = 0

    for start, end in math_regions:
        # 处理数学区域之前的文本
        if start > last_end:
            segment = text[last_end:start]
            segment = re.sub(r'\*\*([^*]+?)\*\*', r'\\textbf{\1}', segment)
            result.append(segment)
        # 保留数学区域原样
        result.append(text[start:end])
        last_end = end

    # 处理最后一个数学区域之后的文本
    if last_end < len(text):
        segment = text[last_end:]
        segment = re.sub(r'\*\*([^*]+?)\*\*', r'\\textbf{\1}', segment)
        result.append(segment)

    return ''.join(result)


def read_markdown(md_path: str) -> DocumentContent:
    """读取 Markdown 文件，返回 DocumentContent 对象。

    与 document_reader.py 的 read_document() 保持相同输出格式，
    这样 WordBuilder、LaTeXBuilder 等组件可以无缝复用。
    """
    # 读取文件（UTF-8）
    with open(md_path, 'r', encoding='utf-8') as f:
        raw_lines = f.readlines()

    # 规范化行结尾
    lines = [line.rstrip('\n') for line in raw_lines]

    # 剥离 YAML front matter：首行 --- 至下一个 --- 之间的元数据段。
    # 该段是 artifact 元信息而非论文正文，不剥离会被当作正文渲染进 PDF/Word
    if lines and lines[0].strip() == '---':
        for _fm_idx in range(1, len(lines)):
            if lines[_fm_idx].strip() == '---':
                lines = lines[_fm_idx + 1:]
                break

    # 初始化输出结构
    blocks: List[Block] = []
    tables: List[DocxTable] = []
    images: List[DocxImage] = []
    idx_counter = 0
    table_counter = 0

    # 状态机
    state = "normal"       # normal / table / code / math / quote
    buffer: List[str] = []
    table_headers: List[str] = []
    table_rows: List[List[str]] = []

    def flush_paragraph(buf: List[str]) -> None:
        """将累积的普通段落文本生成一个 text block"""
        if not buf:
            return
        text = '\n'.join(buf).strip()
        if text:
            # V7.7: 将 Markdown **bold** 语法转换为 LaTeX \textbf{bold}
            # 这样 LaTeXHumanizer 可以正确处理并渲染为 Word 粗体
            text = _convert_md_bold_to_latex(text)
            blocks.append(Block(type="text", content=text))

    def flush_table() -> None:
        """将累积的表格生成 table block"""
        nonlocal table_counter
        if not table_headers and not table_rows:
            return
        table_counter += 1
        table_obj = DocxTable(
            idx=table_counter,
            headers=list(table_headers),
            rows=[list(r) for r in table_rows],
            caption=""
        )
        tables.append(table_obj)
        blocks.append(Block(
            type="table",
            idx=table_counter,
            data={"table_obj": table_obj, "caption": ""}
        ))

    def flush_code(buf: List[str]) -> None:
        """将累积的代码块生成 text block（作为等宽文本）"""
        if not buf:
            return
        code = '\n'.join(buf)
        blocks.append(Block(type="text", content=code, data={"is_code": True}))

    def flush_math(buf: List[str]) -> None:
        """将累积的块级公式生成 text block"""
        if not buf:
            return
        math_content = '\n'.join(buf).strip()
        # V7.7: 在块级公式中，将 Markdown **bold** 语法转换为 LaTeX \textbf{bold}
        # 这样 LaTeXHumanizer 可以正确处理并渲染为 Word 粗体
        # 注意：只处理公式块外的文本部分，不处理公式内部
        math_content = _convert_md_bold_to_latex(math_content)
        math = '$' + '$' + math_content + '$' + '$'
        blocks.append(Block(type="text", content=math, data={"is_math": True}))

    in_references = False
    in_toc = False

    for line_no, line in enumerate(lines):
        stripped = line.strip()

        # --- 状态转换 ---

        if state == "code":
            if _FENCE_CLOSE_RE.match(stripped):
                flush_code(buffer)
                buffer = []
                state = "normal"
                continue
            buffer.append(line)
            continue

        if state == "math":
            if _BLOCK_MATH_CLOSE_RE.match(stripped):
                flush_math(buffer)
                buffer = []
                state = "normal"
                continue
            buffer.append(line)
            continue

        if state == "table":
            # 继续解析表格行，直到空行或非表格行
            if _TABLE_ROW_RE.match(stripped):
                cells = _parse_table_row(stripped)
                # 跳过 separator row（header已经处理）
                if not _is_table_separator(cells):
                    table_rows.append(cells)
                continue
            else:
                # 表格结束
                flush_table()
                table_headers = []
                table_rows = []
                state = "normal"
                # 让当前行被正常解析

        # --- 普通状态 ---

        # 1) 空行：结束当前段落
        if not stripped:
            flush_paragraph(buffer)
            buffer = []
            continue

        # 2) 水平分隔线 ---
        if _HR_RE.match(stripped):
            flush_paragraph(buffer)
            buffer = []
            continue

        # 3) 代码块开始 ```
        if _FENCE_OPEN_RE.match(stripped):
            flush_paragraph(buffer)
            buffer = []
            state = "code"
            continue

        # 4) 块级公式 $$
        if _BLOCK_MATH_OPEN_RE.match(stripped) and line_no + 1 < len(lines):
            # 更安全的判断：下一行是否也有 $$ 作为闭合，或者后面有内容
            flush_paragraph(buffer)
            buffer = []
            state = "math"
            continue

        # 5) 标题
        heading_match = _HEADING_RE.match(line)
        if heading_match:
            flush_paragraph(buffer)
            buffer = []

            hashes = heading_match.group(1)  # "##"
            title_text = heading_match.group(2).strip()
            # V7.7: 标题中的 **bold** 不在这里转换，而是在 WordBuilder 中直接处理
            # 这样标题可以正确渲染为 Word 粗体格式

            level = len(hashes)  # 1=h1, 2=h2, 3=h3

            # 第一层 # 作为文档标题
            if level == 1:
                blocks.append(Block(type="title", content=title_text))
            else:
                # 其余为章节
                heading_level = level - 1  # h2→level1, h3→level2, h4→level3
                heading_level = min(max(heading_level, 1), 4)

                if _REFERENCES_HEADING_RE.match(title_text) or "参考" in title_text or "References" in title_text:
                    in_references = True
                    blocks.append(Block(
                        type="references-heading",
                        level=heading_level,
                        title=title_text
                    ))
                elif _ACK_RE.match(title_text):
                    blocks.append(Block(
                        type="heading",
                        level=heading_level,
                        title=title_text,
                        content=title_text,
                        data={"is_acknowledgements": True}
                    ))
                elif _APPENDIX_RE.match(title_text):
                    blocks.append(Block(
                        type="heading",
                        level=heading_level,
                        title=title_text,
                        content=title_text,
                        data={"is_appendix": True}
                    ))
                elif _DECLARATION_RE.match(title_text):
                    blocks.append(Block(
                        type="heading",
                        level=heading_level,
                        title=title_text,
                        content=title_text,
                        data={"is_declaration": True}
                    ))
                elif _TOC_HEADING_RE.match(title_text):
                    in_toc = True
                    continue
                else:
                    blocks.append(Block(
                        type="heading",
                        level=heading_level,
                        title=title_text,
                        content=title_text
                    ))
            continue

        # 6) 图片 ![alt](path)
        image_match = _IMAGE_RE.search(line)
        if image_match:
            flush_paragraph(buffer)
            buffer = []
            alt_text = image_match.group(1)
            img_path = image_match.group(2)
            # 解析相对路径（相对于 md 文件所在目录）
            import os
            abs_img_path = os.path.join(os.path.dirname(md_path), img_path)
            if os.path.exists(abs_img_path):
                idx_counter += 1
                ext = os.path.splitext(abs_img_path)[1].lstrip('.').lower() or 'png'
                try:
                    from PIL import Image
                    with Image.open(abs_img_path) as im:
                        w, h = im.size
                except Exception:
                    w, h = 0, 0
                img_obj = DocxImage(
                    idx=idx_counter,
                    extracted_path=abs_img_path,
                    width=w,
                    height=h,
                    caption=alt_text,
                )
                images.append(img_obj)
                blocks.append(Block(
                    type="image",
                    idx=idx_counter,
                    data={"image_obj": img_obj, "caption": alt_text}
                ))
            else:
                blocks.append(Block(type="text", content=f"[Image: {alt_text} ({img_path} - not found)]"))
            continue

        # 7) 表格检测
        if _TABLE_ROW_RE.match(stripped):
            # 可能是表格开始：检查下一行是否是分隔符
            first_cells = _parse_table_row(stripped)
            if line_no + 1 < len(lines) and _TABLE_ROW_RE.match(lines[line_no + 1].strip()):
                second_cells = _parse_table_row(lines[line_no + 1].strip())
                if _is_table_separator(second_cells):
                    # 确认是表格
                    flush_paragraph(buffer)
                    buffer = []
                    table_headers = first_cells
                    table_rows = []
                    state = "table"
                    # 跳过已消耗的两行
                    # 注意：由于我们在 line_no 处理，下一行(line_no+1) 是分隔符，
                    # 会被状态机在下次循环识别为表格并跳过
                    # 但分隔符应该被跳过 - 让我们在状态内处理
                    continue

        # 7) 引用块 >
        if _QUOTE_RE.match(line):
            flush_paragraph(buffer)
            buffer = []
            quote_text = _QUOTE_RE.match(line).group(1)
            blocks.append(Block(type="text", content=quote_text, data={"is_quote": True}))
            continue

        # 8) 参考文献条目（如果在参考文献章节）
        if in_references:
            ref_match = _REFERENCE_ITEM_RE.match(stripped)
            if ref_match:
                flush_paragraph(buffer)
                buffer = []
                ref_num = int(ref_match.group(1))
                ref_text = ref_match.group(2).strip()
                blocks.append(Block(
                    type="reference-item",
                    content=ref_text,
                    idx=ref_num,
                    data={"ref_number": ref_num}
                ))
            else:
                if stripped:
                    if blocks and blocks[-1].type == "reference-item":
                        blocks[-1].content += " " + stripped
                    else:
                        flush_paragraph(buffer)
                        buffer = []
                        blocks.append(Block(type="text", content=stripped))
            continue

        # 9) 有序列表（简单处理：合并为普通段落）
        if _ORDERED_LIST_RE.match(line):
            flush_paragraph(buffer)
            buffer = []
            m = _ORDERED_LIST_RE.match(line)
            indent = m.group(1)
            num = m.group(2)
            item_text = m.group(3)
            # V7.7: 将 Markdown **bold** 语法转换为 LaTeX \textbf{bold}
            item_text = _convert_md_bold_to_latex(item_text)
            blocks.append(Block(type="text", content=f"{num}. {item_text}"))
            continue

        # 10) 无序列表（简单处理：合并为普通段落）
        if _UNORDERED_LIST_RE.match(line):
            flush_paragraph(buffer)
            buffer = []
            m = _UNORDERED_LIST_RE.match(line)
            indent = m.group(1)
            item_text = m.group(2)
            # V7.7: 将 Markdown **bold** 语法转换为 LaTeX \textbf{bold}
            item_text = _convert_md_bold_to_latex(item_text)
            blocks.append(Block(type="text", content=f"• {item_text}"))
            continue

        # 11) 目录条目跳过（当检测到目录标题后）
        if in_toc and _TOC_ENTRY_RE.match(stripped):
            continue

        # 12) 非标题形式的特殊声明（正文行）
        if _DECLARATION_RE.match(stripped):
            flush_paragraph(buffer)
            buffer = []
            blocks.append(Block(
                type="heading",
                level=1,
                title=stripped.strip(),
                content=stripped.strip(),
                data={"is_declaration": True}
            ))
            continue

        # 13) 非标题形式的致谢（正文行）
        if _ACK_RE.match(stripped):
            flush_paragraph(buffer)
            buffer = []
            blocks.append(Block(
                type="heading",
                level=1,
                title=stripped.strip(),
                content=stripped.strip(),
                data={"is_acknowledgements": True}
            ))
            continue

        # 14) 非标题形式的附录（正文行）
        if _APPENDIX_RE.match(stripped):
            flush_paragraph(buffer)
            buffer = []
            blocks.append(Block(
                type="heading",
                level=1,
                title=stripped.strip(),
                content=stripped.strip(),
                data={"is_appendix": True}
            ))
            continue

        # 15) 普通文本段落
        buffer.append(line)

    # --- 循环结束，清理剩余状态 ---
    flush_paragraph(buffer)
    if state == "table":
        flush_table()
    elif state == "code":
        flush_code(buffer)
    elif state == "math":
        flush_math(buffer)

    # 生成纯文本
    plain_text = '\n'.join(b.content for b in blocks if b.type == "text")

    return DocumentContent(
        blocks=blocks,
        text=plain_text,
        images=images,
        tables=tables,
        source_file=md_path
    )


# ============================================================
# 便捷入口
# ============================================================

def read_document_auto(path: str) -> DocumentContent:
    """根据文件扩展名自动选择读取器。

    - .docx → document_reader.read_document()
    - .md / .markdown → markdown_reader.read_markdown()
    """
    ext = os.path.splitext(path)[1].lower()
    if ext in ('.md', '.markdown'):
        return read_markdown(path)
    elif ext == '.docx':
        from .document_reader import read_document
        return read_document(path)
    else:
        raise ValueError(f"不支持的文件格式: {ext}（支持 .docx / .md / .markdown）")
