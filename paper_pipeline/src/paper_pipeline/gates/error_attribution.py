"""
智能错误归因与修复建议 —— 方向10

设计原则：
- 基于错误模式库进行根因分析
- 提供分级修复建议（自动修复 / 半自动 / 人工）
- 学习历史修复经验（基于成功/失败统计）
- 给出修复时间预估
"""
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional


class RootCause:
    """错误根因"""

    def __init__(
        self,
        cause: str,
        category: str,
        confidence: float = 1.0,
        explanation: str = "",
    ) -> None:
        self.cause = cause
        self.category = category  # template, structure, content, syntax, environment
        self.confidence = confidence  # 0-1
        self.explanation = explanation

    def __repr__(self):
        return f"RootCause(cause='{self.cause}', category='{self.category}', confidence={self.confidence})"


class FixSuggestion:
    """修复建议"""

    def __init__(
        self,
        action: str,
        automated: bool,
        success_rate: float = 0.0,
        estimated_time_sec: float = 0.0,
        description: str = "",
        code_example: str = "",
    ) -> None:
        self.action = action
        self.automated = automated
        self.success_rate = success_rate
        self.estimated_time_sec = estimated_time_sec
        self.description = description
        self.code_example = code_example

    def __repr__(self):
        return f"FixSuggestion(action='{self.action}', automated={self.automated}, success_rate={self.success_rate})"


class ErrorPatternLibrary:
    """
    错误模式库 —— 存储已知错误模式与对应的根因/修复建议
    """

    # 错误代码 → 根因信息
    _PATTERNS: Dict[str, Dict[str, Any]] = {
        "DUPLICATE_REF_HEADING": {
            "root_causes": [
                RootCause(
                    "模板自动添加参考文献标题 + 原文已有标题",
                    category="template",
                    confidence=0.95,
                    explanation="LaTeX 模板（如 ctexart 的 \\thebibliography 环境）会自动生成参考文献标题，"
                    "如果原文中也包含该标题，会导致重复。",
                ),
            ],
            "suggestions": [
                FixSuggestion(
                    action="删除原文中重复的参考文献标题",
                    automated=True,
                    success_rate=0.95,
                    estimated_time_sec=1.0,
                    description="在 .tex 中删除多余的 \\section*{参考文献} 或 \\chapter*{参考文献}，保留模板自动生成的标题。",
                    code_example="删除前: \\section*{参考文献} ... \\end{thebibliography}\n删除后: ... \\end{thebibliography}",
                ),
            ],
        },
        "SUBHEADING_NOT_LEFT": {
            "root_causes": [
                RootCause(
                    "未使用 \\raggedright 或 titlesec 未正确配置",
                    category="template",
                    confidence=0.90,
                    explanation="中文学位论文要求二级标题左对齐，但默认 LaTeX 章节标题居中。",
                ),
            ],
            "suggestions": [
                FixSuggestion(
                    action="添加 \\raggedright 到 titlesec 设置",
                    automated=True,
                    success_rate=0.85,
                    estimated_time_sec=1.0,
                    description='在 \\titleformat{...} 中添加 \\raggedright 参数。',
                    code_example='\\titleformat{\\section}[block]{\\heiti\\fontsize{14pt}{20pt}\\selectfont\\bfseries\\raggedright}',
                ),
            ],
        },
        "KEYWORD_ALONE": {
            "root_causes": [
                RootCause(
                    "摘要后多余的 \\clearpage 导致关键词单独占一页",
                    category="structure",
                    confidence=0.95,
                    explanation="关键词应紧接摘要，不应单独占一页。",
                ),
            ],
            "suggestions": [
                FixSuggestion(
                    action="删除关键词和摘要之间的 \\clearpage",
                    automated=True,
                    success_rate=0.95,
                    estimated_time_sec=1.0,
                    description="将关键词放入 \\begin{abstract} 环境中，确保与摘要同页。",
                ),
            ],
        },
        "TOC_NOT_SEPARATE": {
            "root_causes": [
                RootCause(
                    "目录前缺少 \\clearpage 或 \\newpage",
                    category="structure",
                    confidence=0.90,
                    explanation="目录应单独占一页。",
                ),
            ],
            "suggestions": [
                FixSuggestion(
                    action="在 \\tableofcontents 前添加 \\clearpage",
                    automated=True,
                    success_rate=0.95,
                    estimated_time_sec=1.0,
                ),
            ],
        },
        "FORMULA_NOT_WRAPPED": {
            "root_causes": [
                RootCause(
                    "数学符号未被 $ 包裹",
                    category="content",
                    confidence=0.90,
                    explanation="希腊字母、数学符号在 LaTeX 中需要 $ 包裹才能正确渲染。",
                ),
            ],
            "suggestions": [
                FixSuggestion(
                    action="用 $ 包裹裸露的数学符号",
                    automated=True,
                    success_rate=0.80,
                    estimated_time_sec=2.0,
                    description="自动检测并包裹希腊字母、数学符号和变量下标。",
                ),
            ],
        },
        "TABLE_NOT_THREE_LINE": {
            "root_causes": [
                RootCause(
                    "表格使用 \\hline 而非 booktabs 三线表",
                    category="template",
                    confidence=0.95,
                    explanation="中文学位论文要求使用三线表（\\toprule/\\midrule/\\bottomrule）。",
                ),
            ],
            "suggestions": [
                FixSuggestion(
                    action="将 \\hline 替换为 booktabs 命令",
                    automated=True,
                    success_rate=0.90,
                    estimated_time_sec=1.0,
                    description="自动将 \\hline 转换为 \\toprule/\\midrule/\\bottomrule。",
                ),
            ],
        },
        "IMAGE_ASPECT_DISTORTED": {
            "root_causes": [
                RootCause(
                    "\\includegraphics 同时设置了 width 和 height，未启用 keepaspectratio",
                    category="syntax",
                    confidence=0.85,
                    explanation="当同时指定 width 和 height 时，未启用 keepaspectratio 会导致图片拉伸变形。",
                ),
            ],
            "suggestions": [
                FixSuggestion(
                    action="移除显式 height 或添加 keepaspectratio",
                    automated=True,
                    success_rate=0.90,
                    estimated_time_sec=1.0,
                ),
            ],
        },
        "ROMAN_AFTER_ARABIC": {
            "root_causes": [
                RootCause(
                    "正文中错误地使用了 \\pagenumbering{Roman}",
                    category="template",
                    confidence=0.95,
                    explanation="罗马数字页码应用于摘要/目录部分，不应出现在正文。",
                ),
            ],
            "suggestions": [
                FixSuggestion(
                    action="删除正文中的 \\pagenumbering{Roman}",
                    automated=True,
                    success_rate=0.95,
                    estimated_time_sec=1.0,
                ),
            ],
        },
        "FONT_INCONSISTENT": {
            "root_causes": [
                RootCause(
                    "正文中存在多种字号，未设置 \\fontsize",
                    category="template",
                    confidence=0.90,
                    explanation="LaTeX 默认会根据上下文自动调整字号，导致不一致。",
                ),
            ],
            "suggestions": [
                FixSuggestion(
                    action="在 \\begin{document} 后添加 \\fontsize{12pt}{18pt}",
                    automated=True,
                    success_rate=0.85,
                    estimated_time_sec=1.0,
                ),
            ],
        },
        "MISSING_GRAPHICSPATH": {
            "root_causes": [
                RootCause(
                    "\\includegraphics{images/...} 路径未配置",
                    category="structure",
                    confidence=0.90,
                    explanation="如果未设置 \\graphicspath，图片引用需要使用完整相对路径。",
                ),
            ],
            "suggestions": [
                FixSuggestion(
                    action="添加 \\graphicspath{{./images/}}",
                    automated=True,
                    success_rate=0.95,
                    estimated_time_sec=0.5,
                ),
            ],
        },
        "TOC_EMPTY": {
            "root_causes": [
                RootCause(
                    "缺少 \\tableofcontents 命令",
                    category="template",
                    confidence=0.99,
                    explanation="LaTeX 不会自动生成目录，必须显式调用 \\tableofcontents。",
                ),
            ],
            "suggestions": [
                FixSuggestion(
                    action="在 \\begin{document} 后添加 \\tableofcontents",
                    automated=True,
                    success_rate=0.99,
                    estimated_time_sec=0.5,
                ),
            ],
        },
        "EMPTY_ABSTRACT": {
            "root_causes": [
                RootCause(
                    "摘要内容为空或仅包含标题",
                    category="content",
                    confidence=0.99,
                    explanation="可能由于解析错误或原文摘要确实缺失。",
                ),
            ],
            "suggestions": [
                FixSuggestion(
                    action="人工检查原文摘要内容",
                    automated=False,
                    success_rate=0.0,
                    estimated_time_sec=300.0,
                    description="无法自动修复，需要人工核对原文。",
                ),
            ],
        },
    }

    @classmethod
    def get_root_causes(cls, error_code: str) -> List[RootCause]:
        """获取错误代码对应的根因列表"""
        pattern = cls._PATTERNS.get(error_code, {})
        return pattern.get("root_causes", [])

    @classmethod
    def get_suggestions(cls, error_code: str) -> List[FixSuggestion]:
        """获取错误代码对应的修复建议"""
        pattern = cls._PATTERNS.get(error_code, {})
        return pattern.get("suggestions", [])

    @classmethod
    def get_all_error_codes(cls) -> List[str]:
        """获取所有已知的错误代码"""
        return list(cls._PATTERNS.keys())


class FixHistory:
    """
    修复历史记录 —— 学习成功的修复策略
    """

    def __init__(self, history_file: Optional[Path] = None) -> None:
        self.history_file = history_file
        self._history: List[Dict[str, Any]] = []
        if history_file and history_file.exists():
            try:
                import json
                with open(history_file, "r", encoding="utf-8") as f:
                    self._history = json.load(f)
            except Exception:
                pass

    def record(
        self,
        error_code: str,
        strategy: str,
        success: bool,
        elapsed_sec: float = 0.0,
    ) -> None:
        """记录一次修复尝试"""
        self._history.append({
            "error_code": error_code,
            "strategy": strategy,
            "success": success,
            "elapsed_sec": elapsed_sec,
            "timestamp": __import__("datetime").datetime.now().isoformat(),
        })
        self._save()

    def get_success_rate(self, error_code: str, strategy: str = "") -> float:
        """获取指定错误/策略的历史成功率"""
        records = [h for h in self._history if h["error_code"] == error_code]
        if not records:
            return 0.0
        if strategy:
            records = [r for r in records if r["strategy"] == strategy]
        if not records:
            return 0.0
        success_count = sum(1 for r in records if r["success"])
        return success_count / len(records)

    def get_avg_elapsed(self, error_code: str) -> float:
        """获取平均修复时间"""
        records = [h for h in self._history if h["error_code"] == error_code and h["success"]]
        if not records:
            return 0.0
        return sum(r["elapsed_sec"] for r in records) / len(records)

    def _save(self) -> None:
        if not self.history_file:
            return
        try:
            import json
            with open(self.history_file, "w", encoding="utf-8") as f:
                json.dump(self._history, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


class ErrorAttributor:
    """
    错误归因器 —— 方向10核心

    功能：
    1. 从 Gate5 报告提取错误
    2. 查询错误模式库获取根因
    3. 结合历史数据生成修复建议
    4. 输出结构化的归因报告
    """

    def __init__(self, history_file: Optional[Path] = None) -> None:
        self.patterns = ErrorPatternLibrary()
        self.history = FixHistory(history_file)

    def attribute(self, error_code: str) -> Dict[str, Any]:
        """
        对单个错误代码进行归因。

        返回:
            {
                "error_code": str,
                "root_causes": List[RootCause],
                "suggestions": List[FixSuggestion],
                "historical_success_rate": float,
                "estimated_fix_time_sec": float,
                "auto_fixable": bool,
            }
        """
        root_causes = self.patterns.get_root_causes(error_code)
        suggestions = self.patterns.get_suggestions(error_code)

        # 从历史数据更新成功率
        historical_rate = self.history.get_success_rate(error_code)
        if historical_rate > 0 and suggestions:
            for s in suggestions:
                # 综合历史和默认成功率
                s.success_rate = (s.success_rate * 0.5 + historical_rate * 0.5)

        # 计算预估修复时间
        estimated_time = 0.0
        if suggestions:
            estimated_time = sum(s.estimated_time_sec for s in suggestions) / len(suggestions)
            historical_time = self.history.get_avg_elapsed(error_code)
            if historical_time > 0:
                estimated_time = (estimated_time + historical_time) / 2

        auto_fixable = any(s.automated for s in suggestions)

        return {
            "error_code": error_code,
            "root_causes": [vars(rc) for rc in root_causes],
            "suggestions": [vars(s) for s in suggestions],
            "historical_success_rate": historical_rate,
            "estimated_fix_time_sec": estimated_time,
            "auto_fixable": auto_fixable,
        }

    def attribute_all(self, errors: List[str]) -> List[Dict[str, Any]]:
        """对所有错误进行归因"""
        # 从错误消息中提取错误代码
        results = []
        seen_codes = set()

        for error in errors:
            code = self._extract_error_code(error)
            if code and code not in seen_codes:
                seen_codes.add(code)
                results.append(self.attribute(code))

        return results

    def _extract_error_code(self, error_message: str) -> Optional[str]:
        """从错误消息中提取错误代码"""
        # 匹配 [...] 格式的错误代码
        match = re.match(r'^\[([A-Z_]+)\]', error_message)
        if match:
            return match.group(1)
        return None

    def generate_report(
        self,
        errors: List[str],
        output_file: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """
        生成完整的归因报告（从错误消息列表）。
        """
        attributions = self.attribute_all(errors)
        return self._build_report(attributions, output_file)

    def generate_report_from_codes(
        self,
        error_codes: List[str],
        output_file: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """
        生成完整的归因报告（从错误代码列表，用于结构化 issues）。
        """
        attributions = []
        seen = set()
        for code in error_codes:
            if code and code not in seen:
                seen.add(code)
                attributions.append(self.attribute(code))
        return self._build_report(attributions, output_file)

    def _build_report(
        self,
        attributions: List[Dict[str, Any]],
        output_file: Optional[Path] = None,
    ) -> Dict[str, Any]:
        """构建归因报告"""
        total = len(attributions)
        auto_fixable = sum(1 for a in attributions if a["auto_fixable"])
        total_time = sum(a["estimated_fix_time_sec"] for a in attributions)

        report = {
            "summary": {
                "total_errors": total,
                "auto_fixable": auto_fixable,
                "manual_required": total - auto_fixable,
                "estimated_total_time_sec": total_time,
            },
            "attributions": attributions,
        }

        if output_file:
            try:
                import json
                with open(output_file, "w", encoding="utf-8") as f:
                    json.dump(report, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

        return report
