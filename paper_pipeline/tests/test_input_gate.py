"""
test_input_gate.py — InputGate (Gate1) 测试

覆盖文件存在性、文件大小、文件扩展名三类检查。
"""
from __future__ import annotations

from pathlib import Path

from paper_pipeline.gates.quality_gates import InputGate


class TestInputGateHappyPath:
    """正常输入 → passed=True, errors=[]."""

    def test_valid_docx_passes(self, supported_docx):
        report = InputGate.check(supported_docx)
        assert report.passed is True
        assert report.errors == []
        assert report.context["path"] == str(supported_docx)

    def test_valid_md_passes(self, tmp_path):
        p = tmp_path / "paper.md"
        p.write_text("# Title\n\nSome content here.\n" * 100, encoding="utf-8")
        report = InputGate.check(p)
        assert report.passed is True

    def test_valid_tex_passes(self, small_tex):
        report = InputGate.check(small_tex)
        assert report.passed is True


class TestInputGateErrors:
    """异常输入 → passed=False, errors 非空."""

    def test_missing_file_fails(self, tmp_path):
        missing = tmp_path / "nope.docx"
        report = InputGate.check(missing)
        assert report.passed is False
        assert any("不存在" in e for e in report.errors)

    def test_empty_file_fails(self, empty_file):
        report = InputGate.check(empty_file)
        assert report.passed is False
        assert any("为空" in e for e in report.errors)

    def test_unsupported_extension_fails(self, unsupported_file):
        report = InputGate.check(unsupported_file)
        assert report.passed is False
        assert any("不支持的文件格式" in e for e in report.errors)


class TestInputGateWarnings:
    """可恢复的输入问题只产生 warnings，passed=True."""

    def test_tiny_file_warns_but_passes(self, tiny_file):
        report = InputGate.check(tiny_file)
        assert report.passed is True
        assert any("过小" in w for w in report.warnings)
