"""
test_typeset_gate.py — TypesetGate (Gate3/Gate4) 测试

验证 PDF/TEX 存在性、PDF 大小、页数检查。
"""
from __future__ import annotations

from pathlib import Path

from paper_pipeline.gates.quality_gates import TypesetGate


class TestTypesetGateHappyPath:
    def test_valid_pdf_and_tex_pass(self, tmp_path):
        pdf = tmp_path / "paper.pdf"
        tex = tmp_path / "paper.tex"
        pdf.write_bytes(b"%PDF-1.4\n" + b"\x00" * 5000)
        tex.write_text(r"\documentclass{article}\begin{document}Hello\end{document}", encoding="utf-8")
        report = TypesetGate.check(pdf, tex, pages=10)
        assert report.passed is True
        assert report.errors == []
        assert report.context["pages"] == 10


class TestTypesetGateErrors:
    def test_missing_pdf_fails(self, tmp_path):
        pdf = tmp_path / "missing.pdf"
        tex = tmp_path / "missing.tex"
        tex.write_text("placeholder", encoding="utf-8")
        report = TypesetGate.check(pdf, tex, pages=5)
        assert report.passed is False
        assert any("PDF 未生成" in e for e in report.errors)

    def test_tiny_pdf_fails(self, tmp_path):
        pdf = tmp_path / "tiny.pdf"
        tex = tmp_path / "tiny.tex"
        pdf.write_bytes(b"x" * 100)
        tex.write_text("placeholder", encoding="utf-8")
        report = TypesetGate.check(pdf, tex, pages=1)
        assert report.passed is False
        assert any("异常过小" in e for e in report.errors)

    def test_missing_tex_fails(self, tmp_path):
        pdf = tmp_path / "p.pdf"
        pdf.write_bytes(b"%PDF" + b"\x00" * 5000)
        tex = tmp_path / "missing.tex"
        report = TypesetGate.check(pdf, tex, pages=5)
        assert report.passed is False
        assert any("TEX 未生成" in e for e in report.errors)


class TestTypesetGateWarnings:
    def test_too_few_pages_warns(self, tmp_path):
        pdf = tmp_path / "p.pdf"
        tex = tmp_path / "p.tex"
        pdf.write_bytes(b"%PDF" + b"\x00" * 5000)
        tex.write_text("x", encoding="utf-8")
        report = TypesetGate.check(pdf, tex, pages=2)
        assert report.passed is True
        assert any("页数过少" in w for w in report.warnings)

    def test_zero_pages_warns(self, tmp_path):
        pdf = tmp_path / "p.pdf"
        tex = tmp_path / "p.tex"
        pdf.write_bytes(b"%PDF" + b"\x00" * 5000)
        tex.write_text("x", encoding="utf-8")
        report = TypesetGate.check(pdf, tex, pages=0)
        assert any("无法确定" in w for w in report.warnings)
