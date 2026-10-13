"""
提示词生成模块 —— 结构化Prompt契约 + Edge-label-first + 布局变体

借鉴 paper-framework-figure-studio-pro 的设计原则：
1. 结构化Prompt契约：语义图契约、可见文字契约、负约束
2. Edge-label-first：变量在线上而非模块内
3. 候选变体：每个候选探索不同的布局和配色方向
4. 审计前移：在生成前校验prompt契约
"""
import re
from typing import Dict, List, Optional
from .color_palettes import COLOR_PALETTES, get_palette, random_palette
from .candidate_variants import get_exploration_variants, get_formal_variants
from ..templates.manager import TemplateManager, TemplateConfig

# ========== 配置常量 ==========
FALLBACK_STAGE_COLORS = ["#E3F2FD", "#FFF3E0", "#F3E5F5", "#E8F5E9", "#FFF8E1", "#EFEBE9"]


class PromptGenerator:
    def __init__(self, llm_api_key: str = None):
        """PromptGenerator不再自建PaperAnalyzer，消除冗余LLM客户端实例"""
        self.template_manager = TemplateManager()
        self.template_manager.load_all()

    # ========== 主流程 ==========

    def generate_prompt(self, paper_analysis: Dict, template_id: str = None,
                        palette_name: str = None) -> str:
        """
        基于已有的论文分析结果生成单次绘图提示词（quick模式）

        :param paper_analysis: PaperAnalyzer.analyze_paper()返回的结构化分析结果
        :param template_id: 模板ID（可选，自动推荐）
        :param palette_name: 配色方案名（可选，随机选择）
        """
        if not template_id:
            template_id = self.template_manager.suggest(paper_analysis)
        template = self.template_manager.get(template_id)

        if palette_name and palette_name in COLOR_PALETTES:
            palette = get_palette(palette_name)
        else:
            palette = random_palette()

        return self._build_structured_prompt(paper_analysis, template, palette)

    def generate_s1_prompts(self, paper_analysis: Dict, candidate_count: int = 8,
                            user_preference: str = "") -> List[Dict]:
        """
        S1阶段：基于论文分析结果，为R1探索轮生成多个候选Prompt包

        :param paper_analysis: S0阶段的论文分析结果
        :param candidate_count: 候选数量（默认8个）
        :param user_preference: 用户额外偏好
        :return: 候选Prompt列表
        """
        variants = get_exploration_variants(candidate_count)
        summary = self._build_paper_summary(paper_analysis)
        modules = paper_analysis.get("stages", [])
        connections = paper_analysis.get("connections", [])

        # 自动选择模板并获取详细配置
        template_id = self.template_manager.suggest(paper_analysis)
        template = self.template_manager.get(template_id)
        n_stages = len(paper_analysis.get("stages", []))

        candidates = []
        for v in variants:
            # 构建详细的视觉策略（融合模板系统配置+变体特定风格）
            visual_strategy = self._build_detailed_visual_strategy(
                template=template,
                variant=v,
                n_stages=n_stages,
                is_formal=False,
            )

            prompt = self._build_contract_prompt(
                paper_summary=summary,
                paper_analysis=paper_analysis,
                modules=modules,
                connections=connections,
                visual_strategy=visual_strategy,
                candidate_identity=v["identity"],
                layout_style=v["layout"],
                color_scheme=v["color"],
                extra_emphasis=user_preference,
            )
            candidates.append({
                "id": v["id"],
                "identity": v["identity"],
                "layout": v["layout"],
                "color": v["color"],
                "style": v["style"],
                "prompt": prompt,
            })

        return candidates

    def generate_s4_prompts(self, paper_analysis: Dict, preferred_ids: List[str],
                            candidate_count: int = 6) -> List[Dict]:
        """
        S4阶段：基于S3偏好选择，为R2正式轮生成精修Prompt包

        :param paper_analysis: S0阶段的论文分析结果
        :param preferred_ids: S3阶段用户偏好的候选ID列表
        :param candidate_count: 正式候选数量（默认6个）
        :return: 正式候选Prompt列表
        """
        preferred_direction = ", ".join(preferred_ids) if preferred_ids else ""
        variants = get_formal_variants(candidate_count, preferred_direction)
        summary = self._build_paper_summary(paper_analysis)
        modules = paper_analysis.get("stages", [])
        connections = paper_analysis.get("connections", [])

        # 自动选择模板并获取详细配置
        template_id = self.template_manager.suggest(paper_analysis)
        template = self.template_manager.get(template_id)
        n_stages = len(paper_analysis.get("stages", []))

        candidates = []
        for v in variants:
            # 构建详细的视觉策略（融合模板系统配置+变体特定风格）
            visual_strategy = self._build_detailed_visual_strategy(
                template=template,
                variant=v,
                n_stages=n_stages,
                is_formal=True,
                preferred_direction=preferred_direction,
            )

            prompt = self._build_contract_prompt(
                paper_summary=summary,
                paper_analysis=paper_analysis,
                modules=modules,
                connections=connections,
                visual_strategy=visual_strategy,
                candidate_identity=v["identity"],
                layout_style=v["layout"],
                color_scheme=v["color"],
                extra_emphasis=f"偏好承接：{preferred_direction or '无特定偏好，使用默认正式风格'}",
            )
            candidates.append({
                "id": v["id"],
                "identity": v["identity"],
                "layout": v["layout"],
                "color": v["color"],
                "style": v["style"],
                "prompt": prompt,
            })

        return candidates

    # ========== 结构化Prompt契约 ==========

    def _build_contract_prompt(self, paper_summary: str, paper_analysis: Dict,
                               modules: List, connections: List,
                               visual_strategy: str,
                               candidate_identity: str,
                               layout_style: str, color_scheme: str,
                               extra_emphasis: str = "") -> str:
        """
        构建结构化Prompt契约（借鉴paper-framework-figure-studio-pro v3.2.15b）
        
        核心改进：
        1. 减少负约束，给模型更大自由度
        2. 允许适当的图标和视觉元素
        3. 积极描述替代消极禁止
        4. 强调模块必须有有色背景
        5. 根据论文语言动态调整提示词语言
        """
        language = paper_analysis.get("language", "en")
        
        # 提取模块名和连接关系
        module_names = []
        stage_info = []
        for stage in modules:
            stage_name = stage.get("name", "")
            stage_desc = stage.get("description", "")
            stage_info.append(f"- {stage_name}: {stage_desc}")
            for mod in stage.get("modules", []):
                module_names.append(mod.get("name", ""))

        # 构建连接描述
        edge_descriptions = []
        for conn in connections:
            edge_descriptions.append(
                f"- {conn.get('source', '')} → {conn.get('target', '')} ({conn.get('type', 'sequential')})"
            )

        # 构建可见文字白名单
        visible_text = []
        for stage in modules:
            for mod in stage.get("modules", []):
                visible_text.append(mod.get("name", ""))

        if language == "en":
            prompt = f"""You are an expert scientific figure designer for top-tier CS/scientific research papers. Generate a publication-quality framework architecture diagram.

## CANVAS
- Output: clean PNG diagram, 16:9 landscape orientation
- Style: {layout_style}
- Color palette: {color_scheme}

## PAPER CONTEXT
{paper_summary}

## CORE MODULES (each must appear as a distinct box or labeled region)
{chr(10).join(f"- {m}" for m in module_names)}

## DATA / INFORMATION FLOW
{chr(10).join(edge_descriptions) if edge_descriptions else "input → processing → output"}

## VISUAL STRATEGY
{visual_strategy}

## SEMANTIC GRAPH CONTRACT
Render these as a modular pipeline diagram:
- Each module above appears as a clearly labeled box or region
- Arrows show directional flow from input to intermediate stages to output
- Variables, metrics, and hyperparameters appear as labels ON the arrows or at ports, NOT inside module boxes
- Distinct line styles (solid/dashed) or color-coded edges show different data types
- If the paper has training + inference stages, show both as complementary lanes

## VISIBLE TEXT CONTRACT
- Use short functional module names inside boxes
- 1-2 word labels on key arrows
- No paragraph text inside the diagram
- Keep the diagram readable and compact

## LAYOUT REQUIREMENTS
- Horizontal left-to-right flow for pipeline diagrams; center-out for autoencoder style
- Consistent spacing and alignment
- White or very light background (for inclusion in paper)
- Clean sans-serif labels

## CANDIDATE EMPHASIS (this figure variant)
{candidate_identity}
{extra_emphasis}

Produce a clean, scholarly framework diagram now."""
        else:
            prompt = f"""你是一名顶级CS/科学研究论文的专业科学图表设计师。请生成一张出版级别的框架架构图。

## 画布设置
- 输出：干净的PNG图表，16:9横向布局
- 风格：{layout_style}
- 配色方案：{color_scheme}

## 论文背景
{paper_summary}

## 核心模块（每个必须作为独立的方框或标签区域出现）
{chr(10).join(f"- {m}" for m in module_names)}

## 数据/信息流
{chr(10).join(edge_descriptions) if edge_descriptions else "输入 → 处理 → 输出"}

## 视觉策略
{visual_strategy}

## 语义图契约
将这些渲染为模块化的流程图：
- 每个模块作为清晰标注的方框或区域出现
- 箭头显示从输入到中间阶段再到输出的方向流
- 变量、指标和超参数作为箭头上或端口处的标签出现，NOT inside module boxes
- 不同线型（实线/虚线）或颜色编码的边表示不同的数据类型
- 如果论文有训练+推理阶段，将两者作为互补通道显示

## 可见文字契约
- 在方框内使用简短的功能模块名称
- 关键箭头上使用1-2个词的标签
- 图内不包含段落文本
- 保持图表可读性和紧凑性

## 布局要求
- 流程图采用从左到右的水平流；自编码器风格采用中心向外布局
- 间距和对齐保持一致
- 白色或非常浅的背景（用于论文中）
- 干净的无衬线字体标签

## 候选重点（此图表变体）
{candidate_identity}
{extra_emphasis}

请生成一张干净、学术风格的框架图。"""

        return prompt

    def _build_structured_prompt(self, analysis: Dict, template: TemplateConfig,
                                 palette) -> str:
        """构建兼容旧接口的结构化提示词"""
        all_colors = palette.primary_colors + palette.secondary_colors + palette.accent_colors
        stage_colors = all_colors[:3]

        summary = self._build_paper_summary(analysis)
        modules = analysis.get("stages", [])
        connections = analysis.get("connections", [])

        return self._build_contract_prompt(
            paper_summary=summary,
            paper_analysis=analysis,
            modules=modules,
            connections=connections,
            visual_strategy=(
                f"布局：{template.n_frames}段独立大外框，{template.layout}排列。"
                f"连线：{template.arrow_style}线条+实心三角箭头。"
                f"配色（{palette.name}）：背景{palette.background_light}，"
                f"分段底色分别使用{', '.join(stage_colors)}三种不同颜色的浅色版。"
                f"每个模块必须有背景底色，不能是纯白填充。"
                f"字体：{template.font_family}，主文本{template.font_size_main}pt。"
            ),
            candidate_identity=f"{template.name}模板",
            layout_style=template.layout,
            color_scheme=f"{palette.name}配色：{', '.join(all_colors[:4])}",
            extra_emphasis=f"强制配色：至少使用三种颜色{', '.join(stage_colors)}",
        )

    def _build_detailed_visual_strategy(self, template: TemplateConfig,
                                        variant: Dict, n_stages: int,
                                        is_formal: bool = False,
                                        preferred_direction: str = "") -> str:
        """
        构建详细的视觉策略，融合模板系统配置和变体特定风格
        
        核心改进：
        1. 积极描述替代消极禁止
        2. 强调模块必须有有色背景填充
        3. 允许适当的图标和视觉装饰
        4. 更具体的颜色和布局指导
        """
        # 从变体颜色描述中提取十六进制颜色
        color_desc = variant.get("color", "")
        hex_colors = re.findall(r"#([0-9A-Fa-f]{6})", color_desc)
        hex_colors = [f"#{c}" for c in hex_colors]

        # 如果提取不到足够的颜色，使用预定义的学术配色常量补充
        if len(hex_colors) < n_stages:
            hex_colors.extend(FALLBACK_STAGE_COLORS[:n_stages - len(hex_colors)])

        stage_colors = hex_colors[:n_stages]

        # 构建视觉策略 - 积极描述
        strategy_parts = [
            f"Layout: {template.n_frames} distinct sections arranged {variant['layout']}.",
            f"Connectors: {template.arrow_style} arrows with solid triangle tips.",
        ]

        # 强调有色背景 - 这是关键！
        if n_stages >= 2 and stage_colors:
            strategy_parts.append(
                f"FILL REQUIREMENTS: Each module box MUST have a colored background fill. "
                f"Use these colors for different stages: {', '.join(stage_colors)}. "
                f"NO module should have a plain white background - every box needs a tinted fill."
            )
        
        strategy_parts.append(
            f"Typography: {template.font_family}, main text {template.font_size_main}pt, "
            f"clear hierarchy between titles and labels."
        )

        # 添加变体特定风格（允许更多视觉元素）
        style_desc = variant.get("style", "")
        strategy_parts.append(f"Visual style: {style_desc}.")

        # 允许适当的视觉增强（这是关键改进！）
        strategy_parts.append(
            "Visual enhancements: You MAY include small semantic icons next to module names "
            "(e.g., database icon for data input, gear icon for processing, chart icon for output). "
            "Use subtle shadows or gradients to give depth to module boxes. "
            "Consider rounded corners for a modern look."
        )

        # 正式轮额外要求
        if is_formal:
            strategy_parts.append(
                "Publication quality: Ensure consistent spacing, clean alignment, "
                "and readability at typical journal figure sizes (single/double column width)."
            )
            if preferred_direction:
                strategy_parts.append(
                    f"Inherit preferences from: {preferred_direction}. "
                    f"Maintain similar layout structure and color tone."
                )

        return " ".join(strategy_parts)

    def _build_paper_summary(self, analysis: Dict) -> str:
        """构建论文摘要用于prompt注入（根据论文语言动态调整）"""
        title = analysis.get("title", "Unknown Paper")
        stages = analysis.get("stages", [])
        connections = analysis.get("connections", [])
        language = analysis.get("language", "en")

        if language == "en":
            summary = f"## Paper Title: {title}\n\n"
            summary += "## Methodology Stages\n"
            for i, stage in enumerate(stages, 1):
                summary += f"{i}. {stage.get('name', '')}: {stage.get('description', '')}\n"
                for mod in stage.get("modules", []):
                    mod_type = mod.get("type", "processing")
                    summary += f"   - [{mod_type}] {mod.get('name', '')}"
                    if mod.get("description"):
                        summary += f" — {mod['description']}"
                    if mod.get("parameters"):
                        summary += f" (params: {', '.join(mod['parameters'])})"
                    summary += "\n"
            summary += "\n## Module Connections\n"
            for conn in connections:
                summary += f"- {conn.get('source', '')} → {conn.get('target', '')} ({conn.get('type', 'sequential')})\n"
        else:
            summary = f"## 论文标题: {title}\n\n"
            summary += "## 方法阶段\n"
            for i, stage in enumerate(stages, 1):
                summary += f"{i}. {stage.get('name', '')}: {stage.get('description', '')}\n"
                for mod in stage.get("modules", []):
                    mod_type = mod.get("type", "processing")
                    summary += f"   - [{mod_type}] {mod.get('name', '')}"
                    if mod.get("description"):
                        summary += f" — {mod['description']}"
                    if mod.get("parameters"):
                        summary += f" (参数: {', '.join(mod['parameters'])})"
                    summary += "\n"
            summary += "\n## 模块连接\n"
            for conn in connections:
                summary += f"- {conn.get('source', '')} → {conn.get('target', '')} ({conn.get('type', 'sequential')})\n"

        return summary
