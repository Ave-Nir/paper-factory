"""
流程编排器 —— 负责 Stage 调度与 Gate 串联

原则：
- Orchestrator 只负责调度，不实现具体业务逻辑（业务在 Service 层）
- 每个 Stage 的输出必须经过 Gate 检查后才能进入下一阶段
- 禁止跨层调用、循环依赖
- 禁止静默吞错
"""
import re
import shutil
from pathlib import Path
from typing import List, Optional

from docx import Document
from docx.shared import Inches
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.text.paragraph import Paragraph

from ..config.settings import Settings
from ..models.diagram import DiagramResult
from ..services.diagram_service import DiagramService
from ..services.typeset_service import TypesetService, TypesetResult
from ..gates.quality_gates import InputGate, DiagramGate, TypesetGate, PdfStrictGate
from ..gates.structured_logger import get_logger, StructuredLogger  # 方向7
from ..gates.error_attribution import ErrorAttributor  # 方向10
from ..exceptions import (
    PipelineError, ValidationError, InsertionError,
    DiagramGenerationError, TypesetError,
)


class PipelineOrchestrator:
    """
    论文处理完整流程编排器

    步骤：
      1. Gate1: 输入校验
      2. Stage A: 生成 4 张流程图 (S0-S5)
      3. Gate2: 图质量校验
      4. Stage B: 将第 1 张图插入论文研究方法章节末尾
      5. Stage C: 排版 PDF
      6. Gate3: 排版质量校验（基本）
      7. Gate5: PDF 严格质量校验
    """

    def __init__(self, settings: Settings, logger: Optional[StructuredLogger] = None) -> None:
        self.settings = settings
        self.diagram_service = DiagramService(settings)
        self.typeset_service = TypesetService(settings)
        self.logger = logger or get_logger()  # 方向7：结构化日志
        self.attributor = ErrorAttributor()    # 方向10：错误归因器

    def run(self, paper_path: Path) -> None:
        """
        执行完整流程

        :param paper_path: 原始论文路径（.docx 或 .md）
        :raises PipelineError: 任意阶段失败
        """
        print("=" * 70)
        print("  论文处理完整流程")
        print("=" * 70)
        print(f"\n输入论文: {paper_path}")
        self.logger.info("Pipeline 启动", paper=str(paper_path))

        # --- Gate1: 输入校验 ---
        gate1_report = InputGate.check(paper_path)
        self._run_gate(gate1_report)
        self.logger.log_gate_result(
            gate1_report.gate_name, gate1_report.passed,
            gate1_report.errors, gate1_report.warnings,
        )

        # --- Stage A: 生成 4 张流程图 ---
        diagram_results = self._stage_generate_diagrams(paper_path)
        self.logger.info(
            "Stage A 完成",
            total=len(diagram_results),
            success=sum(1 for r in diagram_results if r.generated),
        )

        # --- Gate2: 图质量校验 ---
        gate2_report = DiagramGate.check(diagram_results)
        self._run_gate(gate2_report)
        self.logger.log_gate_result(
            gate2_report.gate_name, gate2_report.passed,
            gate2_report.errors, gate2_report.warnings,
            context=gate2_report.context,
        )

        # --- Stage B: 插入第 1 张图 ---
        modified_paper = self._stage_insert_diagram(paper_path, diagram_results[0])
        self.logger.info("Stage B 完成", modified_paper=str(modified_paper))

        # --- Stage C: 排版 PDF ---
        typeset_result = self._stage_typeset(modified_paper)
        self.logger.info(
            "Stage C 完成",
            pdf=str(typeset_result.pdf_path),
            pages=typeset_result.pages,
            elapsed_sec=typeset_result.elapsed_sec,
        )

        # --- Gate3: 排版质量校验（基本）---
        gate3_report = TypesetGate.check(
            typeset_result.pdf_path,
            typeset_result.tex_path,
            typeset_result.pages,
        )
        self._run_gate(gate3_report)
        self.logger.log_gate_result(
            gate3_report.gate_name, gate3_report.passed,
            gate3_report.errors, gate3_report.warnings,
            context=gate3_report.context,
        )

        # --- Gate5: PDF 严格质量校验（带自动修正循环）---
        gate5_report = None
        try:
            gate5_report = self._run_gate_with_auto_fix(
                typeset_result.pdf_path,
                typeset_result.tex_path,
                typeset_result.pages,
                template=self.settings.typeset.template,
            )
        except ValidationError as e:
            # Gate5 失败且修复失败，记录错误但继续输出日志
            self.logger.error("Gate5 检测未通过", errors=e.context.get("errors", []))
            # 创建一个失败的报告用于日志
            from ..gates.quality_gates import GateIssue
            gate5_report = type('GateReport', (), {
                'gate_name': 'PdfStrictGate',
                'passed': False,
                'errors': e.context.get("errors", []),
                'warnings': e.context.get("warnings", []),
                'issues': [GateIssue(**i) for i in e.context.get("issues", [])] if e.context.get("issues") else [],
            })()

        # 方向7：记录 Gate5 结果到结构化日志（含 issues）
        if gate5_report:
            issues_dicts = []
            if hasattr(gate5_report, 'issues') and gate5_report.issues:
                issues_dicts = [i.to_dict() if hasattr(i, 'to_dict') else i for i in gate5_report.issues]
            self.logger.log_gate_result(
                gate5_report.gate_name,
                gate5_report.passed,
                gate5_report.errors,
                gate5_report.warnings,
                issues=issues_dicts,
            )
            # 方向10：生成错误归因报告（使用结构化 issues）
            error_issues = [i for i in (gate5_report.issues or []) if hasattr(i, 'severity') and i.severity == "error"]
            if error_issues:
                attribution_path = self.settings.paths.work_dir / "error_attribution.json"
                error_codes = [i.error_code for i in error_issues if hasattr(i, 'error_code')]
                self.attributor.generate_report_from_codes(error_codes, attribution_path)
                self.logger.info("错误归因报告已生成", path=str(attribution_path))

        # --- 汇总 ---
        self._print_summary(diagram_results, modified_paper, typeset_result, gate5_report)
        # 方向7：保存结构化日志
        log_path = self.settings.paths.work_dir / "pipeline_log.json"
        self.logger.save_json(log_path)
        self.logger.info("Pipeline 完成", log=str(log_path))

    # ------------------------------------------------------------------
    # 各 Stage 实现
    # ------------------------------------------------------------------

    def _stage_generate_diagrams(self, paper_path: Path) -> List[DiagramResult]:
        """Stage A: 生成 4 张不同结构的流程图"""
        print("\n" + "=" * 70)
        print("  Stage A: 生成流程图 (S0-S5)")
        print("=" * 70)

        try:
            results = self.diagram_service.generate_diagrams(paper_path)
        except DiagramGenerationError:
            raise
        except Exception as e:
            raise DiagramGenerationError(
                message="生图 Stage 异常终止",
                stage="STAGE_A",
                context={"paper_path": str(paper_path)},
                cause=e,
            )

        success_count = sum(1 for r in results if r.generated)
        print(f"\n  -> 成功生成 {success_count}/{len(results)} 张图")
        for r in results:
            status = "✓" if r.generated else "✗"
            print(f"     {status} {r.candidate_id}: {r.image_path.name} ({r.size_kb:.1f} KB)")

        return results

    def _stage_insert_diagram(self, original_paper: Path, first_diagram: DiagramResult) -> Path:
        """
        Stage B: 将第 1 张图插入论文研究方法章节末尾

        支持 .docx、.md 和 .tex 三种格式：
        - .docx: 使用 python-docx 在方法章节最后一个段落后插入图片
        - .md:   在方法章节末尾（下一个同级或更高级标题之前）插入图片引用
        - .tex:  在方法章节末尾插入 figure 环境
        """
        print("\n" + "=" * 70)
        print("  Stage B: 插入研究框图")
        print("=" * 70)

        ext = original_paper.suffix.lower()
        if ext in (".md", ".markdown"):
            return self._insert_diagram_markdown(original_paper, first_diagram)
        elif ext == ".tex":
            return self._insert_diagram_tex(original_paper, first_diagram)
        else:
            return self._insert_diagram_docx(original_paper, first_diagram)

    def _insert_diagram_docx(self, original_paper: Path, first_diagram: DiagramResult) -> Path:
        """向 .docx 文件插入流程图，定位到方法章节末尾"""
        modified = self.settings.paths.work_dir / "论文_with_diagram.docx"
        shutil.copy2(original_paper, modified)

        doc = Document(str(modified))

        # 查找方法章节末尾段落
        target = self._find_docx_section_end(doc)
        if target is None:
            raise InsertionError(
                message="未找到研究方法相关章节",
                stage="STAGE_B",
                context={"keywords": self.settings.insertion.target_keywords},
            )

        section_title = target.text.strip()[:60] if target.text else "(空段落)"
        print(f"  -> 插入位置: 方法章节末尾，'{section_title}' 之后")

        # 插入图片
        img_para = self._insert_paragraph_after(target)
        run = img_para.add_run()
        run.add_picture(
            str(first_diagram.image_path),
            width=Inches(self.settings.insertion.image_width_inches),
        )
        img_para.alignment = WD_ALIGN_PARAGRAPH.CENTER

        # 插入图注
        caption_para = self._insert_paragraph_after(img_para)
        caption_para.add_run(self.settings.insertion.caption_text)
        caption_para.alignment = WD_ALIGN_PARAGRAPH.CENTER

        doc.save(str(modified))
        print(f"  -> 已保存: {modified.name}")

        return modified

    def _insert_diagram_markdown(self, original_paper: Path, first_diagram: DiagramResult) -> Path:
        """向 .md 文件插入流程图，定位到方法章节末尾"""
        modified = self.settings.paths.work_dir / "论文_with_diagram.md"
        shutil.copy2(original_paper, modified)

        with open(modified, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # 查找方法章节末尾行号
        insert_line = self._find_md_section_end(lines)
        if insert_line is None:
            raise InsertionError(
                message="未找到研究方法相关章节",
                stage="STAGE_B",
                context={"keywords": self.settings.insertion.target_keywords},
            )

        # 复制图片到论文同目录下的 images/ 子目录
        images_dir = modified.parent / "images"
        images_dir.mkdir(exist_ok=True)
        img_filename = "diagram_method.png"
        img_dst = images_dir / img_filename
        shutil.copy2(first_diagram.image_path, img_dst)

        # 构造 Markdown 图片引用
        img_ref = f"\n![{self.settings.insertion.caption_text}](images/{img_filename})\n"

        # 在方法章节末尾插入图片引用
        lines.insert(insert_line, img_ref)

        with open(modified, "w", encoding="utf-8") as f:
            f.writelines(lines)

        # 显示插入位置的上下文
        context_before = lines[max(0, insert_line - 2):insert_line]
        context_text = "".join(context_before).strip()[-60:]
        print(f"  -> 插入位置: 方法章节末尾，'{context_text}' 之后")

        print(f"  -> 已保存: {modified.name}")

        return modified

    def _insert_diagram_tex(self, original_paper: Path, first_diagram: DiagramResult) -> Path:
        """向 .tex 文件插入流程图，定位到方法章节末尾"""
        modified = self.settings.paths.work_dir / "论文_with_diagram.tex"
        shutil.copy2(original_paper, modified)

        with open(modified, "r", encoding="utf-8") as f:
            lines = f.readlines()

        # 查找方法章节末尾行号
        insert_line = self._find_tex_section_end(lines)
        if insert_line is None:
            raise InsertionError(
                message="未找到研究方法相关章节",
                stage="STAGE_B",
                context={"keywords": self.settings.insertion.target_keywords},
            )

        # 复制图片到论文同目录
        images_dir = modified.parent / "images"
        images_dir.mkdir(exist_ok=True)
        img_filename = "diagram_method.png"
        img_dst = images_dir / img_filename
        shutil.copy2(first_diagram.image_path, img_dst)

        # 确保 .tex 有 graphicspath
        has_graphicspath = any("\\graphicspath" in line for line in lines)
        if not has_graphicspath:
            # 在 \documentclass 之后插入
            for i, line in enumerate(lines):
                if "\\documentclass" in line:
                    lines.insert(i + 1, "\\graphicspath{{./}{./images/}}\n")
                    insert_line += 1
                    break

        # 构造 LaTeX figure 环境
        caption = self.settings.insertion.caption_text
        figure_env = (
            f"\n\\begin{{figure}}[htbp]\n"
            f"\\centering\n"
            f"\\includegraphics[width=\\textwidth]{{images/{img_filename}}}\n"
            f"\\caption{{{caption}}}\n"
            f"\\end{{figure}}\n"
        )

        # 在方法章节末尾插入 figure
        lines.insert(insert_line, figure_env)

        with open(modified, "w", encoding="utf-8") as f:
            f.writelines(lines)

        # 显示插入位置的上下文
        context_before = lines[max(0, insert_line - 2):insert_line]
        context_text = "".join(context_before).strip()[-60:]
        print(f"  -> 插入位置: 方法章节末尾，'{context_text}' 之后")

        print(f"  -> 已保存: {modified.name}")

        return modified

    def _stage_typeset(self, paper_path: Path) -> TypesetResult:
        """Stage C: 排版生成 PDF"""
        print("\n" + "=" * 70)
        print("  Stage C: 排版 PDF")
        print("=" * 70)

        try:
            result = self.typeset_service.typeset(paper_path, self.settings.paths.build_dir)
        except TypesetError:
            raise
        except Exception as e:
            raise TypesetError(
                message="排版 Stage 异常终止",
                stage="STAGE_C",
                context={"paper_path": str(paper_path)},
                cause=e,
            )

        status = "✓" if result.success else "✗"
        print(f"\n  -> {status} PDF: {result.pdf_path.name} ({result.pages} 页)")
        if result.errors:
            for err in result.errors:
                print(f"     [ERROR] {err}")
        if result.warnings:
            for warn in result.warnings:
                print(f"     [WARN]  {warn}")

        return result

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _run_gate(report) -> None:
        """执行 Gate 检查，失败则抛出 ValidationError"""
        print(f"\n[{report.gate_name}] {'PASS' if report.passed else 'FAIL'}")
        for err in report.errors:
            print(f"  [ERROR] {err}")
        for warn in report.warnings:
            print(f"  [WARN]  {warn}")

        if not report.passed:
            raise ValidationError(
                message=f"{report.gate_name} 检查未通过",
                stage=report.gate_name,
                context={"errors": report.errors, "warnings": report.warnings},
            )

    def _run_gate_with_auto_fix(
        self,
        pdf_path: Path,
        tex_path: Path,
        pages: int,
        template: str = "renai",
        max_retries: int = 3,
    ):
        """
        执行 Gate5 检查，失败时自动尝试修复并重新编译。
        输出结构化报告（含错误位置、类型、修复策略）。
        
        :param pdf_path: PDF 文件路径
        :param tex_path: LaTeX 源文件路径
        :param pages: PDF 页数
        :param template: 模板名称
        :param max_retries: 最大重试次数
        :return: 最终 Gate5 报告
        """
        from ..gates.quality_gates import PdfStrictGate, apply_fixes, GateIssue

        for attempt in range(1, max_retries + 1):
            print(f"\n{'='*70}")
            print(f"  Gate5: PDF 严格质量校验 (第 {attempt}/{max_retries} 次尝试)")
            print(f"{'='*70}")

            report = PdfStrictGate.check(pdf_path, pages, template)

            print(f"\n[PdfStrictGate] {'PASS' if report.passed else 'FAIL'}")
            # 使用结构化 issues 打印
            for issue in report.issues:
                level = "ERROR" if issue.severity == "error" else "WARN"
                loc_str = ""
                if issue.locations:
                    pages_found = sorted(set(loc.get("page", 0) for loc in issue.locations if loc.get("page")))
                    if pages_found:
                        loc_str = f" (第{','.join(map(str, pages_found))}页)"
                fix_str = " [可自动修复]" if issue.auto_fixable else ""
                print(f"  [{level}] [{issue.error_code}] {issue.message}{loc_str}{fix_str}")

            if report.passed:
                return report

            # 尝试自动修复（使用结构化 issues）
            auto_fixable_issues = [i for i in report.issues if i.auto_fixable and i.severity == "error"]
            if auto_fixable_issues and tex_path.exists():
                print("\n  -> 尝试自动修复...")
                # 将 issues 转换为错误消息格式（兼容现有修复函数）
                error_messages = [f"[{i.error_code}] {i.message}" for i in auto_fixable_issues]
                fix_results = apply_fixes(tex_path, error_messages, report.context)
                
                for issue in auto_fixable_issues:
                    success = fix_results.get(issue.error_code, False)
                    status = "✓" if success else "✗"
                    print(f"     {status} {issue.error_code}: {issue.fix_strategy or '自动修复'}")

                if any(fix_results.values()):
                    print("  -> 增量重编译 (xelatex) ...")
                    try:
                        # 目录类修复需要两次编译才能让 .toc 写入 PDF
                        toc_fixed = any(
                            fix_results.get(code, False)
                            for code in ("TOC_EMPTY", "TOC_INCOMPLETE")
                        )
                        compile_rounds = 2 if toc_fixed else 1
                        typeset_result = None
                        for round_idx in range(compile_rounds):
                            typeset_result = self.typeset_service.recompile_tex(
                                tex_path,
                                tex_path.parent,
                            )
                            pdf_path = typeset_result.pdf_path
                            pages = typeset_result.pages
                            if not typeset_result.success:
                                break
                        if typeset_result and typeset_result.success:
                            print(f"     ✓ 增量编译成功 ({pages} 页, {typeset_result.elapsed_sec:.1f}秒)"
                                  + (f" [目录 {compile_rounds} 次编译]" if toc_fixed else ""))
                            continue
                        else:
                            print(f"     ✗ 增量编译失败，回退到全量编译...")
                            typeset_result = self.typeset_service.typeset(
                                tex_path.parent / "论文_with_diagram.docx" if (tex_path.parent / "论文_with_diagram.docx").exists() else tex_path,
                                tex_path.parent,
                            )
                            pdf_path = typeset_result.pdf_path
                            pages = typeset_result.pages
                            if typeset_result.success:
                                print(f"     ✓ 全量编译成功 ({pages} 页)")
                                continue
                    except Exception as e:
                        print(f"     ✗ 重新编译失败: {e}")

            # 无法修复或修复失败，抛出异常（携带结构化 issues）
            raise ValidationError(
                message=f"PdfStrictGate 检查未通过，且自动修复失败",
                stage="PdfStrictGate",
                context={
                    "errors": report.errors,
                    "warnings": report.warnings,
                    "issues": [i.to_dict() for i in report.issues],
                },
            )

    # ------------------------------------------------------------------
    # .docx 插入位置检测
    # ------------------------------------------------------------------

    # 中文章节标题模式（用于无 Heading 样式的文档）
    # 支持中文顿号"、"、英文句点"."、全角句点"．"和空白符
    _CHAPTER_PATTERN = re.compile(r'^[一二三四五六七八九十]+[、\.．\s]')
    _NUMBERED_CHAPTER_PATTERN = re.compile(r'^\d+[、\.．\s]')
    # 数字编号章节模式（如 "1 Introduction", "2 Methods"）
    _NUMBERED_WORD_CHAPTER = re.compile(r'^\d+\.?\s+\w')

    def _find_docx_section_end(self, doc: Document) -> Optional[Paragraph]:
        """
        在 .docx 中查找研究方法章节的末尾段落。

        策略：
        1. 遍历段落，找到匹配关键词的标题段落（heading 或中文编号模式）
        2. 从该标题继续向后扫描，找到下一个同级或更高级的标题
        3. 返回该标题前的最后一个非空段落（即方法章节正文末尾）
        4. 若找不到下一个标题，返回文档最后一个非空段落
        """
        keywords = self.settings.insertion.target_keywords

        def _is_chapter_heading(text: str) -> bool:
            """判断文本是否为章节标题（中文编号、数字编号或数字+英文模式）"""
            return bool(
                self._CHAPTER_PATTERN.match(text)
                or self._NUMBERED_CHAPTER_PATTERN.match(text)
                or self._NUMBERED_WORD_CHAPTER.match(text)
            )

        def _extract_level(text: str) -> int:
            """从章节标题文本提取层级（一级标题=1，二级标题=2）"""
            # 中文"一、二、三"格式 → 一级
            if self._CHAPTER_PATTERN.match(text):
                return 1
            # 数字编号：检查是否有小数点（如 3.1 → 二级，1. → 一级）
            m = self._NUMBERED_CHAPTER_PATTERN.match(text)
            if m:
                num_part = m.group(0).strip('、.． ')
                if '.' in num_part:
                    return 2
                return 1
            # 数字+英文模式（如 "1 Introduction"）→ 一级
            if self._NUMBERED_WORD_CHAPTER.match(text):
                return 1
            return 1

        # 第一步：找到方法章节的标题段落
        method_heading_idx = None
        method_heading_level = None

        for i, para in enumerate(doc.paragraphs):
            text = para.text.strip()
            if not text or len(text) > 80:
                continue
            # 检查是否为 heading 样式
            is_heading = (
                para.style
                and para.style.name
                and para.style.name.startswith("Heading")
            )
            is_chapter = _is_chapter_heading(text)
            if not is_heading and not is_chapter:
                continue
            # 关键词匹配（不区分大小写）
            text_lower = text.lower()
            for kw in keywords:
                if kw.lower() in text_lower:
                    method_heading_idx = i
                    if is_heading:
                        level_match = re.search(r"(\d+)", para.style.name)
                        method_heading_level = int(level_match.group(1)) if level_match else 1
                    else:
                        method_heading_level = _extract_level(text)
                    break
            if method_heading_idx is not None:
                break

        if method_heading_idx is None:
            # 回退：找任意包含关键词的短段落
            for i, para in enumerate(doc.paragraphs):
                text = para.text.strip()
                if not text or len(text) > 60:
                    continue
                text_lower = text.lower()
                for kw in keywords:
                    if kw.lower() in text_lower:
                        method_heading_idx = i
                        method_heading_level = _extract_level(text)
                        break
                if method_heading_idx is not None:
                    break

        if method_heading_idx is None:
            return None

        # 第二步：从方法标题向后扫描，找下一个同级或更高级标题
        paras = doc.paragraphs
        for j in range(method_heading_idx + 1, len(paras)):
            para = paras[j]
            text = para.text.strip()
            if not text:
                continue

            # 检查是否为 heading 样式
            is_heading = (
                para.style
                and para.style.name
                and para.style.name.startswith("Heading")
            )
            is_chapter = _is_chapter_heading(text)

            if not is_heading and not is_chapter:
                continue

            # 提取层级
            if is_heading:
                level_match = re.search(r"(\d+)", para.style.name)
                next_level = int(level_match.group(1)) if level_match else 1
            else:
                next_level = _extract_level(text)

            # 同级或更高级（level <= method_level）意味着新章节开始
            if next_level <= method_heading_level:
                # 返回前一个非空段落
                for k in range(j - 1, method_heading_idx, -1):
                    if paras[k].text.strip():
                        return paras[k]
                # 方法章节内无内容，返回标题本身
                return paras[method_heading_idx]

        # 没有找到下一个 heading：返回文档最后一个非空段落
        for k in range(len(paras) - 1, method_heading_idx, -1):
            if paras[k].text.strip():
                return paras[k]

        return paras[method_heading_idx]

    # ------------------------------------------------------------------
    # .md 插入位置检测
    # ------------------------------------------------------------------

    def _find_md_section_end(self, lines: List[str]) -> Optional[int]:
        """
        在 Markdown 行列表中查找研究方法章节末尾的行号。

        策略：
        1. 找到匹配关键词的 Markdown 标题行（# / ## / ### 等）
        2. 记录其层级（# 的数量）
        3. 向后扫描，找到下一个同级或更高级标题行
        4. 返回该标题行的行号（图片将插入到此行之前）
        5. 若找不到下一个标题，返回最后一行的行号
        """
        keywords = self.settings.insertion.target_keywords
        heading_re = re.compile(r'^(#{1,6})\s+(.+?)\s*#*\s*$')

        # 第一步：找到方法章节标题
        method_line = None
        method_level = None

        for i, line in enumerate(lines):
            m = heading_re.match(line)
            if not m:
                continue
            title = m.group(2).strip()
            title_lower = title.lower()
            for kw in keywords:
                if kw.lower() in title_lower:
                    method_line = i
                    method_level = len(m.group(1))
                    break
            if method_line is not None:
                break

        if method_line is None:
            return None

        # 第二步：向后扫描，找下一个同级或更高级标题
        for j in range(method_line + 1, len(lines)):
            m = heading_re.match(lines[j])
            if not m:
                continue
            next_level = len(m.group(1))
            if next_level <= method_level:
                # 跳过中间的空行，找到最后一个非空行的下一行
                insert_at = j
                # 向前回退空行，使图片插入在正文之后、空行之前
                while insert_at > 0 and lines[insert_at - 1].strip() == "":
                    insert_at -= 1
                return insert_at

        # 没有找到下一个标题：返回末尾
        return len(lines)

    # ------------------------------------------------------------------
    # .tex 插入位置检测
    # ------------------------------------------------------------------

    def _find_tex_section_end(self, lines: List[str]) -> Optional[int]:
        r"""
        在 LaTeX 行列表中查找研究方法章节末尾的行号。

        策略：
        1. 找到匹配关键词的 \section 或 \subsection 命令行
        2. 记录其层级（section=1, subsection=2, subsubsection=3）
        3. 向后扫描，找到下一个同级或更高级的 \section/\subsection 命令
        4. 返回该命令行的行号（figure 将插入到此行之前）
        5. 若找不到下一个标题，在 \end{document} 前插入
        """
        keywords = self.settings.insertion.target_keywords
        # 匹配 \section{...}, \section*{...}, \subsection{...} 等
        heading_re = re.compile(
            r'^\\(section|subsection|subsubsection)\*?\s*\{([^}]*)\}'
        )

        # 第一步：找到方法章节标题
        method_line = None
        method_level = None

        for i, line in enumerate(lines):
            m = heading_re.match(line)
            if not m:
                continue
            cmd = m.group(1)
            title = m.group(2).strip()
            title_lower = title.lower()
            for kw in keywords:
                if kw.lower() in title_lower:
                    method_line = i
                    method_level = {"section": 1, "subsection": 2, "subsubsection": 3}[cmd]
                    break
            if method_line is not None:
                break

        if method_line is None:
            return None

        # 第二步：向后扫描，找下一个同级或更高级标题
        for j in range(method_line + 1, len(lines)):
            m = heading_re.match(lines[j])
            if not m:
                continue
            cmd = m.group(1)
            next_level = {"section": 1, "subsection": 2, "subsubsection": 3}[cmd]
            if next_level <= method_level:
                # 回退空行
                insert_at = j
                while insert_at > 0 and lines[insert_at - 1].strip() == "":
                    insert_at -= 1
                return insert_at

        # 没有找到下一个标题：在 \end{document} 之前插入
        for j in range(len(lines) - 1, method_line, -1):
            if "\\end{document}" in lines[j]:
                insert_at = j
                while insert_at > 0 and lines[insert_at - 1].strip() == "":
                    insert_at -= 1
                return insert_at

        return len(lines)

    # ------------------------------------------------------------------
    # 通用辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _insert_paragraph_after(para: Paragraph) -> Paragraph:
        """在段落后插入新空段落"""
        new_p = OxmlElement("w:p")
        para._p.addnext(new_p)
        return Paragraph(new_p, para._parent)

    @staticmethod
    def _print_summary(
        diagrams: List[DiagramResult],
        modified_paper: Path,
        typeset: TypesetResult,
        gate5_report=None,
    ) -> None:
        print("\n" + "=" * 70)
        print("  流程执行完毕")
        print("=" * 70)
        print(f"\n  4 张流程图:")
        for i, d in enumerate(diagrams, 1):
            status = "✓" if d.generated else "✗"
            print(f"    {i}. {status} {d.candidate_id} -> {d.image_path.name}")
        print(f"\n  修改后论文: {modified_paper}")
        print(f"  排版 PDF:   {typeset.pdf_path} ({typeset.pages} 页)")
        if gate5_report:
            print(f"\n  Gate5 检测: {'PASS' if gate5_report.passed else 'FAIL'}")
            if gate5_report.errors:
                print(f"    错误: {len(gate5_report.errors)} 项")
            if gate5_report.warnings:
                print(f"    警告: {len(gate5_report.warnings)} 项")
