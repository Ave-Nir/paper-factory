"""
NL Output → DocumentContent 转换器

将 NLIntake 输出的 (PaperSpec, ReferenceDB, section_data_map)
转换为 DocumentContent，使其能够被 process_lunwen_v4.py 主流程消费。

约定：
- input_data 是 NLIntake.process() 的返回值
- 转换后的 DocumentContent.source_file 标识为 "nl_intake"
- 所有段落以 Block 形式呈现，type 取值与 document_reader 一致
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from .document_reader import Block, DocxImage, DocxTable, DocumentContent
from .types import PaperSpec, ReferenceDB


# ============================================================
# 区块类型映射
# ============================================================

# 中文 section → (Block.type, Block.level, 显示标题)
_CN_SECTION_MAP = {
    "chinese_abstract": ("abstract", 0, "摘 要"),
    "english_abstract": ("abstract-en", 0, "Abstract"),
    "related_work_cn": ("heading", 1, "研究背景与文献综述"),
    "research_content": ("heading", 1, "研究内容"),
    "research_basis": ("heading", 1, "研究基础"),
    "figures_tables_cn": ("heading", 1, "图表汇总"),
    "conclusion_cn": ("heading", 1, "结 论"),
    "acknowledgement_cn": ("heading", 1, "致 谢"),
    "references_cn": ("references-heading", 1, "参考文献"),
}

# 英文 section → (Block.type, Block.level, 显示标题)
_EN_SECTION_MAP = {
    "abstract": ("abstract-en", 0, "Abstract"),
    "introduction": ("heading", 1, "Introduction"),
    "related_work": ("heading", 1, "Related Work"),
    "method": ("heading", 1, "Method"),
    "experiments": ("heading", 1, "Experiments"),
    "conclusion": ("heading", 1, "Conclusion"),
    "acknowledgement": ("heading", 1, "Acknowledgement"),
    "references": ("references-heading", 1, "References"),
}


def _pick_section_map(language: str) -> Dict[str, tuple]:
    return _CN_SECTION_MAP if language == "chinese" else _EN_SECTION_MAP


# ============================================================
# 文本字段提取
# ============================================================

def _flatten_text(value: Any) -> str:
    """把 dict / list / str 全部转成可读文本。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "\n".join(_flatten_text(v) for v in value if v not in (None, "", []))
    if isinstance(value, dict):
        # 常见子字段
        for key in ("text", "content", "summary", "description", "value", "name", "title"):
            if key in value and isinstance(value[key], str):
                return value[key].strip()
        # fallback: 全字段拼接
        return "\n".join(_flatten_text(v) for v in value.values())
    return str(value)


def _block_from_section(
    section_name: str,
    section_data: Dict[str, Any],
    block_type: str,
    level: int,
    title: str,
    idx_start: int,
) -> List[Block]:
    """把 section 字典展开成 Block 列表。"""
    blocks: List[Block] = []
    idx = idx_start

    # 标题 block
    blocks.append(Block(
        type=block_type,
        level=level,
        title=title,
        content="",
        idx=idx,
    ))
    idx += 1

    # 主体内容
    if block_type in ("abstract", "abstract-en"):
        # abstract: 把所有字符串字段拼起来
        body = _flatten_text(section_data)
        if body:
            blocks.append(Block(
                type="text",
                level=0,
                title="",
                content=body,
                idx=idx,
            ))
            idx += 1
        return blocks

    if block_type == "references-heading":
        # references: 渲染 reference-heading 块，下面挂 references block
        return blocks

    # 普通 section：按字段顺序遍历
    if isinstance(section_data, dict):
        for key, value in section_data.items():
            if key in ("_language",):
                continue
            text = _flatten_text(value)
            if not text:
                continue
            # 长字段用子标题
            blocks.append(Block(
                type="text",
                level=2 if len(section_data) > 3 else 0,
                title="",
                content=text,
                idx=idx,
                data={"subsection": key},
            ))
            idx += 1
    else:
        text = _flatten_text(section_data)
        if text:
            blocks.append(Block(
                type="text",
                level=0,
                title="",
                content=text,
                idx=idx,
            ))
            idx += 1

    return blocks


# ============================================================
# 主转换函数
# ============================================================

def build_document_content(
    paper_spec: PaperSpec,
    ref_db: ReferenceDB,
    section_data_map: Dict[str, Any],
    language: Optional[str] = None,
) -> DocumentContent:
    """把 NLIntake 输出组装成 DocumentContent。

    Args:
        paper_spec: NLIntake.process() 返回的第一个值
        ref_db:     NLIntake.process() 返回的第二个值
        section_data_map: NLIntake.process() 返回的第三个值
        language:   "chinese" / "english" / None（自动推断）

    Returns:
        DocumentContent: 可被 process_lunwen_v4.py 主流程消费
    """
    # 语言推断
    if language is None:
        language = "chinese" if _looks_chinese(paper_spec) else "english"
    section_map = _pick_section_map(language)

    blocks: List[Block] = []
    idx = 0

    # 标题
    title = (paper_spec.get("title") or "").strip() or "Untitled"
    blocks.append(Block(type="title", level=0, title=title, content="", idx=idx))
    idx += 1

    # 作者
    authors = paper_spec.get("authors") or []
    if authors:
        author_lines = []
        for a in authors:
            if isinstance(a, dict):
                name = a.get("name") or a.get("full_name") or ""
                affil = a.get("affiliation") or a.get("affil") or ""
                email = a.get("email") or ""
                if name:
                    line = name
                    if affil:
                        line += f" ({affil})"
                    if email:
                        line += f" <{email}>"
                    author_lines.append(line)
            else:
                author_lines.append(str(a))
        if author_lines:
            blocks.append(Block(
                type="author",
                level=0,
                title="",
                content=", ".join(author_lines),
                idx=idx,
            ))
            idx += 1

    # 关键词
    keywords = paper_spec.get("keywords") or []
    if keywords:
        kw_text = ", ".join(str(k) for k in keywords)
        blocks.append(Block(
            type="keywords",
            level=0,
            title="关键词" if language == "chinese" else "Keywords",
            content=kw_text,
            idx=idx,
        ))
        idx += 1

    # 摘要（双语）
    abstract_obj = paper_spec.get("abstract")
    if isinstance(abstract_obj, dict):
        cn_abstract = abstract_obj.get("chinese") or abstract_obj.get("zh") or abstract_obj.get("cn")
        en_abstract = abstract_obj.get("english") or abstract_obj.get("en")
        if cn_abstract:
            section_data_map.setdefault("chinese_abstract", {"content": cn_abstract})
        if en_abstract:
            section_data_map.setdefault("english_abstract", {"content": en_abstract})

    # 遍历 section_data_map
    for section_name, section_data in section_data_map.items():
        if section_name == "original_sections":
            continue
        if section_name not in section_map:
            # 未知 section：作为普通 text
            text = _flatten_text(section_data)
            if text:
                blocks.append(Block(
                    type="text",
                    level=0,
                    title=section_name,
                    content=text,
                    idx=idx,
                ))
                idx += 1
            continue

        block_type, level, title_display = section_map[section_name]
        section_blocks = _block_from_section(
            section_name, section_data, block_type, level, title_display, idx,
        )
        blocks.extend(section_blocks)
        idx += len(section_blocks)

        # 参考文献块
        if block_type == "references-heading" and ref_db and len(ref_db) > 0:
            for ref_key in ref_db.entries:
                blocks.append(Block(
                    type="reference",
                    level=0,
                    title="",
                    content=f"[{ref_key}] {ref_db.entries[ref_key].get('fields', {}).get('title', ref_key)}",
                    idx=idx,
                    data={"ref_key": ref_key},
                ))
                idx += 1

    text_full = "\n\n".join(
        b.content for b in blocks if b.content
    )

    return DocumentContent(
        blocks=blocks,
        text=text_full,
        images=[],
        tables=[],
        source_file="nl_intake",
    )


def _looks_chinese(paper_spec: PaperSpec) -> bool:
    """从 PaperSpec 推断语言。"""
    venue = (paper_spec.get("venue") or "").lower()
    if any(k in venue for k in ("nsfc", "sci", "thesis", "humanities")):
        return True
    if any(k in venue for k in ("ieee", "neurips", "icml", "cvpr", "acl")):
        return False
    title = paper_spec.get("title") or ""
    return any("\u4e00" <= ch <= "\u9fff" for ch in title)


# ============================================================
# 序列化 / 反序列化（用于"先 LLM 生成 JSON，再跑排版"的两步模式）
# ============================================================

def serialize_intake_output(
    paper_spec: PaperSpec,
    ref_db: ReferenceDB,
    section_data_map: Dict[str, Any],
) -> Dict[str, Any]:
    """把 NLIntake 输出打包成可保存为 JSON 的字典。"""
    refs_serialized = []
    for key, entry in ref_db.entries.items():
        refs_serialized.append({
            "key": entry["key"],
            "entry_type": entry.get("entry_type", "misc"),
            "fields": entry.get("fields", {}),
        })
    return {
        "paper_spec": dict(paper_spec),
        "references": refs_serialized,
        "sections": dict(section_data_map),
    }


def deserialize_intake_output(data: Dict[str, Any]) -> Tuple[PaperSpec, ReferenceDB, Dict[str, Any]]:
    """从 JSON 字典还原 NLIntake 输出。"""
    paper_spec: PaperSpec = dict(data.get("paper_spec") or {})
    ref_db = ReferenceDB()
    for ref in data.get("references") or []:
        from .types import BibEntry
        ref_db.add(BibEntry(
            key=ref["key"],
            entry_type=ref.get("entry_type", "misc"),
            fields=ref.get("fields", {}),
        ))
    sections = dict(data.get("sections") or {})
    return paper_spec, ref_db, sections
