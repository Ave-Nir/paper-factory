# -*- coding: utf-8 -*-
"""
paperforge.workflows.tex_typeset - .tex 文件排版工作流

将已有 .tex 论文文件经 tex_normalizer → tex_reader → render_enhanced_latex
完整 PaperForge 管道重新排版，输出 PDF + Word。

严格 Gate5 质量控制：ERROR 级问题拒绝输出。

架构:
  Step 0: tex_normalizer — 规范化混合语法（**→textbf, ###→subsubsection, pipe→table）
  Step 1: tex_reader — 解析 .tex → DocumentContent blocks（数学公式保留）
  Step 2: render_enhanced_latex — blocks → LaTeX（renai 模板，xeCJK 中文）
  Step 3: latex_cleaner — Unicode/粗体/tag 修复
  Step 4: Gate5 — 格式卫生校验（ERROR → 中止，拒绝输出）
  Step 5: xelatex × 3 → PDF
  Step 6: word_builder → Word

用法:
    python -m paperforge.workflows.tex_typeset input.tex -o output_dir -t renai
"""

import os
import sys
import argparse
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class TexTypesetResult:
    """排版结果"""
    pdf_path: str = ""
    word_path: str = ""
    tex_path: str = ""
    pages: int = 0
    success: bool = False
    gate5_passed: bool = False
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def summary(self) -> str:
        status = "OK" if self.success else "FAILED"
        lines = [f"TexTypeset: {status}"]
        if self.pdf_path:
            lines.append(f"  PDF: {self.pdf_path} ({self.pages} pages)")
        if self.word_path:
            lines.append(f"  Word: {self.word_path}")
        if not self.gate5_passed:
            lines.append(f"  Gate5: BLOCKED")
        for e in self.errors[:5]:
            lines.append(f"  [ERR] {e}")
        for w in self.warnings[:5]:
            lines.append(f"  [WARN] {w}")
        return "\n".join(lines)


def typeset_tex(
    tex_path: str,
    output_dir: str,
    template: str = "renai",
    generate_word: bool = True,
    miktex_path: Optional[str] = None,
) -> TexTypesetResult:
    """将 .tex 论文经完整 PaperForge 管道排版为 PDF + Word。

    Gate5 严格模式：任何 ERROR 级问题 → 中止，不产出 PDF/Word。
    """
    result = TexTypesetResult()

    if not os.path.exists(tex_path):
        result.errors.append(f"输入文件不存在: {tex_path}")
        return result

    paperforge_root = Path(__file__).resolve().parents[1]
    if str(paperforge_root) not in sys.path:
        sys.path.insert(0, str(paperforge_root))

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "images").mkdir(exist_ok=True)

    # =========================================================================
    # Step 0: tex_normalizer — 规范化混合 Markdown/LaTeX 语法
    # =========================================================================
    print(f"\n[Step 0] tex_normalizer: 规范化混合语法...")
    from core.tex_normalizer import normalize_tex
    raw_content = Path(tex_path).read_text(encoding="utf-8")
    normalized_content, norm_stats = normalize_tex(raw_content)
    if any(v for v in norm_stats.values() if isinstance(v, int) and v > 0):
        parts = [f"{k}: {v}" for k, v in norm_stats.items() if v]
        print(f"  Fixed: {', '.join(parts)}")

    # 写入临时规范化文件供 tex_reader 解析
    norm_path = out / "_normalized.tex"
    norm_path.write_text(normalized_content, encoding="utf-8")
    print(f"  规范化文件: {norm_path}")

    # =========================================================================
    # Step 1: tex_reader — .tex → DocumentContent blocks（数学公式保留）
    # =========================================================================
    print(f"\n[Step 1] tex_reader: 解析 .tex → 结构化 blocks...")
    from core.tex_reader import read_tex
    doc = read_tex(str(norm_path))
    print(f"  Blocks: {len(doc.blocks)} | Images: {len(doc.images)} | Tables: {len(doc.tables)}")
    if not doc.blocks:
        result.errors.append("tex_reader 未提取到任何内容块")
        return result

    # =========================================================================
    # Step 2: render_enhanced_latex — blocks → LaTeX（renai 模板）
    # =========================================================================
    print(f"\n[Step 2] render_enhanced_latex: blocks → LaTeX (template={template})...")
    from config.process_lunwen_v4 import render_enhanced_latex
    from core.formatting import PRESET_FORMATS
    format_spec = PRESET_FORMATS.get(template)
    tex_content = render_enhanced_latex(doc, str(out), format_spec=format_spec, template=template)

    built_tex = out / "paper.tex"
    built_tex.write_text(tex_content, encoding="utf-8")
    result.tex_path = str(built_tex)
    print(f"  保存: {built_tex} ({len(tex_content)} chars)")

    # =========================================================================
    # Step 3: latex_cleaner — 清洗 LaTeX
    # =========================================================================
    print(f"\n[Step 3] latex_cleaner: 清洗 LaTeX...")
    from core.latex_cleaner import clean_tex_file
    clean_stats = clean_tex_file(built_tex)
    if any(v for v in clean_stats.values() if isinstance(v, int) and v > 0):
        parts = []
        for k, v in clean_stats.items():
            if isinstance(v, int) and v > 0:
                parts.append(f"{k}: {v}")
        if parts:
            print(f"  Fixed: {', '.join(parts)}")
    tex_content = built_tex.read_text(encoding="utf-8")

    # =========================================================================
    # Step 4: Gate5 — 格式卫生校验（严格模式）
    # =========================================================================
    print(f"\n[Step 4] Gate5: 格式卫生校验（严格模式）...")
    from core.latex_cleaner import validate_clean
    gate5_issues = validate_clean(tex_content)
    if gate5_issues:
        has_errors = any(sev == 'error' for sev, _, _ in gate5_issues)
        for severity, code, msg in gate5_issues:
            tag = "ERROR" if severity == "error" else "WARN"
            print(f"  [{tag}] [{code}] {msg}")

        if has_errors:
            error_count = len([i for i in gate5_issues if i[0] == 'error'])
            print(f"\n  [Gate5 BLOCKED] {error_count} 个 ERROR 级问题，拒绝输出。")
            print(f"  请修复以上问题后重新排版。")
            result.errors.append(f"Gate5 阻断: {error_count} 个 ERROR 级格式问题")
            result.gate5_passed = False
            return result
        else:
            print(f"  Gate5: WARN only, 继续编译...")
    else:
        print(f"  Gate5: PASS")
    result.gate5_passed = True

    # =========================================================================
    # Step 5: xelatex → PDF
    # =========================================================================
    print(f"\n[Step 5] xelatex × 3: 编译 PDF...")
    from core.latex_compiler import LaTeXCompiler
    compiler = LaTeXCompiler(timeout=180, miktex_path=miktex_path)
    compile_result = compiler.compile(str(built_tex), str(out), engine="xelatex")

    if compile_result.success and compile_result.pdf_path:
        result.pdf_path = compile_result.pdf_path
        result.success = True
    else:
        # 检查是否实际产生了 PDF（非致命错误可能仍有产出）
        expected_pdf = str(out / "paper.pdf")
        if os.path.exists(expected_pdf) and os.path.getsize(expected_pdf) > 1024:
            result.pdf_path = expected_pdf
            result.success = True
            if compile_result.errors:
                result.warnings.extend(compile_result.errors[:5])
        else:
            result.errors.extend(compile_result.errors or ["编译失败"])

    # V7.6: Gate5 严格模式 — 仅阻断致命编译错误（无法产出具可读PDF）
    xelatex_fatal = []
    for e in (compile_result.errors or []):
        # 致命错误：Emergency stop, Fatal error
        if any(kw in e for kw in ("Emergency stop", "Fatal error", "runaway")):
            xelatex_fatal.append(e)

    if xelatex_fatal:
        print(f"\n  [Gate5 BLOCKED] xelatex 致命编译错误，拒绝输出：")
        for e in xelatex_fatal[:3]:
            print(f"    {e}")
        result.gate5_passed = False
        result.errors.append(f"xelatex 致命编译错误: {xelatex_fatal[0][:120]}")
        return result

    # V7.6: 非致命编译错误/警告 → 记录但不阻断
    non_fatal = [e for e in (compile_result.errors or []) if e not in xelatex_fatal]
    if non_fatal:
        for e in non_fatal[:5]:
            print(f"  [WARN] xelatex: {e[:100]}")
        result.warnings.extend(non_fatal[:5])

    if result.success:
        try:
            import fitz
            pdf_doc = fitz.open(result.pdf_path)
            result.pages = pdf_doc.page_count
            pdf_doc.close()
        except Exception:
            result.pages = -1
        print(f"  PDF: {result.pdf_path} ({result.pages} pages)")
    else:
        for e in (compile_result.errors or [])[:3]:
            print(f"  [ERR] {e}")

    # =========================================================================
    # Step 6: Word 生成
    # =========================================================================
    if generate_word and result.success:
        print(f"\n[Step 6] word_builder: 生成 Word...")
        try:
            from core.word_builder import WordDocumentBuilder
            builder = WordDocumentBuilder(format_spec=format_spec if 'format_spec' in dir() else None)
            word_path = builder.build_from_blocks(
                blocks=doc.blocks,
                title=None,
                author="",
                output_dir=str(out),
                filename="paper",
                images_map={},
                tables_map={},
            )
            result.word_path = word_path
            print(f"  Word: {word_path}")
        except Exception as e:
            result.warnings.append(f"Word 生成异常: {e}")

    # =========================================================================
    # Step 6.5: Gate5 Word 质检（V7.6 新增）
    # =========================================================================
    if generate_word and result.success and result.word_path:
        print(f"\n[Step 6.5] Gate5 Word 质检...")
        try:
            from core.latex_cleaner import validate_word
            word_issues = validate_word(result.word_path)
            if word_issues:
                has_errors = any(sev == 'error' for sev, _, _ in word_issues)
                for severity, code, msg in word_issues:
                    tag = "ERROR" if severity == "error" else "WARN"
                    print(f"  [{tag}] [{code}] {msg}")

                if has_errors:
                    error_count = len([i for i in word_issues if i[0] == 'error'])
                    print(f"\n  [Gate5 BLOCKED] Word 质检: {error_count} 个 ERROR 级问题")
                    print(f"  回滚: 删除不合格的 Word 输出")
                    # 回滚：删除 Word 文件
                    try:
                        os.remove(result.word_path)
                        result.word_path = ""
                        result.errors.append(f"Gate5 Word 质检阻断: {error_count} 个 ERROR，Word 已回滚删除")
                    except Exception as e:
                        result.warnings.append(f"Word 回滚删除失败: {e}")
                else:
                    print(f"  Gate5 Word: WARN only, 保留输出")
            else:
                print(f"  Gate5 Word: PASS")
        except Exception as e:
            result.warnings.append(f"Word 质检异常: {e}")

    print(f"\n{'='*60}")
    print(result.summary())
    print(f"{'='*60}")
    return result


def main():
    parser = argparse.ArgumentParser(description="tex_typeset - .tex 排版 (PDF + Word)")
    parser.add_argument("input", help="输入 .tex 文件路径")
    parser.add_argument("-o", "--output", default=None, help="输出目录")
    parser.add_argument("-t", "--template", default="renai", help="模板名")
    parser.add_argument("--miktex", default=None, help="MiKTeX bin 路径")
    parser.add_argument("--no-word", action="store_true", help="仅 PDF")

    args = parser.parse_args()
    if not args.output:
        base = os.path.splitext(os.path.basename(args.input))[0]
        args.output = os.path.join(os.path.dirname(args.input) or ".", f"build_{base}")

    result = typeset_tex(
        tex_path=args.input,
        output_dir=args.output,
        template=args.template,
        generate_word=not args.no_word,
        miktex_path=args.miktex,
    )
    if not result.success:
        sys.exit(1)


if __name__ == "__main__":
    main()
