"""
生图服务 —— 封装 paper2diagram-skill，实现完整 S0-S5 流程

设计原则：
- 不重复实现 paper2diagram 已有的功能，直接调用其组件
- 类型安全：输入/输出使用本项目的模型类型，内部调用时转换
- 异常处理：所有底层异常捕获并包装为 PipelineError
- 分层边界：Service 层只负责业务逻辑编排，不直接处理 CLI/配置
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from typing import List, Dict, Any, Optional

from ..config.settings import Settings
from ..models.paper import PaperAnalysis
from ..models.diagram import DiagramResult, DiagramPrompt, DiagramVariant, PipelineStage
from ..exceptions import DiagramGenerationError, LLMError, ConfigurationError

_PAPER2DIAGRAM_INITIALIZED = False


def _init_paper2diagram(paper2diagram_dir: Path) -> None:
    """延迟初始化 paper2diagram 模块路径（避免模块级硬编码）。"""
    global _PAPER2DIAGRAM_INITIALIZED
    if _PAPER2DIAGRAM_INITIALIZED:
        return
    if str(paper2diagram_dir) not in sys.path:
        sys.path.insert(0, str(paper2diagram_dir))
    _PAPER2DIAGRAM_INITIALIZED = True


# ── paper2diagram 组件延迟导入 ──
# 实际导入在 DiagramService.__init__ 中通过 _init_paper2diagram(settings.paper2diagram_dir) 触发


class DiagramService:
    """
    生图服务 —— 对 paper2diagram 的 S0-S5 完整流程进行类型安全封装

    对外接口类型：
      - 输入: Path (论文文件路径)
      - 输出: List[DiagramResult] (4 张不同结构的流程图)
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        _init_paper2diagram(self.settings.paths.paper2diagram_dir)
        # 延迟导入 —— 路径初始化完成后才导入 paper2diagram 组件
        # 延迟导入的类提升为模块级全局：_get_analyzer()/_get_image_generator()
        # 按模块全局名引用这些类，若仅局部导入会触发 NameError
        global PaperAnalyzer, PromptGenerator, ImageGenerator, get_palette
        from paper2diagram import PaperAnalyzer, PromptGenerator, ImageGenerator  # noqa: F811
        from paper2diagram.llm.color_palettes import get_palette  # noqa: F811
        self._analyzer: Optional[PaperAnalyzer] = None
        self._prompt_gen: Optional[PromptGenerator] = None
        self._image_gen: Optional[ImageGenerator] = None
        self._paper_analysis: Optional[PaperAnalysis] = None
        # 存储导入的模块级函数引用供类内使用
        self._get_palette = get_palette

    # ------------------------------------------------------------------
    # 内部：延迟初始化组件（避免在 __init__ 中触发网络/文件操作）
    # ------------------------------------------------------------------

    def _get_analyzer(self) -> PaperAnalyzer:
        if self._analyzer is None:
            self._analyzer = PaperAnalyzer(
                llm_api_key=self.settings.api.llm_api_key,
                base_url=self.settings.api.llm_base_url,
                model=self.settings.api.llm_model,
            )
        return self._analyzer

    def _get_prompt_generator(self) -> PromptGenerator:
        if self._prompt_gen is None:
            self._prompt_gen = PromptGenerator()
        return self._prompt_gen

    def _get_image_generator(self) -> ImageGenerator:
        if self._image_gen is None:
            self._image_gen = ImageGenerator(
                api_key=self.settings.api.image_api_key,
                base_url=self.settings.api.image_base_url,
                model=self.settings.api.image_model,
                timeout=self.settings.api.image_timeout,
                max_retries=self.settings.api.image_max_retries,
                total_timeout=self.settings.api.image_total_timeout,
            )
        return self._image_gen

    # ------------------------------------------------------------------
    # S0: 论文基础分析
    # ------------------------------------------------------------------

    def analyze_paper(self, paper_path: Path) -> PaperAnalysis:
        """
        S0 —— 解析论文并 LLM 分析

        :param paper_path: 论文文件路径 (.docx)
        :return: 类型安全的 PaperAnalysis
        :raises DiagramGenerationError: 分析失败
        """
        if not paper_path.exists():
            raise DiagramGenerationError(
                message=f"论文文件不存在: {paper_path}",
                stage="S0",
                context={"paper_path": str(paper_path)},
            )

        analyzer = self._get_analyzer()

        try:
            content = analyzer.extract_text(str(paper_path))
        except Exception as e:
            raise DiagramGenerationError(
                message="论文文本提取失败",
                stage="S0",
                context={"paper_path": str(paper_path)},
                cause=e,
            )

        try:
            raw_analysis = analyzer.analyze_paper(content)
        except Exception as e:
            raise LLMError(
                message="LLM 论文分析失败",
                stage="S0",
                context={"content_length": len(content)},
                cause=e,
            )

        try:
            analysis = PaperAnalysis.from_raw(raw_analysis)
        except ValueError as e:
            raise DiagramGenerationError(
                message="LLM 输出结构不符合预期",
                stage="S0",
                context={"raw_keys": list(raw_analysis.keys()) if isinstance(raw_analysis, dict) else "non-dict"},
                cause=e,
            )

        self._paper_analysis = analysis
        return analysis

    # ------------------------------------------------------------------
    # S1-S5: 生成 4 张不同结构的流程图
    # ------------------------------------------------------------------

    def generate_diagrams(self, paper_path: Path) -> List[DiagramResult]:
        """
        完整 S0-S5 流程 —— 生成 4 张不同结构的流程图

        流程设计：
          S0: 分析论文（一次）
          S1: 选择 4 个不同 R1 变体，各生成一个探索 prompt
          S2: 跳过 R1 草图探索（全自动场景，直接基于变体方向精修）
          S3: 自动确定 4 个偏好方向（每个变体即一个方向）
          S4: 基于 4 个方向各生成 R2 正式 prompt
          S5: 生成 4 张最终图

        :param paper_path: 论文文件路径
        :return: 4 张 DiagramResult，按变体顺序排列
        """
        # S0
        analysis = self.analyze_paper(paper_path)
        raw_dict = analysis.to_dict()

        # S1: 生成 4 个不同变体的探索 prompt
        s1_prompts = self._run_s1(raw_dict)

        # S4-S5: 对每个变体方向生成正式 prompt 并出图
        results: List[DiagramResult] = []
        for i, s1_prompt in enumerate(s1_prompts):
            variant_id = s1_prompt.variant.id
            palette = self.settings.diagram.palettes[i % len(self.settings.diagram.palettes)]

            # S4: 基于该变体方向生成 R2 正式 prompt
            s4_prompt = self._run_s4_for_variant(raw_dict, s1_prompt, palette)

            # S5: 生成图片
            result = self._run_s5(s4_prompt)
            results.append(result)

            # 间隔避免 API 限流
            if i < len(s1_prompts) - 1:
                time.sleep(self.settings.diagram.image_gen_interval_sec)

        return results

    def _run_s1(self, paper_analysis: Dict[str, Any]) -> List[DiagramPrompt]:
        """
        S1 —— 策略设计：为 4 个不同变体生成探索 prompt

        使用 PromptGenerator.generate_s1_prompts() 确保变体 layout 被正确
        融入 prompt 的 VISUAL STRATEGY 核心指令，而非仅追加到末尾。
        """
        prompt_gen = self._get_prompt_generator()

        # 使用正确接口：generate_s1_prompts 会把变体 layout 写入 VISUAL STRATEGY
        s1_candidates = prompt_gen.generate_s1_prompts(
            paper_analysis,
            candidate_count=self.settings.diagram.s2_count,
        )

        s1_results: List[DiagramPrompt] = []
        for i, cand in enumerate(s1_candidates):
            variant = DiagramVariant.from_dict({
                "id": cand["id"],
                "identity": cand["identity"],
                "layout": cand["layout"],
                "color": cand["color"],
                "style": cand["style"],
            })
            palette_name = self.settings.diagram.palettes[i % len(self.settings.diagram.palettes)]
            palette = self._get_palette(palette_name)

            # 用配置的配色覆盖变体默认配色
            prompt_text = self._override_palette_in_prompt(cand["prompt"], palette)

            candidate_id = f"{variant.id}_{palette_name}"
            prompt_path = self.settings.paths.diagrams_dir / f"prompt_s1_{candidate_id}.txt"
            prompt_path.parent.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text(prompt_text, encoding="utf-8")

            target_image = self.settings.paths.diagrams_dir / f"diagram_{candidate_id}.png"

            s1_results.append(DiagramPrompt(
                candidate_id=candidate_id,
                prompt_text=prompt_text,
                variant=variant,
                target_image_path=target_image,
                prompt_path=prompt_path,
                stage=PipelineStage.S1_STRATEGY,
            ))

        return s1_results

    def _run_s4_for_variant(
        self,
        paper_analysis: Dict[str, Any],
        s1_prompt: DiagramPrompt,
        palette_name: str,
    ) -> DiagramPrompt:
        """
        S4 —— 基于 S1 变体方向生成 R2 正式 prompt

        直接使用 S1 的变体布局信息，确保 R2 正式 prompt 继承相同的布局结构，
        而不是使用 get_formal_variants() 的默认水平管线布局。
        """
        prompt_gen = self._get_prompt_generator()
        variant = s1_prompt.variant

        summary = prompt_gen._build_paper_summary(paper_analysis)
        modules = paper_analysis.get("stages", [])
        connections = paper_analysis.get("connections", [])

        template_id = prompt_gen.template_manager.suggest(paper_analysis)
        template = prompt_gen.template_manager.get(template_id)
        n_stages = len(paper_analysis.get("stages", []))

        s1_variant_dict = {
            "id": variant.id,
            "identity": variant.identity,
            "layout": variant.layout,
            "color": variant.color,
            "style": variant.style,
        }

        visual_strategy = prompt_gen._build_detailed_visual_strategy(
            template=template,
            variant=s1_variant_dict,
            n_stages=n_stages,
            is_formal=True,
            preferred_direction=variant.id,
        )

        prompt_text = prompt_gen._build_contract_prompt(
            paper_summary=summary,
            paper_analysis=paper_analysis,
            modules=modules,
            connections=connections,
            visual_strategy=visual_strategy,
            candidate_identity=s1_variant_dict["identity"],
            layout_style=s1_variant_dict["layout"],
            color_scheme=s1_variant_dict["color"],
            extra_emphasis=f"偏好承接：{variant.id}",
        )

        palette = get_palette(palette_name)
        prompt_text = self._override_palette_in_prompt(prompt_text, palette)

        prompt_text = self._refine_to_r2(prompt_text, variant)

        candidate_id = f"R2_{variant.id}_{palette_name}"
        prompt_path = self.settings.paths.diagrams_dir / f"prompt_s4_{candidate_id}.txt"
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt_text, encoding="utf-8")

        target_image = self.settings.paths.diagrams_dir / f"diagram_{candidate_id}.png"

        return DiagramPrompt(
            candidate_id=candidate_id,
            prompt_text=prompt_text,
            variant=variant,
            target_image_path=target_image,
            prompt_path=prompt_path,
            stage=PipelineStage.S4_FORMAL,
        )

    def _run_s5(self, s4_prompt: DiagramPrompt) -> DiagramResult:
        """
        S5 —— 正式候选：调用生图模型生成出版级图片
        """
        image_gen = self._get_image_generator()
        target = s4_prompt.target_image_path

        if self.settings.diagram.skip_existing and target.exists() and target.stat().st_size > self.settings.diagram.min_image_file_size:
            size_kb = target.stat().st_size / 1024
            return DiagramResult(
                candidate_id=s4_prompt.candidate_id,
                image_path=target,
                prompt=s4_prompt,
                generated=True,
                size_kb=size_kb,
                stage=PipelineStage.S5_FINAL,
            )

        try:
            saved_path = image_gen.generate_image(
                s4_prompt.prompt_text,
                str(target),
            )
        except Exception as e:
            return DiagramResult(
                candidate_id=s4_prompt.candidate_id,
                image_path=target,
                prompt=s4_prompt,
                generated=False,
                error=str(e),
                stage=PipelineStage.S5_FINAL,
            )

        saved = Path(saved_path)
        size_kb = saved.stat().st_size / 1024 if saved.exists() else 0.0
        return DiagramResult(
            candidate_id=s4_prompt.candidate_id,
            image_path=saved,
            prompt=s4_prompt,
            generated=True,
            size_kb=size_kb,
            stage=PipelineStage.S5_FINAL,
        )

    # ------------------------------------------------------------------
    # 辅助：Prompt 注入与精修
    # ------------------------------------------------------------------

    @staticmethod
    def _override_palette_in_prompt(prompt_text: str, palette: Any) -> str:
        """
        用配置的配色方案覆盖 prompt 中的默认配色。

        generate_s1_prompts/generate_s4_prompts 使用变体定义中的默认配色，
        需要替换为用户配置的 palette（ocean_breeze 等）。
        """
        all_colors = palette.primary_colors + palette.secondary_colors + palette.accent_colors
        stage_colors = all_colors[:3]

        # 1. 替换 CANVAS 中的 Color palette 行
        prompt_text = re.sub(
            r"^- Color palette:.*$",
            f"- Color palette: {palette.name}: {', '.join(all_colors[:4])}",
            prompt_text,
            flags=re.MULTILINE,
        )

        # 2. 替换 VISUAL STRATEGY 中的 FILL REQUIREMENTS 颜色列表
        prompt_text = re.sub(
            r"Use these colors for different stages: [^\.]+\.",
            f"Use these colors for different stages: {', '.join(stage_colors)}.",
            prompt_text,
        )

        # 3. 追加配色覆盖声明（确保 LLM 使用正确颜色）
        override_note = (
            f"\n\n[COLOR OVERRIDE — 必须使用以下配色]\n"
            f"- 主色: {', '.join(palette.primary_colors)}\n"
            f"- 辅色: {', '.join(palette.secondary_colors)}\n"
            f"- 强调色: {', '.join(palette.accent_colors)}\n"
            f"- 背景: {palette.background_light}\n"
            f"- 忽略 prompt 中其他颜色指令，以上述为准\n"
        )
        return prompt_text + override_note

    @staticmethod
    def _refine_to_r2(base_prompt: str, variant: DiagramVariant) -> str:
        """将 prompt 精修为 R2 正式出版风格"""
        refinement = (
            "\n\n[出版级精修要求]\n"
            "- 所有文字清晰可读，字体大小适中\n"
            "- 模块边界干净利落，无多余装饰\n"
            "- 箭头方向明确，标签紧贴连线\n"
            "- 整体布局对称均衡，适合学术期刊印刷\n"
            "- 纯白背景，高对比度，灰度打印友好\n"
            f"- 核心布局特征: {variant.identity}\n"
        )
        return base_prompt + refinement
