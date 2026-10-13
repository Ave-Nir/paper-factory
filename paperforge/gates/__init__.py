"""
Gate System — 四级门控验证系统

Gate 1 (Pre-Write):   模板合法性 + 数据完整性 + 引用可用性
Gate 2 (Per-Section): 逐节编译 + 标签检查 + 页数预估
Gate 3 (Full-Build):  全文编译 + 交叉引用 + 图表完整性
Gate 4 (Final-Audit): 页数限制 + 匿名性 + 图表引用完整性
"""

from .gate_system import (
    BaseGate,
    Gate1PreWrite,
    Gate2PerSection,
    Gate3FullBuild,
    Gate4FinalAudit,
)