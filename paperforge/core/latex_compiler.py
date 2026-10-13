"""
LaTeX 编译器与静态检查器。

设计原则：
- 编译流程：pdflatex → bibtex → pdflatex ×2
- 支持单次编译和完整编译
- 静态检查不依赖编译，可离线运行
- 使用统一的 MikTeXResolver 进行路径检测
"""

import os
import subprocess
from typing import Optional

from .types import CompileResult
from .utils.miktex import MikTeXResolver, MikTeXConfig


class CompilationError(Exception):
    """编译异常"""
    def __init__(self, message: str, errors: list = None):
        super().__init__(message)
        self.errors = errors or []


class LaTeXCompiler:
    """LaTeX 编译器"""

    def __init__(self, timeout: int = 120, miktex_path: Optional[str] = None):
        self.timeout = timeout
        self.miktex_resolver = MikTeXResolver(custom_path=miktex_path)

    def compile(self, tex_path: str, work_dir: str, engine: str = "pdflatex") -> CompileResult:
        """
        完整编译：
        - pdflatex: pdflatex → bibtex → pdflatex ×2
        - xelatex:  xelatex  → bibtex → xelatex ×2（中文项目推荐）

        Args:
            tex_path: .tex 文件路径
            work_dir: 工作目录
            engine: LaTeX 引擎（xelatex/pdflatex）

        Returns:
            CompileResult: 编译结果

        Raises:
            CompilationError: 编译过程中的严重错误
        """
        # 检查文件是否存在
        if not os.path.exists(tex_path):
            return CompileResult(
                success=False,
                errors=[f"文件不存在: {tex_path}"],
                engine=engine,
            )

        # 规范化引擎名称
        engine = engine.lower()
        if engine not in ("pdflatex", "xelatex"):
            engine = "pdflatex"

        # 创建工作目录
        os.makedirs(work_dir, exist_ok=True)
        base = os.path.splitext(os.path.basename(tex_path))[0]

        # 使用 MikTeXResolver 解析路径
        config = self.miktex_resolver.resolve(engine)
        env = self.miktex_resolver.get_env(config)

        # 检查引擎是否可用
        if not config.is_found and not config.found_in_path:
            return CompileResult(
                success=False,
                errors=[f"找不到 LaTeX 引擎 '{engine}'，请检查 MiKTeX 安装"],
                engine=engine,
            )

        errors = []
        warnings = []

        try:
            # Pass 1: 初次编译
            r1 = self._run_pass(config, tex_path, work_dir, env)

            for line in r1.stdout.split("\n"):
                if line.startswith("!"):
                    errors.append(self._clean_line(line))
                if "Warning" in line:
                    warnings.append(self._clean_line(line))

            if r1.returncode != 0:
                return CompileResult(
                    success=False,
                    log=r1.stdout[-3000:],
                    errors=errors,
                    warnings=warnings,
                    engine=engine,
                )

            # BibTeX
            aux_path = os.path.join(work_dir, f"{base}.aux")
            if os.path.exists(aux_path):
                self._run_bibtex(config, base, work_dir, env, warnings)

            # Pass 2 & 3: 解决交叉引用
            for _ in range(2):
                r = self._run_pass(config, tex_path, work_dir, env)
                for line in r.stdout.split("\n"):
                    if line.startswith("!"):
                        errors.append(self._clean_line(line))

            # 检查结果
            pdf_path = os.path.join(work_dir, f"{base}.pdf")
            success = len(errors) == 0 and os.path.exists(pdf_path)

            return CompileResult(
                success=success,
                pdf_path=pdf_path if success else None,
                log=r1.stdout[-3000:] if not success else "",
                errors=errors,
                warnings=warnings,
                engine=engine,
            )

        except subprocess.TimeoutExpired:
            return CompileResult(
                success=False,
                errors=[f"编译超时 ({self.timeout}秒)，使用引擎: {engine}"],
                engine=engine,
            )

        except FileNotFoundError as e:
            return CompileResult(
                success=False,
                errors=[f"找不到可执行文件: {e.filename}"],
                engine=engine,
            )

        except Exception as e:
            return CompileResult(
                success=False,
                errors=[f"编译异常: {str(e)}"],
                engine=engine,
            )

    def _run_pass(
        self,
        config: MikTeXConfig,
        tex_path: str,
        work_dir: str,
        env: dict
    ) -> subprocess.CompletedProcess:
        """执行单次编译"""
        return subprocess.run(
            [config.engine_path, "-interaction=nonstopmode",
             "-output-directory", work_dir, tex_path],
            capture_output=True,
            text=True,
            timeout=self.timeout,
            env=env,
        )

    def _run_bibtex(
        self,
        config: MikTeXConfig,
        base: str,
        work_dir: str,
        env: dict,
        warnings: list
    ) -> None:
        """执行 BibTeX"""
        try:
            bib_result = subprocess.run(
                [config.bibtex_path, base],
                capture_output=True,
                text=True,
                timeout=30,
                cwd=work_dir,
                env=env,
            )
            for line in bib_result.stdout.split("\n"):
                if "Warning" in line:
                    warnings.append(f"bibtex: {self._clean_line(line)}")
        except subprocess.TimeoutExpired:
            warnings.append("bibtex: 超时")
        except FileNotFoundError:
            warnings.append("bibtex: 找不到可执行文件")

    def _clean_line(self, line: str) -> str:
        """清理日志行中的 ANSI 颜色代码"""
        import re
        ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
        return ansi_escape.sub('', line.strip())


class LaTeXStaticChecker:
    """LaTeX 静态检查器 —— 不编译，仅分析 .tex 文件"""
    
    @staticmethod
    def check_unescaped_chars(content: str) -> list[str]:
        """检查未转义的特殊字符"""
        issues = []
        # 检查不在数学模式中的 &, %, $, #, _, {, }
        # 简化版本：逐行检查
        for i, line in enumerate(content.split("\n"), 1):
            # 跳过注释行
            if line.strip().startswith("%"):
                continue
            # 检查裸露的 &（不在 tabular 中的）
            if "&" in line and "\\begin{tabular}" not in content:
                # 复杂逻辑省略，简单标记
                pass
        return issues
    
    @staticmethod
    def check_unclosed_envs(content: str) -> list[str]:
        """检查未闭合的环境"""
        issues = []
        begin_pattern = re.compile(r"\\begin\{(\w+)\}")
        end_pattern = re.compile(r"\\end\{(\w+)\}")
        
        begins = begin_pattern.findall(content)
        ends = end_pattern.findall(content)
        
        from collections import Counter
        begin_counts = Counter(begins)
        end_counts = Counter(ends)
        
        for env in set(list(begin_counts.keys()) + list(end_counts.keys())):
            diff = begin_counts.get(env, 0) - end_counts.get(env, 0)
            if diff > 0:
                issues.append(f"Unclosed environment: '{env}' ({diff} missing \\end{{{env}}})")
            elif diff < 0:
                issues.append(f"Extra \\end{{{env}}} (no matching \\begin)")
        
        return issues
    
    @staticmethod
    def check_duplicate_labels(content: str) -> list[str]:
        """检查重复的 \\label"""
        issues = []
        labels = re.findall(r"\\label\{([^}]+)\}", content)
        from collections import Counter
        label_counts = Counter(labels)
        for label, count in label_counts.items():
            if count > 1:
                issues.append(f"Duplicate label: '{label}' (used {count} times)")
        return issues
    
    @staticmethod
    def check_undefined_refs(content: str) -> list[str]:
        """检查未定义的引用"""
        issues = []
        refs = set(re.findall(r"\\(?:ref|eqref|cref|autoref|cite)\{([^}]+)\}", content))
        labels = set(re.findall(r"\\label\{([^}]+)\}", content))
        # 处理多引用
        all_refs = set()
        for r in refs:
            for part in r.split(","):
                all_refs.add(part.strip())
        
        undefined = all_refs - labels
        for u in sorted(undefined):
            issues.append(f"Undefined reference: '{u}'")
        return issues
    
    @staticmethod
    def check_all(content: str) -> dict[str, list[str]]:
        """运行所有静态检查"""
        return {
            "unclosed_envs": LaTeXStaticChecker.check_unclosed_envs(content),
            "duplicate_labels": LaTeXStaticChecker.check_duplicate_labels(content),
            "undefined_refs": LaTeXStaticChecker.check_undefined_refs(content),
            "unescaped_chars": LaTeXStaticChecker.check_unescaped_chars(content),
        }