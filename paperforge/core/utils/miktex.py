# -*- coding: utf-8 -*-
r"""
MiKTeX 路径检测与解析工具。

提供统一的 MiKTeX 安装路径检测逻辑，消除代码重复。
支持 Windows 和 Unix-like 系统。
"""

import os
import shutil
from dataclasses import dataclass
from typing import Optional


@dataclass
class MikTeXConfig:
    """MiKTeX 配置信息"""
    miktex_path: Optional[str]  # MiKTeX bin 目录路径
    engine_path: str           # 具体引擎的完整路径
    bibtex_path: str            # bibtex 完整路径
    found_in_path: bool         # 是否在系统 PATH 中找到

    @property
    def is_found(self) -> bool:
        """是否找到 MiKTeX"""
        return self.found_in_path or os.path.exists(self.engine_path)


class MikTeXResolver:
    """
    MiKTeX 路径解析器。

    自动检测 MiKTeX 安装位置，支持多种安装路径和配置方式。
    """

    # 常见的 MiKTeX 安装路径（按优先级排序）
    # 最高优先级: MIKTEX_BIN 环境变量，由 paper_pipeline config/settings.py 注入
    WINDOWS_CANDIDATES = [
        os.environ.get("MIKTEX_BIN", ""),
        r"C:\Program Files\MiKTeX\miktex\bin\x64",
        r"C:\Program Files (x86)\MiKTeX\miktex\bin\x64",
        r"C:\MiKTeX\miktex\bin\x64",
        r"%LOCALAPPDATA%\Programs\MiKTeX\miktex\bin\x64",
    ]

    UNIX_CANDIDATES = [
        "/usr/bin",
        "/usr/local/bin",
        "/opt/miktex/bin",
        "~/.miktex/bin",
    ]

    def __init__(self, custom_path: Optional[str] = None):
        """
        初始化解析器。

        Args:
            custom_path: 用户指定的 MiKTeX 路径，如果提供则优先使用
        """
        self.custom_path = custom_path

    def resolve(self, engine: str = "xelatex") -> MikTeXConfig:
        """
        解析 MiKTeX 配置。

        Args:
            engine: LaTeX 引擎名称（xelatex, pdflatex 等）

        Returns:
            MikTeXConfig: 包含路径信息的配置对象
        """
        exe_name = f"{engine}.exe" if os.name == "nt" else engine

        # 1. 检查是否在系统 PATH 中
        if shutil.which(engine):
            return MikTeXConfig(
                miktex_path=None,
                engine_path=shutil.which(engine),
                bibtex_path=self._get_bibtex_path(None),
                found_in_path=True,
            )

        # 2. 使用用户自定义路径
        if self.custom_path:
            engine_path = os.path.join(self.custom_path, exe_name)
            if os.path.exists(engine_path):
                return MikTeXConfig(
                    miktex_path=self.custom_path,
                    engine_path=engine_path,
                    bibtex_path=self._get_bibtex_path(self.custom_path),
                    found_in_path=False,
                )

        # 3. 自动搜索常见安装位置
        candidates = self.WINDOWS_CANDIDATES if os.name == "nt" else self.UNIX_CANDIDATES

        # 展开环境变量路径，过滤空字符串（MIKTEX_BIN 未设置时）
        expanded_candidates = []
        for path in candidates:
            expanded = os.path.expandvars(path).strip()
            if expanded:
                expanded_candidates.append(expanded)

        for base_path in expanded_candidates:
            engine_path = os.path.join(base_path, exe_name)
            if os.path.exists(engine_path):
                # 检查 pdflatex 是否也在同一目录（用于确认这是 MiKTeX 目录）
                pdflatex_path = os.path.join(base_path, "pdflatex.exe" if os.name == "nt" else "pdflatex")
                if os.path.exists(pdflatex_path) or engine == "pdflatex":
                    return MikTeXConfig(
                        miktex_path=base_path,
                        engine_path=engine_path,
                        bibtex_path=self._get_bibtex_path(base_path),
                        found_in_path=False,
                    )

        # 4. 回退：只找到指定引擎但没找到 pdflatex 的情况
        for base_path in expanded_candidates:
            engine_path = os.path.join(base_path, exe_name)
            if os.path.exists(engine_path):
                return MikTeXConfig(
                    miktex_path=base_path,
                    engine_path=engine_path,
                    bibtex_path=self._get_bibtex_path(base_path),
                    found_in_path=False,
                )

        # 5. 完全找不到，返回未找到状态
        return MikTeXConfig(
            miktex_path=None,
            engine_path=exe_name,  # 回退到只用命令名
            bibtex_path="bibtex",
            found_in_path=False,
        )

    def _get_bibtex_path(self, base_path: Optional[str]) -> str:
        """获取 bibtex 可执行文件路径"""
        bibtex_name = "bibtex.exe" if os.name == "nt" else "bibtex"
        if base_path:
            return os.path.join(base_path, bibtex_name)
        return bibtex_name

    def get_env(self, config: MikTeXConfig) -> dict:
        """
        获取包含 MiKTeX 路径的环境变量。

        Args:
            config: MikTeXConfig 配置对象

        Returns:
            dict: 包含 PATH 的环境变量字典
        """
        import copy
        env = copy.deepcopy(os.environ)

        # 清理 PATH：移除不是有效目录的条目（如错误添加的文件路径）
        path_env = env.get("PATH", "")
        if path_env:
            separator = ";" if os.name == "nt" else ":"
            path_entries = path_env.split(separator)
            valid_entries = []
            for entry in path_entries:
                entry = entry.strip()
                if entry and os.path.isdir(entry):
                    valid_entries.append(entry)
            env["PATH"] = separator.join(valid_entries)

        if config.miktex_path and config.miktex_path not in env.get("PATH", ""):
            separator = ";" if os.name == "nt" else ":"
            env["PATH"] = config.miktex_path + separator + env.get("PATH", "")

        return env

    def get_bst_inputs_env(self, bibstyle_dir: Optional[str] = None) -> dict:
        """
        获取 BibTeX 样式文件搜索路径的环境变量。

        Args:
            bibstyle_dir: 自定义 BibTeX 样式目录

        Returns:
            dict: 包含 BSTINPUTS 和 BIBINPUTS 的环境变量
        """
        env = {}
        if bibstyle_dir and os.path.isdir(bibstyle_dir):
            existing_bst = os.environ.get("BSTINPUTS", "")
            existing_bib = os.environ.get("BIBINPUTS", "")
            separator = ";" if os.name == "nt" else ":"
            env["BSTINPUTS"] = bibstyle_dir + (separator + existing_bst if existing_bst else "")
            env["BIBINPUTS"] = bibstyle_dir + (separator + existing_bib if existing_bib else "")
        return env


def find_miktex_path(engine: str = "xelatex") -> Optional[str]:
    """
    快速查找 MiKTeX 路径（兼容旧 API）。

    Args:
        engine: LaTeX 引擎名称

    Returns:
        str 或 None: MiKTeX bin 目录路径，如果已在 PATH 中则返回 None
    """
    resolver = MikTeXResolver()
    config = resolver.resolve(engine)
    return config.miktex_path
