"""
Gate System —— 四级门控系统。

设计原则：
- 每级 Gate 独立检查，返回 GateReport
- FAIL 硬阻止，WARN 允许继续但记录
- 每个 Diagnostic 带有具体位置和修复建议
- 使用统一的 MikTeXResolver 进行路径检测
"""

import os
import re
import subprocess
from abc import ABC, abstractmethod
from typing import Optional

from core.types import (
    Diagnostic, DiagnosticSeverity, GateReport, LaTeXBlock,
    PaperSpec, ReferenceDB, CompileResult,
)
from core.template_engine import ResolvedTemplate
from core.utils.miktex import MikTeXResolver


class BaseGate(ABC):
    """门控基类"""
    
    gate_name: str = ""
    gate_level: int = 0
    
    @abstractmethod
    def check(self, **kwargs) -> GateReport:
        """执行检查，返回 GateReport"""
        ...


# ============================================================================
# Gate 1: Pre-Write —— 写前检查
# ============================================================================

class Gate1PreWrite(BaseGate):
    gate_name = "Gate1-PreWrite"
    gate_level = 1
    
    def check(
        self,
        paper_spec: PaperSpec,
        section_data_map: dict[str, dict],
        ref_db: ReferenceDB,
        template: ResolvedTemplate,
    ) -> GateReport:
        diagnostics = []
        
        # 1. 检查模板配置合法性
        template_valid, template_errors = self._check_template(template)
        if not template_valid:
            for err in template_errors:
                diagnostics.append(Diagnostic(
                    severity=DiagnosticSeverity.ERROR,
                    location="template",
                    message=err,
                ))
        
        # 2. 检查必需章节数据是否存在
        for section_name in template.section_order:
            if section_name not in section_data_map:
                diagnostics.append(Diagnostic(
                    severity=DiagnosticSeverity.ERROR,
                    location=f"section_data.{section_name}",
                    message=f"Missing section data for '{section_name}'",
                    fix_suggestion=f"Provide {section_name} data in section_data_map",
                ))
        
        # 3. 收集所有 citation_keys 并检查是否在 ReferenceDB 中
        all_cited_keys: set[str] = set()
        for section_name, data in section_data_map.items():
            all_cited_keys.update(self._extract_citation_keys(data))
        
        if all_cited_keys:
            all_exist, missing = ref_db.validate_keys_exist(list(all_cited_keys))
            if not all_exist:
                diagnostics.append(Diagnostic(
                    severity=DiagnosticSeverity.ERROR,
                    location="references",
                    message=f"Missing BibTeX entries for keys: {', '.join(missing)}",
                    fix_suggestion="Add these entries to ReferenceDB",
                ))
        
        # 4. 检查 paper_spec 基本字段
        for field in ["title", "venue", "field"]:
            if not paper_spec.get(field):
                diagnostics.append(Diagnostic(
                    severity=DiagnosticSeverity.ERROR,
                    location=f"paperspec.{field}",
                    message=f"PaperSpec.{field} is required but empty",
                ))
        
        # 判定结果
        has_errors = any(d.severity == DiagnosticSeverity.ERROR for d in diagnostics)
        has_warnings = any(d.severity == DiagnosticSeverity.WARNING for d in diagnostics)
        
        if has_errors:
            status = "FAIL"
        elif has_warnings:
            status = "WARN"
        else:
            status = "PASS"
        
        return GateReport(
            gate_name=self.gate_name,
            status=status,
            diagnostics=diagnostics,
        )
    
    def _check_template(self, template: ResolvedTemplate) -> tuple[bool, list[str]]:
        errors = []
        if not template.document_class:
            errors.append("document_class is empty")
        if not template.section_order:
            errors.append("section_order is empty")
        if template.page_limit <= 0:
            errors.append("page_limit must be positive")
        return len(errors) == 0, errors
    
    def _extract_citation_keys(self, data) -> set[str]:
        """递归提取数据结构中所有的 citation_keys"""
        keys = set()
        if isinstance(data, dict):
            if "citation_keys" in data:
                keys.update(data["citation_keys"])
            for v in data.values():
                keys.update(self._extract_citation_keys(v))
        elif isinstance(data, list):
            for item in data:
                keys.update(self._extract_citation_keys(item))
        return keys


# ============================================================================
# Gate 2: Per-Section —— 逐节编译检查
# ============================================================================

class Gate2PerSection(BaseGate):
    gate_name = "Gate2-PerSection"
    gate_level = 2
    
    def check(
        self,
        latex_block: LaTeXBlock,
        template: ResolvedTemplate,
        work_dir: str,
    ) -> GateReport:
        diagnostics = []
        
        # 1. 检查章节标签
        if f"\\label{{sec:{latex_block.section_name}}}" not in latex_block.content:
            diagnostics.append(Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                location=f"{latex_block.section_name}",
                message=f"Missing \\label{{sec:{latex_block.section_name}}}",
                fix_suggestion=f"Add \\label{{sec:{latex_block.section_name}}}",
            ))
        
        # 2. 单节编译测试（根据 template.engine 选择 pdflatex / xelatex）
        tex_content = self._wrap_in_test_doc(latex_block.content, template)
        compile_result = self._compile_test(tex_content, work_dir, template.engine)
        
        if not compile_result.success:
            for err in compile_result.errors:
                diagnostics.append(Diagnostic(
                    severity=DiagnosticSeverity.ERROR,
                    location=latex_block.section_name,
                    message=f"Compilation error: {err}",
                ))
        
        # 3. 页数预估
        max_pages = template.page_limit * 0.25  # 单节不超过总页数 25%
        if latex_block.estimated_pages > max_pages:
            diagnostics.append(Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                location=latex_block.section_name,
                message=f"Section estimated {latex_block.estimated_pages:.1f} pages "
                        f"(> {max_pages:.1f} threshold)",
                fix_suggestion="Consider reducing content",
            ))
        
        has_errors = any(d.severity == DiagnosticSeverity.ERROR for d in diagnostics)
        
        return GateReport(
            gate_name=self.gate_name,
            status="FAIL" if has_errors else "PASS",
            diagnostics=diagnostics,
        )
    
    def _wrap_in_test_doc(self, section_latex: str, template: ResolvedTemplate) -> str:
        """将单节包装为最小可编译的 LaTeX 文档（中文项目自动注入 xeCJK）"""
        base = f"""\\documentclass[{','.join(template.class_options)}]{{{template.document_class}}}
\\usepackage{{amsmath}}
\\usepackage{{amssymb}}
\\usepackage{{graphicx}}
\\usepackage{{booktabs}}
\\usepackage{{hyperref}}"""
        if template.language == "chinese":
            base += "\n\\usepackage{xeCJK}\n\\setCJKmainfont{SimSun}\n\\IfFontExistsTF{Times New Roman}{\\setmainfont{Times New Roman}}{}"
        base += f"\n\\begin{{document}}\n{section_latex}\n\\end{{document}}"
        return base
    
    def _compile_test(self, tex_content: str, work_dir: str, engine: str = "pdflatex") -> CompileResult:
        """在临时目录编译测试（使用统一的 MikTeXResolver）"""
        os.makedirs(work_dir, exist_ok=True)
        test_file = os.path.join(work_dir, "_gate2_test.tex")

        engine = engine.lower()
        if engine not in ("pdflatex", "xelatex"):
            engine = "pdflatex"

        # 使用 MikTeXResolver 解析路径
        resolver = MikTeXResolver()
        config = resolver.resolve(engine)
        env = resolver.get_env(config)

        try:
            with open(test_file, "w", encoding="utf-8") as f:
                f.write(tex_content)

            result = subprocess.run(
                [config.engine_path, "-interaction=nonstopmode", "-halt-on-error",
                 "-output-directory", work_dir, test_file],
                capture_output=True, text=True, timeout=30,
                env=env,
            )

            success = result.returncode == 0
            errors = []
            if not success:
                for line in result.stdout.split("\n"):
                    if line.startswith("!"):
                        errors.append(line.strip())

            return CompileResult(
                success=success,
                log=result.stdout[-2000:] if not success else "",
                errors=errors,
                engine=engine,
            )
        except FileNotFoundError:
            return CompileResult(
                success=False,
                errors=[f"{engine} 未找到，请检查 MiKTeX 安装"],
                engine=engine,
            )
        except subprocess.TimeoutExpired:
            return CompileResult(
                success=False,
                errors=[f"编译超时 (30秒)，使用引擎: {engine}"],
                engine=engine,
            )


# ============================================================================
# Gate 3: Full-Build —— 全文编译检查
# ============================================================================

class Gate3FullBuild(BaseGate):
    gate_name = "Gate3-FullBuild"
    gate_level = 3
    
    def check(
        self,
        tex_path: str,
        work_dir: str,
        ref_db: ReferenceDB,
        template: ResolvedTemplate,
    ) -> GateReport:
        diagnostics = []
        
        tex_content = self._read_tex(tex_path)
        if tex_content is None:
            return GateReport(
                gate_name=self.gate_name,
                status="FAIL",
                diagnostics=[Diagnostic(
                    severity=DiagnosticSeverity.ERROR,
                    location=tex_path,
                    message="Cannot read .tex file",
                )],
            )
        
        # 1. 检查所有 \cite 中的 key 是否在 ReferenceDB 中
        cited_keys = set(re.findall(r"\\cite\{([^}]+)\}", tex_content))
        # 处理多引用 \cite{key1,key2}
        all_keys = set()
        for ck in cited_keys:
            for k in ck.split(","):
                all_keys.add(k.strip())
        
        all_exist, missing = ref_db.validate_keys_exist(list(all_keys))
        if not all_exist:
            diagnostics.append(Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                location="citations",
                message=f"Undefined citation keys: {', '.join(missing)}",
                fix_suggestion="Add these entries to ReferenceDB or fix citation keys",
            ))
        
        # 2. 检查 \ref 中的 label 是否存在
        refs = set(re.findall(r"\\(?:ref|eqref|cref|autoref)\{([^}]+)\}", tex_content))
        labels = set(re.findall(r"\\label\{([^}]+)\}", tex_content))
        undefined_refs = refs - labels
        if undefined_refs:
            diagnostics.append(Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                location="cross-references",
                message=f"Undefined labels: {', '.join(sorted(undefined_refs))}",
                fix_suggestion="Add missing \\label commands or fix ref names",
            ))
        
        # 3. LaTeX 内容质量检查：错误转义模式
        textbackslash_count = tex_content.count(r"\textbackslash{}")
        if textbackslash_count > 0:
            diagnostics.append(Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                location="escaping",
                message=f"Found {textbackslash_count} instances of \\textbackslash{{}} in content. This indicates incorrect backslash escaping.",
                fix_suggestion="Remove backslash from escape mapping or fix the text processing pipeline.",
            ))
        
        # 4. 检查命令参数中的转义花括号（如 \cite\{\{ref1\}\}）
        escaped_brace_in_command = re.findall(r"\\(cite|ref|textsuperscript|textbf|textit)\{\{", tex_content)
        if escaped_brace_in_command:
            diagnostics.append(Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                location="escaping",
                message=f"Found escaped braces in command arguments: {', '.join(set(escaped_brace_in_command))}. This will cause compilation errors.",
                fix_suggestion="Fix the text processing order: process commands after escaping, not before.",
            ))
        
        # 5. 检查图表文件是否存在
        figure_paths = re.findall(r"\\includegraphics(?:\[.*?\])?\{([^}]+)\}", tex_content)
        for fp in figure_paths:
            # 跳过带扩展名的路径检查
            if "." in os.path.basename(fp):
                full_path = os.path.join(os.path.dirname(tex_path), fp)
                if not os.path.exists(full_path):
                    diagnostics.append(Diagnostic(
                        severity=DiagnosticSeverity.WARNING,
                        location=f"figure:{fp}",
                        message=f"Figure file not found: {fp}",
                    ))
        
        # 6. 全文编译（根据 template.engine 选择
        compile_result = self._full_compile(tex_path, work_dir, template.engine)
        
        if not compile_result.success:
            for err in compile_result.errors:
                diagnostics.append(Diagnostic(
                    severity=DiagnosticSeverity.ERROR,
                    location=tex_path,
                    message=f"Full compile error: {err}",
                ))
        
        # 7. Overfull hbox 检查
        for warn in compile_result.warnings:
            if "Overfull" in warn:
                diagnostics.append(Diagnostic(
                    severity=DiagnosticSeverity.WARNING,
                    location=tex_path,
                    message=warn.strip(),
                    fix_suggestion="Consider rewording or adding line breaks",
                ))
        
        has_errors = any(d.severity == DiagnosticSeverity.ERROR for d in diagnostics)
        has_warnings = any(d.severity == DiagnosticSeverity.WARNING for d in diagnostics)
        
        if has_errors:
            status = "FAIL"
        elif has_warnings:
            status = "WARN"
        else:
            status = "PASS"
        
        return GateReport(
            gate_name=self.gate_name,
            status=status,
            diagnostics=diagnostics,
        )
    
    def _read_tex(self, path: str) -> Optional[str]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return None
    
    def _full_compile(self, tex_path: str, work_dir: str, engine: str = "pdflatex") -> CompileResult:
        """engine → bibtex → engine ×2（使用统一的 MikTeXResolver）"""
        engine = engine.lower()
        if engine not in ("pdflatex", "xelatex"):
            engine = "pdflatex"

        base = os.path.splitext(os.path.basename(tex_path))[0]
        errors = []
        warnings = []

        # 使用 MikTeXResolver 解析路径
        resolver = MikTeXResolver()
        config = resolver.resolve(engine)
        env = resolver.get_env(config)

        # 设置 BSTINPUTS，让 BibTeX 能找到自定义 .bst 文件
        skill_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        bibstyle_dir = os.path.join(skill_root, "templates", "bibstyle")
        bst_env = resolver.get_bst_inputs_env(bibstyle_dir)
        env.update(bst_env)

        try:
            # Pass 1
            r1 = subprocess.run(
                [config.engine_path, "-interaction=nonstopmode",
                 "-output-directory", work_dir, tex_path],
                capture_output=True, text=True, timeout=60,
                env=env,
            )
            if r1.returncode != 0:
                for line in r1.stdout.split("\n"):
                    if line.startswith("!"):
                        errors.append(line.strip())
                # 也检查 stderr 中的致命错误（如 MiKTeX 崩溃）
                if r1.stderr:
                    for line in r1.stderr.split("\n"):
                        line = line.strip()
                        if line and not line.startswith("Sorry"):
                            errors.append(line)
                # 如果 returncode != 0 但没有收集到错误，添加一个通用错误
                if not errors:
                    errors.append(f"Compilation failed with exit code {r1.returncode}")
                return CompileResult(success=False, errors=errors, engine=engine)

            # BibTeX
            bib_file = os.path.join(work_dir, f"{base}.aux")
            if os.path.exists(bib_file):
                subprocess.run(
                    [config.bibtex_path, os.path.splitext(os.path.basename(bib_file))[0]],
                    capture_output=True, text=True, timeout=30,
                    cwd=work_dir,
                    env=env,
                )

            # Pass 2 & 3
            for _ in range(2):
                r = subprocess.run(
                    [config.engine_path, "-interaction=nonstopmode",
                     "-output-directory", work_dir, tex_path],
                    capture_output=True, text=True, timeout=60,
                    env=env,
                )
                if r.returncode != 0:
                    for line in r.stdout.split("\n"):
                        if line.startswith("!"):
                            errors.append(line.strip())
            
            # Extract warnings
            for line in r1.stdout.split("\n"):
                if "Warning" in line:
                    warnings.append(line.strip())
            
            pdf_path = os.path.join(work_dir, f"{base}.pdf")
            success = len(errors) == 0 and os.path.exists(pdf_path)
            
            return CompileResult(
                success=success,
                pdf_path=pdf_path if success else None,
                errors=errors,
                warnings=warnings,
                engine=engine,
            )
        except FileNotFoundError:
            return CompileResult(
                success=False,
                errors=[f"{engine} 或 bibtex 未找到，请检查 MiKTeX 安装"],
                engine=engine,
            )
        except subprocess.TimeoutExpired:
            return CompileResult(
                success=False,
                errors=[f"编译超时，使用引擎: {engine}"],
                engine=engine,
            )


# ============================================================================
# Gate 4: Final-Audit —— 终审检查
# ============================================================================

class Gate4FinalAudit(BaseGate):
    gate_name = "Gate4-FinalAudit"
    gate_level = 4
    
    def check(
        self,
        pdf_path: str,
        tex_path: str,
        template: ResolvedTemplate,
    ) -> GateReport:
        diagnostics = []
        
        tex_content = self._read_tex(tex_path)
        if tex_content is None:
            return GateReport(
                gate_name=self.gate_name,
                status="FAIL",
                diagnostics=[Diagnostic(
                    severity=DiagnosticSeverity.ERROR,
                    location=tex_path,
                    message="Cannot read .tex file",
                )],
            )
        
        # 1. 页数检查（从 .log 文件推断，或使用简单启发式）
        estimated_pages = len(tex_content) / (
            1500 if template.column_layout == "double" else 3000
        )
        if estimated_pages > template.page_limit * 1.05:  # 5% 容忍
            diagnostics.append(Diagnostic(
                severity=DiagnosticSeverity.ERROR,
                location="page_limit",
                message=f"Estimated {estimated_pages:.0f} pages exceeds "
                        f"limit of {template.page_limit}",
                fix_suggestion="Reduce content or move to appendix",
            ))
        elif estimated_pages > template.page_limit:
            diagnostics.append(Diagnostic(
                severity=DiagnosticSeverity.WARNING,
                location="page_limit",
                message=f"Estimated pages ({estimated_pages:.0f}) close to limit ({template.page_limit})",
            ))
        
        # 2. 匿名性检查（如果需要）
        if template.anonymous:
            anon_issues = self._check_anonymity(tex_content)
            diagnostics.extend(anon_issues)
        
        # 3. 图表引用完整性（排除附录部分，附录中的图表不需要被正文引用）
        appendix_pos = self._find_appendix_position(tex_content)
        main_content = tex_content[:appendix_pos] if appendix_pos else tex_content
        
        figure_labels = set(re.findall(r"\\label\{fig:([^}]+)\}", main_content))
        figure_refs = set(re.findall(r"\\ref\{fig:([^}]+)\}", main_content))
        unreferenced_figs = figure_labels - figure_refs
        if unreferenced_figs:
            diagnostics.append(Diagnostic(
                severity=DiagnosticSeverity.INFO,
                location="figures",
                message=f"Unreferenced figures: {', '.join(sorted(unreferenced_figs))}",
            ))
        
        table_labels = set(re.findall(r"\\label\{tab:([^}]+)\}", main_content))
        table_refs = set(re.findall(r"\\ref\{tab:([^}]+)\}", main_content))
        unreferenced_tbls = table_labels - table_refs
        if unreferenced_tbls:
            diagnostics.append(Diagnostic(
                severity=DiagnosticSeverity.INFO,
                location="tables",
                message=f"Unreferenced tables: {', '.join(sorted(unreferenced_tbls))}",
            ))
        
        has_errors = any(d.severity == DiagnosticSeverity.ERROR for d in diagnostics)
        has_warnings = any(d.severity == DiagnosticSeverity.WARNING for d in diagnostics)
        
        if has_errors:
            status = "FAIL"
        elif has_warnings:
            status = "WARN"
        else:
            status = "PASS"
        
        return GateReport(
            gate_name=self.gate_name,
            status=status,
            diagnostics=diagnostics,
        )
    
    def _read_tex(self, path: str) -> Optional[str]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            return None
    
    def _find_appendix_position(self, tex_content: str) -> Optional[int]:
        r"""查找附录部分的起始位置（如果有）。
        
        匹配以下模式：
        - \chapter*{附录...}
        - \section*{附录...}
        - \appendix
        - 中文"附录"开头的标题
        """
        patterns = [
            r"\\chapter\*\{[^\}]*附\s*录",
            r"\\section\*\{[^\}]*附\s*录",
            r"\\chapter\{[^\}]*附\s*录",
            r"\\section\{[^\}]*附\s*录",
            r"\\appendix",
            r"\\chapter\*\{Appendix",
            r"\\section\*\{Appendix",
        ]
        earliest_pos = None
        for pattern in patterns:
            m = re.search(pattern, tex_content, re.IGNORECASE)
            if m:
                if earliest_pos is None or m.start() < earliest_pos:
                    earliest_pos = m.start()
        return earliest_pos
    
    def _check_anonymity(self, tex_content: str) -> list[Diagnostic]:
        """检查匿名性：不应包含作者信息、机构名称、致谢等"""
        issues = []
        
        # 简单检查：是否有常见的非匿名模式
        suspicious = [
            (r"\\author\{", "Author information found (anonymous mode)"),
            (r"\\thanks\{", "Acknowledgement found (anonymous mode)"),
        ]
        
        for pattern, msg in suspicious:
            if re.search(pattern, tex_content):
                issues.append(Diagnostic(
                    severity=DiagnosticSeverity.ERROR,
                    location="anonymity",
                    message=msg,
                    fix_suggestion=f"Remove or anonymize the {pattern} content",
                ))
        
        return issues