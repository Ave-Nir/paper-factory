"""
test_settings.py — settings.py 测试套件

Covers the path resolution logic added in P0-C-1 (replace hardcoded absolute
paths with parameter > env > relative-path resolution).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from paper_pipeline.config.settings import (
    ApiConfig,
    PathConfig,
    Settings,
    TEMPLATE_STANDARDS,
    get_settings,
)
from paper_pipeline.exceptions import ConfigurationError


class TestTemplateStandards:
    """10 个模板的排版标准必须全部定义完整。"""

    def test_all_templates_present(self):
        required = {"renai", "thesis", "humanities", "nsfc", "sci", "ieee",
                    "icml2025", "cvpr2024", "neurips2024", "acl2024"}
        assert required.issubset(TEMPLATE_STANDARDS.keys())

    @pytest.mark.parametrize("template", list(TEMPLATE_STANDARDS.keys()))
    def test_template_has_required_fields(self, template):
        std = TEMPLATE_STANDARDS[template]
        for key in ("body_font_pt", "heading2_font_pt",
                    "margin_top_mm", "margin_bottom_mm",
                    "margin_left_mm", "margin_right_mm", "line_spacing"):
            assert key in std, f"Template {template} missing {key}"
            assert std[key] > 0

    def test_chinese_templates_use_larger_font(self):
        """中文学位论文/期刊应使用 12pt 字号；英文会议用 10-11pt。"""
        for tmpl in ("renai", "thesis", "humanities", "nsfc", "sci"):
            assert TEMPLATE_STANDARDS[tmpl]["body_font_pt"] == 12.0
        for tmpl in ("ieee", "icml2025", "cvpr2024", "neurips2024"):
            assert TEMPLATE_STANDARDS[tmpl]["body_font_pt"] == 10.0


class TestGetSettingsApi:
    """get_settings() 必须强制从环境变量读取 API key (fail-closed)."""

    def test_missing_llm_key_raises(self, monkeypatch):
        monkeypatch.setenv("IMAGE_API_KEY", "sk-test-image")
        with pytest.raises(ConfigurationError) as exc_info:
            get_settings()
        assert "LLM_API_KEY" in str(exc_info.value)

    def test_missing_image_key_raises(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-test-llm")
        with pytest.raises(ConfigurationError) as exc_info:
            get_settings()
        assert "IMAGE_API_KEY" in str(exc_info.value)

    def test_valid_env_produces_settings(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "sk-test-llm")
        monkeypatch.setenv("IMAGE_API_KEY", "sk-test-image")
        s = get_settings()
        assert s.api.llm_api_key == "sk-test-llm"
        assert s.api.image_api_key == "sk-test-image"

    def test_env_overrides_take_effect(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "k")
        monkeypatch.setenv("IMAGE_API_KEY", "k")
        monkeypatch.setenv("LLM_MODEL", "test-model")
        monkeypatch.setenv("IMAGE_MODEL", "test-img")
        s = get_settings()
        assert s.api.llm_model == "test-model"
        assert s.api.image_model == "test-img"


class TestGetSettingsPaths:
    """路径解析：参数 > 环境变量 > 相对项目根."""

    def test_explicit_work_dir_takes_priority(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "k")
        monkeypatch.setenv("IMAGE_API_KEY", "k")
        s = get_settings(work_dir=tmp_path)
        assert s.paths.work_dir == tmp_path

    def test_env_var_used_when_no_work_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "k")
        monkeypatch.setenv("IMAGE_API_KEY", "k")
        monkeypatch.setenv("PAPER_PIPELINE_HOME", str(tmp_path))
        s = get_settings()
        assert s.paths.work_dir == tmp_path

    def test_relative_fallback_is_under_project_root(self, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "k")
        monkeypatch.setenv("IMAGE_API_KEY", "k")
        # clear any user override
        monkeypatch.delenv("PAPER_PIPELINE_HOME", raising=False)
        s = get_settings()
        # 项目根由 settings.py 位置推导：
        #   paper_pipeline/src/paper_pipeline/config/settings.py
        # 因此默认 work_dir 为 <仓库根>/paper_pipeline
        assert s.paths.work_dir.name == "paper_pipeline"
        # 关键反测：默认路径不得包含硬编码盘符
        assert "G:" not in str(s.paths.work_dir)
        assert "g:" not in str(s.paths.work_dir)

    def test_paper2diagram_env_overrides(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "k")
        monkeypatch.setenv("IMAGE_API_KEY", "k")
        monkeypatch.setenv("PAPER2DIAGRAM_HOME", str(tmp_path))
        s = get_settings()
        assert s.paths.paper2diagram_dir == tmp_path

    def test_paperforge_env_overrides(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "k")
        monkeypatch.setenv("IMAGE_API_KEY", "k")
        monkeypatch.setenv("PAPERFORGE_HOME", str(tmp_path))
        s = get_settings()
        assert s.paths.paperforge_dir == tmp_path

    def test_miktex_env_overrides(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LLM_API_KEY", "k")
        monkeypatch.setenv("IMAGE_API_KEY", "k")
        monkeypatch.setenv("MIKTEX_BIN", str(tmp_path))
        s = get_settings()
        assert s.paths.miktex_bin == tmp_path

    def test_default_paths_stay_inside_repo(self, monkeypatch):
        """核心反测：默认路径必须由项目根相对推导，不得硬编码外部绝对路径。"""
        monkeypatch.setenv("LLM_API_KEY", "k")
        monkeypatch.setenv("IMAGE_API_KEY", "k")
        monkeypatch.delenv("PAPER_PIPELINE_HOME", raising=False)
        monkeypatch.delenv("PAPER2DIAGRAM_HOME", raising=False)
        monkeypatch.delenv("PAPERFORGE_HOME", raising=False)
        monkeypatch.delenv("MIKTEX_BIN", raising=False)
        s = get_settings()

        # tests/ → paper_pipeline/ → paper-factory/
        repo_root = Path(__file__).resolve().parents[2]
        for p in (s.paths.work_dir, s.paths.paper2diagram_dir,
                  s.paths.paperforge_dir, s.paths.miktex_bin):
            resolved = Path(p).resolve()
            assert resolved.is_relative_to(repo_root), \
                f"Default path escaped repo root (hardcoded absolute path?): {resolved}"
