"""
配色方案定义 —— 从用户提供的图片中提取的专业配色方案
"""
from dataclasses import dataclass, field
from typing import List, Dict


@dataclass
class ColorPalette:
    """配色方案"""
    name: str = ""
    description: str = ""
    primary_colors: List[str] = field(default_factory=list)
    secondary_colors: List[str] = field(default_factory=list)
    accent_colors: List[str] = field(default_factory=list)
    background_light: str = "#FFFFFF"
    background_medium: str = "#F8FAFC"


COLOR_PALETTES: Dict[str, ColorPalette] = {
    "ocean_breeze": ColorPalette(
        name="海洋清风",
        description="蓝色与橙色的清新搭配，适合科技、工程类论文",
        primary_colors=["#51999F", "#4198AC", "#7BC0CD"],
        secondary_colors=["#BFDDFD", "#DBCB92", "#ECB66C"],
        accent_colors=["#EA9E58", "#ED8D5A"],
        background_light="#F0F7FC",
        background_medium="#E6F0F9",
    ),
    "pink_girl": ColorPalette(
        name="粉彩少女",
        description="紫色与粉色的温柔搭配，适合社会科学、人文类论文",
        primary_colors=["#B6B3D6", "#CFCDE3", "#D5D3DE"],
        secondary_colors=["#D5D1D1", "#F6DFD6", "#F8B2A2"],
        accent_colors=["#F1837A", "#E9687A"],
        background_light="#F9F6FA",
        background_medium="#F0EAEE",
    ),
    "forest_green": ColorPalette(
        name="柔绿森林",
        description="绿色与棕色的自然搭配，适合环境、生态类论文",
        primary_colors=["#86BC79", "#71A682", "#81989B"],
        secondary_colors=["#B8DBB3", "#B5AF8B", "#7EA4B6"],
        accent_colors=["#D19246", "#4A4F7E"],
        background_light="#F2F7F3",
        background_medium="#EBF5E0",
    ),
    "summer_beach": ColorPalette(
        name="夏日海滩",
        description="珊瑚色与青色的活力搭配，适合能源、材料类论文",
        primary_colors=["#F97F5F", "#FAA26F", "#3C9BC9"],
        secondary_colors=["#FC757B", "#FEE199", "#B0D6A9"],
        accent_colors=["#65BDBA", "#FEE199"],
        background_light="#FFF5F3",
        background_medium="#FDF5E0",
    ),
    "fresh_holiday": ColorPalette(
        name="清新假日",
        description="薄荷绿与蓝色的清爽搭配，适合计算机、数据科学类论文",
        primary_colors=["#6AD1A3", "#7FBDDA", "#84ADDC"],
        secondary_colors=["#BBC7BE", "#FFD47D", "#FFA288"],
        accent_colors=["#C49892", "#929EAB"],
        background_light="#F2FAF6",
        background_medium="#EBF5E0",
    ),
}


def get_palette(name: str) -> ColorPalette:
    """获取配色方案"""
    return COLOR_PALETTES.get(name, COLOR_PALETTES["ocean_breeze"])


def list_palettes() -> Dict[str, str]:
    """列出所有配色方案"""
    return {name: palette.name for name, palette in COLOR_PALETTES.items()}


def random_palette() -> ColorPalette:
    """随机选择一个配色方案"""
    import random
    return random.choice(list(COLOR_PALETTES.values()))
