"""
布局变体定义 —— 借鉴 paper-framework-figure-studio-pro 的候选变体机制
提供12种探索变体（R1轮）和8种正式变体（R2轮），覆盖多种学术图表布局风格
"""
from typing import List, Dict


def get_exploration_variants(count: int = 8) -> List[Dict[str, str]]:
    """
    第一轮探索变体（R1），用于全局探索不同的布局和配色方向
    默认生成C01-C08，最多可扩展到C12
    """
    all_variants = [
        {
            "id": "C01",
            "identity": "经典水平管线 —— 标准学术论文布局，矩形模块+实心箭头",
            "layout": "horizontal left-to-right pipeline with rectangular module boxes",
            "color": "soft gray-blue palette (primary: #2c5aa0, accents: #8ba8c9, background: white with subtle #f5f7fa grid)",
            "style": "academic line-art schematic, white background, clean sans-serif labels",
        },
        {
            "id": "C02",
            "identity": "中心压缩布局 —— 输入在左，压缩表示在中心，输出在右",
            "layout": "hourglass / autoencoder layout (input → encoder → latent → decoder → output)",
            "color": "teal-orange complementary palette (primary: #2a9d8f, #e76f51, background: white)",
            "style": "soft gradient-filled boxes, subtle drop shadows, bold arrows",
        },
        {
            "id": "C03",
            "identity": "双轨训练/推理 —— 两条平行通道共享一个核心模块",
            "layout": "two-column layout: training lane on top / left, inference lane on bottom / right, shared backbone in center",
            "color": "purple-green palette (training: #7a5195, inference: #4caf50, shared: #555555, background: white)",
            "style": "architectural diagram with dashed boundaries for lanes, solid edges for forward flow",
        },
        {
            "id": "C04",
            "identity": "垂直层叠 —— 深度模型纵向层叠，带跳跃连接",
            "layout": "vertical stack, input at bottom, output at top, with drawn skip-connection arrows where relevant",
            "color": "monochrome navy with coral accent for skip connections (#1a365d primary, #e87461 accent)",
            "style": "layer-box schematic typical of CNN/transformer architecture diagrams",
        },
        {
            "id": "C05",
            "identity": "数据流强调 —— 节点为圆形，连接线为粗箭头标注数据类型",
            "layout": "graph-theory style with nodes as circles, weighted arrows, source on left, sink on right",
            "color": "dark blue and amber (nodes: #1f3b66, edges: #d97706, background: #f8fafc)",
            "style": "flow-diagram style with small port labels, emphasizing information flow over modules",
        },
        {
            "id": "C06",
            "identity": "展开模块视图 —— 每个主模块展开为简化内部子图",
            "layout": "exploded view: main boxes contain a simplified internal sub-diagram (e.g., 2-3 internal blocks)",
            "color": "warm brown and cream (#6d4c41 on #fff8e1 background, teal #00838f accents)",
            "style": "slightly more detailed but still clean; each module shows 2-3 internal sub-components",
        },
        {
            "id": "C07",
            "identity": "极简线框 —— 非常稀疏，强调结构而非装饰，适合布局对比",
            "layout": "thin-outlined boxes, minimal arrows, grid-aligned",
            "color": "grayscale only (#333333 lines on white, #999999 for dashed references)",
            "style": "pure line-art schematic, no fills, no shadows, thin arrows",
        },
        {
            "id": "C08",
            "identity": "图标增强图 —— 每个模块标签旁有小型语义图标，便于快速扫描",
            "layout": "horizontal pipeline with small consistent icons (16x16 pixel size, simple line icons) next to module names",
            "color": "classic academic palette: #3d5a80 (blue), #98c1d9 (light accent), #293241 (dark text) on white",
            "style": "icon-labeled boxes, arrows carry short variable-name labels; icons are minimal vector-style",
        },
        {
            "id": "C09",
            "identity": "漏斗式 —— 输入宽，经过压缩阶段后输出变窄",
            "layout": "funnel / tapered diagram where modules decrease in visual width from input to bottleneck then expand",
            "color": "blue-to-violet gradient (#1976d2 at input side, #7b1fa2 at output side)",
            "style": "tapered schematic emphasizing information compression and dimensionality change",
        },
        {
            "id": "C10",
            "identity": "信号轨迹式 —— 模块旁有简化的数据/轨迹面板",
            "layout": "center pipeline with side panels showing stylized input data / output traces (simplified rectangles/waves)",
            "color": "forest green and slate (#2e7d32 pipeline on #37474f side panels, white background)",
            "style": "mixed block + trace-panel diagram; side panels are highly schematic, not actual data plots",
        },
        {
            "id": "C11",
            "identity": "UML组件图 —— 显式端口标注，类型化输入/输出",
            "layout": "UML-component-diagram style: small circles (ports) on box edges, typed arrows between ports",
            "color": "navy-and-orange UML palette (#0d47a1 components, #e65100 typed arrows)",
            "style": "formal engineering schematic with typed arrows and small port glyphs",
        },
        {
            "id": "C12",
            "identity": "叙事分镜式 —— 框用叙事箭头连接，展示方法进展",
            "layout": "storyboard grid, 3-4 panels showing progression through the method",
            "color": "muted earth tones (#5d4037, #8d6e63) on cream background",
            "style": "storyboard panels with very short arrows and minimal labels per panel",
        },
    ]
    return all_variants[:max(4, min(count, 12))]


def get_formal_variants(count: int = 6, preferred_direction: str = "") -> List[Dict[str, str]]:
    """
    第二轮正式变体（R2），更精致、面向出版
    基于R1偏好方向进行local-essence refinement
    """
    all_variants = [
        {
            "id": "F01",
            "identity": "最终精修标准管线 —— 出版就绪，白底，优化IEEE/ACM双栏",
            "layout": "horizontal pipeline with carefully sized rectangular modules, consistent arrows",
            "color": "authoritative CS-paper palette: dark #1b3a57 (primary), #4a90c2 (accent), #f0f4f8 (light panels) on pure white background",
            "style": "final publication schematic with clean sans-serif labels and no decorative elements",
        },
        {
            "id": "F02",
            "identity": "双面板训练/推理变体 —— 强调方法的双模式操作",
            "layout": "side-by-side panels: left = Training Flow, right = Inference Flow, shared modules shown with dashed connection",
            "color": "training panel: #5e35b1 + #b39ddb; inference panel: #00695c + #80cbc4; shared: #424242; all on white",
            "style": "architectural schematic with explicit Training/Inference lane boundaries",
        },
        {
            "id": "F03",
            "identity": "垂直层叠最终版 —— 强调深度和层次化特征处理",
            "layout": "vertical layer stack with horizontal arrows; input at bottom, output at top; skip-connections drawn as curved arrows",
            "color": "navy gradient layers (#0d47a1 bottom → #1976d2 top) on light #e3f2fd background, orange #ef6c00 for skip arrows",
            "style": "deep-architecture schematic typical of transformer/CNN papers",
        },
        {
            "id": "F04",
            "identity": "潜空间中心图 —— 编码器在左，潜空间在中心高亮，解码器在右",
            "layout": "symmetric hourglass with central latent space node highlighted",
            "color": "teal + amber: #006064 encoders, #ff8f00 central latent emphasized, #00897b decoders, white background",
            "style": "symmetric schematic with central latent node visually heavier/darker for emphasis",
        },
        {
            "id": "F05",
            "identity": "模块端口连接最终版 —— UML风格，显式输入/输出端口",
            "layout": "components as boxes with small port circles on edges; arrows connect specific ports with type labels",
            "color": "formal engineering palette: #263238 boxes, #8d6e63 arrows with small type labels, white background, #90a4ae dashed reference lines",
            "style": "engineering schematic with typed arrows and small port glyphs on module edges",
        },
        {
            "id": "F06",
            "identity": "极简高对比最终版 —— 更粗线条，更少颜色，优化灰度打印",
            "layout": "clean rectangular pipeline, uniform spacing, slightly bolder box boundaries",
            "color": "high-contrast: #212121 near-black lines, #424242 labels, #bdbdbd dashed secondary arrows on pure white",
            "style": "print-optimized line-art; works well in grayscale and at small sizes",
        },
        {
            "id": "F07",
            "identity": "内部展开最终版 —— 每个模块包含2-3步简化内部子图",
            "layout": "horizontal pipeline where each main box shows an exploded 2-3 element mini-schematic of its internals",
            "color": "slate blue primary (#283593), warm orange accent (#fb8c00), light gray inner sub-box lines",
            "style": "detailed-but-clean; suitable when the paper's novelty is in internal module design",
        },
        {
            "id": "F08",
            "identity": "数据流加权最终版 —— 箭头粗细反映数据量或重要性",
            "layout": "graph-theory flow diagram with nodes; arrow thickness / darkness signals data volume or gradient flow magnitude",
            "color": "#1a237e nodes of varying size, arrow thickness proportional to signal importance, white background",
            "style": "weighted-graph schematic emphasizing information flow and critical pathways",
        },
    ]

    selected = all_variants[:max(4, min(count, 8))]
    if preferred_direction:
        selected[0]["identity"] = f"[偏好方向: {preferred_direction}] {selected[0]['identity']}"
    return selected
