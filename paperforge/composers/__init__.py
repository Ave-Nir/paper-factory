"""
Section Composers — 各章节的 LaTeX 编写器

每个 Composer 继承 BaseSectionComposer，实现 _render() 方法。
compose() 方法是 final 的，保证 pre/post-validation 始终执行。
"""

from .section_composer import (
    BaseSectionComposer,
    SectionValidationError,
    IntroductionComposer,
    RelatedWorkComposer,
    MethodComposer,
    ExperimentsComposer,
    ConclusionComposer,
    AbstractComposer,
    # 工具函数
    escape_latex,
    escape_latex_math,
    wrap_figure,
    wrap_table,
    wrap_equation,
)