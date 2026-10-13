# -*- coding: utf-8 -*-
"""
模板自动识别器 —— 根据 DocumentContent 特征推断最合适的模板。

设计原则：
1. 所有识别规则配置化（template_rules.yaml），禁止硬编码
2. 输入 DocumentContent，输出 TemplateDetection（严格类型对齐）
3. 单一职责：仅做模板推断，不涉及渲染或编译
"""

import os
import re
import yaml
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from core.types import TemplateDetection, TemplateCandidate
from core.document_reader import DocumentContent


@dataclass
class RuleMatch:
    """单条规则匹配结果"""
    rule_type: str
    pattern: str
    weight: float
    matched: bool


class TemplateDetector:
    """模板自动识别器"""

    def __init__(self, rules_path: Optional[str] = None):
        """
        Args:
            rules_path: 规则配置文件路径。默认使用 config/template_rules.yaml
        """
        if rules_path is None:
            base_dir = os.path.dirname(os.path.dirname(__file__))
            rules_path = os.path.join(base_dir, "config", "template_rules.yaml")
        self.rules_path = rules_path
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        """加载 YAML 配置"""
        if not os.path.exists(self.rules_path):
            raise FileNotFoundError(f"模板规则配置文件不存在: {self.rules_path}")
        with open(self.rules_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def detect(self, doc: DocumentContent, hint: Optional[str] = None) -> TemplateDetection:
        """
        检测最合适的模板。

        Args:
            doc: DocumentContent 对象（来自 Step 1）
            hint: 可选的用户提示模板名（优先级最高）

        Returns:
            TemplateDetection: 包含模板名、置信度、候选列表、判定依据
        """
        # 用户明确指定模板时，直接返回
        if hint and hint in self._get_template_names():
            return TemplateDetection(
                template=hint,
                confidence=1.0,
                candidates=[TemplateCandidate(name=hint, score=1.0, matched_rules=["user_specified"])],
                evidence=["用户指定模板: " + hint]
            )

        # 提取文档特征
        text = self._extract_text(doc)
        language = self._detect_language(text)

        # 遍历所有模板，计算匹配得分
        candidates: List[TemplateCandidate] = []
        all_evidence: List[str] = []

        for template_cfg in self.config.get("templates", []):
            template_name = template_cfg["name"]
            template_lang = template_cfg.get("language", "zh")

            # 语言不匹配时跳过（但给予低分而非完全忽略）
            lang_penalty = 0.0 if template_lang == language else 0.5

            matches: List[RuleMatch] = []
            evidence: List[str] = []

            for rule in template_cfg.get("rules", []):
                match_result = self._match_rule(rule, text, doc)
                if match_result.matched:
                    matches.append(match_result)
                    evidence.append(f"{rule['type']}: {match_result.pattern}")

            if matches:
                # 得分计算：取最高权重
                score = max(m.weight for m in matches) - lang_penalty
                candidates.append(TemplateCandidate(
                    name=template_name,
                    score=score,
                    matched_rules=[m.pattern for m in matches]
                ))
                all_evidence.extend(evidence)

        # 排序并选择最佳模板
        candidates.sort(key=lambda c: c.score, reverse=True)

        if not candidates:
            # 无匹配时，根据语言选择默认模板（配置化）
            default_by_lang = {"zh": "nsfc", "en": "ieee"}
            default_name = default_by_lang.get(language, self.config.get("default_template", "nsfc"))
            return TemplateDetection(
                template=default_name,
                confidence=0.3,  # 低置信度，表示推断而非精确匹配
                candidates=[],
                evidence=[f"无精确匹配，根据语言({language})推断"]
            )

        best = candidates[0]
        threshold = self.config.get("strategy", {}).get("confidence_threshold", 0.7)
        confidence = best.score

        return TemplateDetection(
            template=best.name,
            confidence=confidence,
            candidates=candidates[:self.config.get("strategy", {}).get("max_candidates", 3)],
            evidence=all_evidence
        )

    def _get_template_names(self) -> List[str]:
        """获取所有已配置的模板名"""
        return [t["name"] for t in self.config.get("templates", [])]

    def _extract_text(self, doc: DocumentContent) -> str:
        """从 DocumentContent 提取纯文本用于分析"""
        texts = []
        for block in doc.blocks:
            if block.content:
                texts.append(block.content)
            if block.title:
                texts.append(block.title)
        return "\n".join(texts)

    def _detect_language(self, text: str) -> str:
        """检测文档语言"""
        threshold = self.config.get("language_detection", {}).get("chinese_char_threshold", 0.3)
        chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
        total_chars = len(text.replace(" ", "").replace("\n", ""))
        if total_chars == 0:
            return "zh"
        ratio = chinese_chars / total_chars
        return "zh" if ratio >= threshold else "en"

    def _match_rule(self, rule: Dict[str, Any], text: str, doc: DocumentContent) -> RuleMatch:
        """匹配单条规则"""
        rule_type = rule["type"]
        weight = rule.get("weight", 0.5)

        if rule_type == "title_keyword":
            # 标题关键词匹配
            patterns = rule.get("patterns", [])
            for p in patterns:
                if p.lower() in text.lower():
                    return RuleMatch(rule_type=rule_type, pattern=p, weight=weight, matched=True)

        elif rule_type == "abstract_keyword":
            # 摘要关键词匹配
            patterns = rule.get("patterns", [])
            for p in patterns:
                if p.lower() in text.lower():
                    return RuleMatch(rule_type=rule_type, pattern=p, weight=weight, matched=True)

        elif rule_type == "citation_style":
            # 引用格式匹配
            pattern = rule.get("pattern", "")
            if pattern and re.search(pattern, text):
                return RuleMatch(rule_type=rule_type, pattern=pattern, weight=weight, matched=True)

        elif rule_type == "structure_marker":
            # 结构标记匹配（如"第一章"、"参考文献"）
            patterns = rule.get("patterns", [])
            for p in patterns:
                if p in text:
                    return RuleMatch(rule_type=rule_type, pattern=p, weight=weight, matched=True)

        return RuleMatch(rule_type=rule_type, pattern="", weight=0.0, matched=False)

    @classmethod
    def detect_from_file(cls, file_path: str, hint: Optional[str] = None) -> TemplateDetection:
        """
        从文件路径直接检测模板（便捷方法）。
        
        Args:
            file_path: Word 文档或 Markdown 文档路径
            hint: 可选的用户提示模板名
            
        Returns:
            TemplateDetection: 模板检测结果
        """
        from core.document_reader import read_document
        from core.markdown_reader import read_markdown
        
        ext = os.path.splitext(file_path)[-1].lower()
        if ext in ('.md', '.markdown'):
            doc_content = read_markdown(file_path)
        else:
            doc_content = read_document(file_path, os.path.dirname(file_path) or '.')
        detector = cls()
        return detector.detect(doc_content, hint)