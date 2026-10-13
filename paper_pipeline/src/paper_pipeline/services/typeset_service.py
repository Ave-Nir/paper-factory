"""
排版服务 —— 封装 PaperForge，类型安全接口

设计原则：
- 所有格式 (.docx/.md/.tex) 统一通过 PaperForge 的 process_lunwen_v4.py 排版
- PaperForge 负责模板选择、内容解析、LaTeX 重新生成和 PDF 编译
- 类型安全：明确输入/输出类型
- 异常处理：所有子进程异常捕获并包装
- 环境隔离：确保 MiKTeX 在 PATH 中，密钥通过环境变量传递
- 支持增量重编译（方向2）：避免每次都全量解析
"""
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from ..config.settings import Settings
from ..exceptions import TypesetError, ConfigurationError


class TypesetResult:
    """排版结果 —— 禁止裸 dict 透传"""

    def __init__(
        self,
        pdf_path: Path,
        tex_path: Path,
        pages: int,
        success: bool,
        errors: list[str],
        warnings: list[str],
        elapsed_sec: float = 0.0,
        incremental: bool = False,
    ) -> None:
        self.pdf_path = pdf_path
        self.tex_path = tex_path
        self.pages = pages
        self.success = success
        self.errors = errors
        self.warnings = warnings
        self.elapsed_sec = elapsed_sec
        self.incremental = incremental


class IncrementalCompiler:
    """
    增量重编译器 —— 方向2核心组件

    工作原理：
    1. 首次编译：完整流程（解析docx→生成tex→xelatex）
    2. 增量编译：仅当 .tex 被修改时，调用 xelatex 重编译
    3. 缓存：保留 .aux / .toc 等中间文件，仅当 .tex 修改时删除
    """

    def __init__(self, build_dir: Path) -> None:
        self.build_dir = build_dir
        self._tex_path: Optional[Path] = None
        self._last_tex_mtime: float = 0.0
        self._last_compile_time: float = 0.0
        self._is_first_compile: bool = True

    def should_recompile(self, tex_path: Path) -> bool:
        """
        判断是否需要重新编译。

        规则：
        - 首次编译：True
        - tex 文件修改时间 > 上次编译时间：True
        - 否则：False（增量模式）
        """
        if not tex_path.exists():
            return True
        if self._is_first_compile:
            return True

        current_mtime = tex_path.stat().st_mtime
        if current_mtime > self._last_tex_mtime:
            return True
        return False

    def cleanup_intermediate(self, tex_path: Path) -> None:
        """
        清理 LaTeX 中间文件（.aux, .toc, .out 等），强制重新生成。
        """
        for ext in [".aux", ".toc", ".out", ".lof", ".lot", ".bbl", ".blg", ".log"]:
            aux_file = tex_path.with_suffix(ext)
            if aux_file.exists():
                aux_file.unlink()

    def mark_compiled(self, tex_path: Path) -> None:
        """记录编译完成状态"""
        self._is_first_compile = False
        if tex_path.exists():
            self._last_tex_mtime = tex_path.stat().st_mtime
        self._last_compile_time = time.time()


class TypesetService:
    """
    排版服务 —— 对 PaperForge process_lunwen_v4.py 的类型安全封装

    对外接口类型：
      - 输入: Path (修改后的论文路径，.docx / .md / .tex)
      - 输出: TypesetResult
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._paperforge_dir = settings.paths.paperforge_dir
        self._script_path = self._paperforge_dir / "config" / "process_lunwen_v4.py"

        if not self._script_path.exists():
            raise ConfigurationError(
                message=f"PaperForge 脚本不存在: {self._script_path}",
                stage="INIT",
                context={"script_path": str(self._script_path)},
            )

    def typeset(
        self,
        paper_path: Path,
        output_dir: Path,
        incremental: bool = True,
    ) -> TypesetResult:
        """
        调用 PaperForge 排版生成 PDF

        :param paper_path: 修改后的论文路径（.docx / .md / .tex，含插入的图片）
        :param output_dir: 输出目录
        :param incremental: 是否启用增量编译（方向2）
        :return: TypesetResult
        :raises TypesetError: 排版失败
        """
        if not paper_path.exists():
            raise TypesetError(
                message=f"输入论文不存在: {paper_path}",
                stage="TYPESET",
                context={"paper_path": str(paper_path)},
            )

        output_dir.mkdir(parents=True, exist_ok=True)

        # 构建子进程环境
        env = os.environ.copy()
        env["LLM_API_KEY"] = self.settings.api.llm_api_key
        # V7.7: Windows 控制台默认 GBK，process_lunwen_v4 打印 '•' 等字符会
        # UnicodeEncodeError 崩溃 —— 强制子进程 UTF-8 输出
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        miktex_str = str(self.settings.paths.miktex_bin).replace("/", "\\")
        env["PATH"] = miktex_str + ";" + env.get("PATH", "")

        cmd = [
            sys.executable,
            str(self._script_path),
            str(paper_path),
            "-o", str(output_dir),
            "-t", self.settings.typeset.template,
            "--miktex", str(self.settings.paths.miktex_bin).replace("\\", "/"),
        ]
        # V6.7: Word 生成由 generate_word 控制（默认关闭）
        if not self.settings.typeset.generate_word:
            cmd.append("--no-word")

        start_time = time.time()

        try:
            result = subprocess.run(
                cmd,
                cwd=str(self._paperforge_dir),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.settings.typeset.xelatex_timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise TypesetError(
                message=f"排版超时（>{self.settings.typeset.xelatex_timeout}秒）",
                stage="TYPESET",
                context={"paper_path": str(paper_path)},
                cause=e,
            )
        except Exception as e:
            raise TypesetError(
                message="排版子进程异常",
                stage="TYPESET",
                context={"paper_path": str(paper_path)},
                cause=e,
            )

        elapsed = time.time() - start_time

        # 解析输出
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        errors, warnings = self._parse_output(stdout, stderr)

        # 检查 PDF
        pdf_path = output_dir / "paper.pdf"
        tex_path = output_dir / "paper.tex"
        success = pdf_path.exists() and pdf_path.stat().st_size > 1024

        pages = 0
        if success:
            pages = self._extract_page_count(stdout)

        return TypesetResult(
            pdf_path=pdf_path,
            tex_path=tex_path,
            pages=pages,
            success=success,
            errors=errors,
            warnings=warnings,
            elapsed_sec=elapsed,
            incremental=incremental,
        )

    def recompile_tex(
        self,
        tex_path: Path,
        output_dir: Path,
    ) -> TypesetResult:
        """
        增量重编译 —— 方向2优化

        直接调用 xelatex 编译已存在的 .tex 文件，跳过 docx 解析阶段。
        适用于 Gate5 自动修复后的快速重编译。

        :param tex_path: 已修改的 .tex 文件路径
        :param output_dir: 输出目录
        :return: TypesetResult
        """
        if not tex_path.exists():
            raise TypesetError(
                message=f"tex 文件不存在: {tex_path}",
                stage="TYPESET",
                context={"tex_path": str(tex_path)},
            )

        # 构建子进程环境
        env = os.environ.copy()
        env["LLM_API_KEY"] = self.settings.api.llm_api_key
        # V7.7: Windows 控制台默认 GBK，process_lunwen_v4 打印 '•' 等字符会
        # UnicodeEncodeError 崩溃 —— 强制子进程 UTF-8 输出
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        miktex_str = str(self.settings.paths.miktex_bin).replace("/", "\\")
        env["PATH"] = miktex_str + ";" + env.get("PATH", "")

        start_time = time.time()

        # xelatex 命令：仅编译 tex，跳过 docx 解析
        cmd = [
            "xelatex",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-output-directory", str(output_dir),
            str(tex_path.name),
        ]

        try:
            result = subprocess.run(
                cmd,
                cwd=str(output_dir),
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.settings.typeset.xelatex_timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise TypesetError(
                message=f"增量编译超时（>{self.settings.typeset.xelatex_timeout}秒）",
                stage="TYPESET",
                context={"tex_path": str(tex_path)},
                cause=e,
            )
        except Exception as e:
            raise TypesetError(
                message="增量编译异常",
                stage="TYPESET",
                context={"tex_path": str(tex_path)},
                cause=e,
            )

        elapsed = time.time() - start_time

        # 检查 PDF
        pdf_path = output_dir / tex_path.with_suffix(".pdf").name
        success = pdf_path.exists() and pdf_path.stat().st_size > 1024

        # 从 PDF 提取页数
        pages = 0
        if success:
            try:
                import fitz
                doc = fitz.open(str(pdf_path))
                pages = doc.page_count
                doc.close()
            except Exception:
                pass

        return TypesetResult(
            pdf_path=pdf_path,
            tex_path=tex_path,
            pages=pages,
            success=success,
            errors=[],
            warnings=[],
            elapsed_sec=elapsed,
            incremental=True,
        )

    @staticmethod
    def _parse_output(stdout: str, stderr: str = "") -> tuple[list[str], list[str]]:
        """解析 PaperForge 输出，提取错误和警告。
        
        V6.6: 同时解析 stdout 和 stderr。当 stdout 无错误时，
        将 stderr 作为错误信息返回，避免静默失败。
        """
        errors: list[str] = []
        warnings: list[str] = []
        combined = stdout + "\n" + stderr
        for line in combined.split("\n"):
            line = line.strip()
            if "[ERROR]" in line:
                errors.append(line.split("[ERROR]", 1)[1].strip())
            elif "[警告]" in line or "[WARNING]" in line:
                warnings.append(line)
        
        # V6.6: 当无显式错误标记时，将 stderr 作为兜底诊断信息
        if not errors and stderr.strip():
            errors.append(f"[stderr] {stderr.strip()[:500]}")
        
        return errors, warnings

    @staticmethod
    def _extract_page_count(stdout: str) -> int:
        """从输出中提取页数"""
        for line in stdout.split("\n"):
            if "页" in line and "编译" in line:
                parts = line.split(",")
                for p in parts:
                    if "页" in p:
                        nums = [int(s) for s in p.split() if s.isdigit()]
                        if nums:
                            return nums[-1]
        return 0
