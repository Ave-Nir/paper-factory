"""
NL Intake Module —— 自然语言 → 结构化数据

这是架构中唯一使用 LLM 的步骤。用户提供纯文本描述，LLM 将其转为
严格类型化的 Python 数据结构，后续所有步骤均为纯代码驱动。

设计原则：
- 输入：用户用自然语言描述论文内容（自由格式）
- 输出：PaperSpec + ReferenceDB + section_data_map（严格类型化）
- LLM 的输出先经过 schema 验证，不合法则返回错误要求重新生成
- 支持增量模式：用户可分批提供内容，逐步填充
"""

import json
import re
from typing import Optional, Callable
from dataclasses import dataclass, field

from .types import (
    PaperSpec, Author, BibEntry, Claim, Contribution,
    IntroductionData, RelatedWorkData, MethodData, MethodSubSection,
    ExperimentData, ExperimentSubSection, ConclusionData, AbstractData,
    ReferenceDB, SectionData, Diagnostic, DiagnosticSeverity, GateReport,
)


# ============================================================================
# LLM 调用接口（可替换为任意 LLM backend）
# ============================================================================

@dataclass
class LLMResponse:
    content: str
    model: str = ""


LLMCallable = Callable[[str, str], LLMResponse]
"""LLM 调用函数签名：(system_prompt, user_prompt) -> LLMResponse"""


# ============================================================================
# 默认 LLM 实现（使用 OpenAI-compatible API）
# ============================================================================

class OpenAILLM:
    """基于 OpenAI-compatible API 的 LLM 实现"""
    
    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1",
                 model: str = "gpt-4o"):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model
    
    def __call__(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        try:
            import json
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.3,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            
            # 处理硅基流动等API返回的嵌套JSON格式
            # e.g. {"msg_type":"text","content":"{...json...}"}
            try:
                parsed = json.loads(content)
                if isinstance(parsed, dict):
                    # 如果返回是 {msg_type, content} 格式
                    if "content" in parsed and "msg_type" in parsed:
                        content = parsed["content"]
                    # 如果返回是正常的JSON对象（我们需要的格式），直接使用
                    else:
                        pass
            except (json.JSONDecodeError, TypeError):
                pass
            
            return LLMResponse(
                content=content,
                model=self.model,
            )
        except ImportError:
            raise ImportError("pip install openai required for OpenAILLM")


# ============================================================================
# NL Intake —— 核心转换器
# ============================================================================

# System prompt —— 定义输出 schema 和转换规则
INTAKE_SYSTEM_PROMPT = """YOU MUST PRESERVE ALL CONTENT FROM THE INPUT TEXT. NO INFORMATION CAN BE OMITTED.

You are a structured data extraction system for academic paper writing.
Your ONLY job is to convert natural language paper descriptions into a strict JSON format.

## CRITICAL MANDATE: COMPLETE CONTENT PRESERVATION
YOU MUST EXTRACT AND PRESERVE EVERY SENTENCE, PARAGRAPH, AND PIECE OF INFORMATION FROM THE INPUT TEXT.
- Do NOT summarize, condense, or shorten any content
- Include ALL sections: abstract, introduction, literature review, methodology, results, discussion, conclusion, acknowledgements, references
- Preserve exact wording from the input
- If the input contains acknowledgements/致谢, include them in the output
- If the input contains appendices, include them

## CRITICAL MANDATE: PRESERVE IMAGE PLACEHOLDERS
If the input text contains markers like "[IMAGE:1]", "[IMAGE:2]", etc.,
YOU MUST PRESERVE THEM VERBATIM in your JSON output.
- These markers stand for images from the original Word document
- Do NOT delete, summarize, or modify these markers
- Place the marker in the section that corresponds to the original text context
- If a marker appears inside a paragraph, keep it at the same relative position
  within that paragraph's content string

## CRITICAL MANDATE: PRESERVE TABLE PLACEHOLDERS
If the input text contains markers like "[TABLE:1]", "[TABLE:2]", etc.,
YOU MUST PRESERVE THEM VERBATIM in your JSON output.
- These markers stand for tables from the original Word document
- Do NOT delete, summarize, or modify these markers

## CRITICAL MANDATE: PRESERVE ORIGINAL SECTION STRUCTURE
ALWAYS include an "original_sections" field in your JSON output. This field preserves the original document structure exactly as it appears in the input text.

```json
{
  "sections": {
    "original_sections": [
      {
        "level": "chapter",
        "title": "string (EXACT heading text from input)",
        "content": "string (full content under this heading)",
        "subsections": [
          {
            "level": "section",
            "title": "string (subsection heading)",
            "content": "string",
            "subsections": []
          }
        ]
      }
    ]
  }
}
```

- "level" can be: "chapter", "section", "subsection", "paragraph"
- Output sections in the SAME ORDER as they appear in the input
- Use EXACT heading text from the input, do NOT translate or rename
- Every heading in the input must appear in original_sections
- Keep [IMAGE:N] and [TABLE:N] markers in place within content strings

## Step 1: Detect Language

First determine the source language of the user's input text:
- If the text is primarily in **Chinese** (contains Chinese characters), language = "chinese"
- If the text is primarily in **English**, language = "english"

## Step 2: Choose the correct output schema based on language

### IF language = "chinese" (中文论文，严格使用以下 sections):
Use ONLY these Chinese section keys. Do NOT output ANY English section keys.

```json
{
  "paper_spec": {
    "title": "string (论文标题，中文)",
    "venue": "one of: nsfc, sci, thesis, humanities",
    "field": "one of: humanities, general, cs_ml, cs_cv, cs_nlp, cs_ai, bio_informatics",
    "keywords": ["keyword1", "keyword2", ...]
  },
  "references": [
    {
      "key": "authorYearFirstword",
      "entry_type": "article | inproceedings | book | misc",
      "fields": {"author": "...", "title": "...", "year": "...", ...}
    }
  ],
  "sections": {
    "chinese_abstract": {
      "title": "string (通常为 '中文摘要')",
      "content": "string (完整保留原文中文摘要内容，不要删减)",
      "keywords": ["关键词1", "关键词2", ...]
    },
    "english_abstract": {
      "title": "string (通常为 'Abstract')",
      "content": "string (完整保留原文英文摘要内容，不要删减)",
      "keywords": ["keyword1", "keyword2", ...]
    },
    "related_work_cn": {
      "subsections": [
        {
          "title": "string (中文子标题，如国内外研究现状)",
          "works": [
            {"text": "string (中文，完整段落内容，保留所有参考文献引用)", "citation_keys": ["key1"]}
          ]
        }
      ]
    },
    "research_content": {
      "overview": "string (中文，研究内容概述)",
      "items": [
        {"title": "string (中文章节标题)", "detail": "string (完整章节内容，不要删减)"}
      ]
    },
    "research_basis": {
      "subsections": [
        {"title": "string (中文)", "content": "string (完整内容，保留所有细节)"}
      ]
    },
    "figures_tables_cn": {
      "figures": [],
      "tables": []
    },
    "conclusion_cn": {
      "summary": "string (中文，完整结论内容)",
      "innovations": ["创新点1", "创新点2", ...],
      "expected_outcomes": ["预期成果1", "预期成果2", ...]
    },
    "acknowledgement_cn": {
      "content": "string (完整致谢内容，如有则必须包含)"
    },
    "references_cn": {
      "bib_path": "references",
      "style": "gbt7714-numerical"
    }
  }
}
```

### ADDITIONAL SECTION: PRESERVE ORIGINAL STRUCTURE
To preserve the original document structure, you can also include an "original_sections" key in the sections object.
This is a list of sections in the order they appear in the original document.

```json
{
  "sections": {
    "original_sections": [
      {
        "level": "chapter",
        "title": "string (exact heading text from input)",
        "content": "string (full content under this heading)",
        "subsections": [
          {
            "level": "section",
            "title": "string (subsection heading)",
            "content": "string",
            "subsections": []
          }
        ]
      }
    ]
  }
}
```

- "level" can be: "chapter", "section", "subsection", "paragraph"
- Include ALL headings from the input document in original_sections
- This preserves the original structure even if other section keys are used

### IF language = "english" (英文论文，严格使用以下 sections):
Use ONLY these English section keys. Do NOT output ANY Chinese section keys.

```json
{
  "paper_spec": {
    "title": "string (paper title, in English)",
    "venue": "one of: neurips2024, icml2025, cvpr2024, acl2024, ieee",
    "field": "one of: cs_ml, cs_cv, cs_nlp, cs_ai, bio_informatics, general",
    "keywords": ["keyword1", "keyword2", ...]
  },
  "references": [
    {
      "key": "authorYearFirstword",
      "entry_type": "article | inproceedings | book | misc",
      "fields": {"author": "...", "title": "...", "year": "...", ...}
    }
  ],
  "sections": {
    "introduction": {
      "background": [
        {"text": "...", "citation_keys": ["key1"], "confidence": "established|emerging|speculative"}
      ],
      "problem_statement": "string",
      "research_gap": "string",
      "contributions": [
        {"text": "...", "evidence": "..."}
      ],
      "paper_structure": ["Section 2: ...", "Section 3: ..."]
    },
    "related_work": {
      "subsections": [
        {
          "topic": "string",
          "works": [
            {"text": "...", "citation_keys": ["key1"], "confidence": "established"}
          ]
        }
      ]
    },
    "method": {
      "overview": "string",
      "subsections": [
        {"title": "string", "content": "string", "equations": [], "figures": []}
      ],
      "algorithms": []
    },
    "experiments": {
      "subsections": [
        {
          "title": "string",
          "description": "string",
          "tables": [],
          "figures": [],
          "findings": [{"text": "...", "citation_keys": [], "confidence": "established"}]
        }
      ]
    },
    "conclusion": {
      "summary": "string",
      "limitations": ["string"],
      "future_work": ["string"]
    },
    "abstract": {
      "context": "string", "problem": "string", "approach": "string",
      "results": "string", "impact": "string"
    },
    "acknowledgement": {
      "content": "string"
    }
  }
}
```

## CRITICAL RULES (ENFORCE STRICTLY):
1. **COMPLETE CONTENT PRESERVATION**: Extract ALL information from the input. Do NOT omit, summarize, or condense ANY content. If the input has 10 paragraphs, your output must contain all 10 paragraphs.

2. **Language lock-in**: If input is Chinese, ONLY output Chinese section keys
   (chinese_abstract, related_work_cn, research_content, research_basis,
   figures_tables_cn, conclusion_cn, acknowledgement_cn, references_cn).
   Never use English section keys for Chinese inputs.

3. If input is English, ONLY output English section keys
   (introduction, related_work, method, experiments, conclusion, abstract, acknowledgement).
   Never use any *_cn section keys for English inputs.

4. **Acknowledgements**: If the input contains acknowledgements/致谢/感谢部分,
   YOU MUST include it in the appropriate section (acknowledgement_cn for Chinese, acknowledgement for English).

5. **References**: Extract ALL references from the input, ensuring every citation_key in the text
   corresponds to a key in the references array.

6. Every citation_key (when non-empty) MUST correspond to a key in the "references" array.

7. Reference keys should follow pattern: authorYearFirstword (e.g. "smith2024attention", "chen2026amo")

8. If the user doesn't provide enough info for a field, use empty string "" or empty list []

9. Output ONLY valid JSON, no explanation, no markdown code fences

10. The detected language MUST also appear in your JSON output (for validation).
    Add a top-level key "_language": "chinese" or "_language": "english"

11. Venue selection by input nature:
    - Chinese input → nsfc / sci / thesis / humanities
    - English input → ieee / neurips2024 / icml2025 / cvpr2024 / acl2024

## WARNING: FAILURE TO PRESERVE ALL CONTENT WILL RESULT IN SEVERE PENALTY
If you omit, summarize, or condense any part of the input text, your response will be considered invalid.
YOU MUST INCLUDE EVERY SENTENCE AND PARAGRAPH FROM THE INPUT."""


class NLIntake:
    """自然语言 → 结构化数据 转换器
    
    用法:
        llm = OpenAILLM(api_key="...")
        intake = NLIntake(llm)
        paper_spec, ref_db, section_data = intake.process(user_text)
    """
    
    def __init__(self, llm: LLMCallable):
        self.llm = llm
    
    def process(self, user_text: str, 
                existing_refs: Optional[ReferenceDB] = None,
                venue: Optional[str] = None,
                field: Optional[str] = None) -> tuple[PaperSpec, ReferenceDB, dict]:
        """
        将用户自然语言描述转为结构化数据。
        
        Args:
            user_text: 用户的自然语言论文描述
            existing_refs: 已有的引用数据库（增量模式），新引用会合并进去
            venue: 覆盖 venue（如果用户没指定）
            field: 覆盖 field
            
        Returns:
            (PaperSpec, ReferenceDB, section_data_map)
        """
        # 构建 user prompt
        hints = []
        if venue:
            hints.append(f"Venue: {venue}")
        if field:
            hints.append(f"Field: {field}")
        
        user_prompt = user_text
        if hints:
            user_prompt = f"Additional hints: {', '.join(hints)}\n\n{user_text}"
        
        # 调用 LLM
        response = self.llm(INTAKE_SYSTEM_PROMPT, user_prompt)
        
        # 解析 JSON
        try:
            data = self._parse_response(response.content)
        except (json.JSONDecodeError, KeyError) as e:
            raise IntakeParseError(f"Failed to parse LLM response: {e}\n"
                                   f"Raw response: {response.content[:500]}...")
        
        # 验证
        errors = self._validate(data)
        if errors:
            raise IntakeValidationError(errors)
        
        # 转换为 Python 类型
        paper_spec, ref_db, section_data = self._convert(data, existing_refs)
        
        return paper_spec, ref_db, section_data
    
    def process_incremental(self, user_text: str, 
                            current_data: dict) -> dict:
        """
        增量模式：在已有结构化数据基础上，用新的自然语言补充/修改。
        
        Args:
            user_text: 新增/修改的自然语言描述
            current_data: 当前已有的 section_data_map
            
        Returns:
            更新后的 section_data_map
        """
        prompt = f"""You are editing an existing paper data structure.
Current data:
{json.dumps(current_data, ensure_ascii=False, indent=2)}

User's update request:
{user_text}

Return the COMPLETE updated data structure as JSON (not just the changes).
Follow the same schema rules as before."""
        
        response = self.llm(INTAKE_SYSTEM_PROMPT, prompt)
        data = self._parse_response(response.content)
        
        errors = self._validate(data)
        if errors:
            raise IntakeValidationError(errors)
        
        # 只取 sections 部分合并
        _, _, new_sections = self._convert(data)
        current_data.update(new_sections)
        return current_data
    
    def _parse_response(self, content: str) -> dict:
        """解析 LLM 返回的 JSON（处理可能的 markdown code fence）"""
        content = content.strip()
        
        # 去除可能的 markdown code fence
        if content.startswith("```"):
            lines = content.split("\n")
            # 去掉第一行 ```json 或 ```
            if lines[0].startswith("```"):
                lines = lines[1:]
            # 去掉最后一行 ```
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            content = "\n".join(lines)
        
        return json.loads(content)
    
    def _validate(self, data: dict) -> list[str]:
        """验证 LLM 输出的结构完整性"""
        errors = []
        
        # 检查必需顶层 key
        for key in ["paper_spec", "references", "sections"]:
            if key not in data:
                errors.append(f"Missing top-level key: {key}")
        
        if "paper_spec" in data:
            ps = data["paper_spec"]
            if not ps.get("title"):
                errors.append("paper_spec.title is required")
            if not ps.get("venue"):
                errors.append("paper_spec.venue is required")
        
        # 检查 citation_keys 是否在 references 中定义
        if "references" in data and "sections" in data:
            ref_keys = {r["key"] for r in data["references"]}
            cited_keys = self._extract_citation_keys(data["sections"])
            undefined = cited_keys - ref_keys
            if undefined:
                errors.append(
                    f"Citation keys not in references: {', '.join(sorted(undefined))}"
                )

        return errors
    
    def _extract_citation_keys(self, data) -> set:
        """递归提取所有 citation_keys"""
        keys = set()
        if isinstance(data, dict):
            if "citation_keys" in data:
                keys.update(data["citation_keys"])
            for v in data.values():
                keys.update(self._extract_citation_keys(v))
        elif isinstance(data, list):
            for item in data:
                keys.update(self._extract_citation_keys(item))
        return keys
    
    def _convert(self, data: dict, 
                 existing_refs: Optional[ReferenceDB] = None
                 ) -> tuple[PaperSpec, ReferenceDB, dict]:
        """将 LLM 返回的 JSON 转为 Python 类型"""
        
        # PaperSpec
        ps = data["paper_spec"]
        paper_spec: PaperSpec = {
            "title": ps.get("title", ""),
            "authors": ps.get("authors", []),
            "venue": ps.get("venue", "neurips2024"),
            "field": ps.get("field", "general"),
            "keywords": ps.get("keywords", []),
            "abstract": None,
        }
        
        # ReferenceDB
        ref_db = existing_refs if existing_refs else ReferenceDB()
        for ref in data.get("references", []):
            ref_db.add(BibEntry(
                key=ref["key"],
                entry_type=ref.get("entry_type", "misc"),
                fields=ref.get("fields", {}),
            ))
        
        # Sections —— 根据 _language 严格过滤 section key，忽略不匹配语言的 section
        sections = data.get("sections", {})
        section_data_map = {}

        # 根据 _language 决定支持的 section names
        detected_language = data.get("_language", "english")
        if detected_language == "chinese":
            # 中文模板：支持中文和英文摘要（双语）
            all_section_names = [
                "chinese_abstract", "english_abstract", "related_work_cn", "research_content",
                "research_basis", "figures_tables_cn", "conclusion_cn", 
                "acknowledgement_cn", "references_cn",
            ]
        else:
            # 英文模板：只用英文 section key
            all_section_names = [
                "introduction", "related_work", "method",
                "experiments", "conclusion", "abstract",
                "acknowledgement",
            ]

        for section_name in all_section_names:
            if section_name in sections:
                section_data_map[section_name] = self._clean_section(
                    sections[section_name]
                )

        # 保留原文章节结构（存在则原样放入，供后续渲染优先使用）
        if "original_sections" in sections:
            orig = sections["original_sections"]
            if isinstance(orig, list) and orig:
                section_data_map["original_sections"] = [
                    self._clean_section(item) if isinstance(item, dict) else item
                    for item in orig
                ]

        return paper_spec, ref_db, section_data_map
    
    def _clean_section(self, section: dict) -> dict:
        """清理 LLM 输出中可能的空值/多余字段"""
        # 递归移除 None 值
        cleaned = {}
        for k, v in section.items():
            if v is None:
                cleaned[k] = [] if k in ("background", "works", "contributions",
                                          "subsections", "limitations", 
                                          "future_work", "paper_structure",
                                          "equations", "figures", "tables",
                                          "findings", "algorithms") else ""
            elif isinstance(v, dict):
                cleaned[k] = self._clean_section(v)
            elif isinstance(v, list):
                cleaned[k] = [
                    self._clean_section(item) if isinstance(item, dict) else item
                    for item in v
                ]
            else:
                cleaned[k] = v
        return cleaned


# ============================================================================
# 便捷函数：模拟 LLM（用于测试或不依赖 API 的场景）
# ============================================================================

class MockLLM:
    """模拟 LLM —— 用于测试，返回预定义的 JSON"""
    
    def __init__(self, mock_json: dict):
        self.mock_json = mock_json
    
    def __call__(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        return LLMResponse(
            content=json.dumps(self.mock_json, ensure_ascii=False),
            model="mock",
        )


# ============================================================================
# 异常类
# ============================================================================

class IntakeParseError(Exception):
    """LLM 返回的内容无法解析为 JSON"""
    pass


class IntakeValidationError(Exception):
    """LLM 返回的 JSON 结构不合法"""
    def __init__(self, errors: list[str]):
        self.errors = errors
        msg = "Validation errors in LLM output:\n" + "\n".join(f"  - {e}" for e in errors)
        super().__init__(msg)