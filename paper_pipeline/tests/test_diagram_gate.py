"""
test_diagram_gate.py — DiagramGate (Gate2) 测试

验证 4 张候选图的数量、多样性和大小检查。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from paper_pipeline.gates.quality_gates import DiagramGate
from paper_pipeline.models.diagram import (
    DiagramPrompt,
    DiagramResult,
    DiagramVariant,
    PipelineStage,
)


def _make_result(
    candidate_id: str,
    image_path: Path,
    generated: bool,
    size_kb: float = 100.0,
    variant_id: str = "C01",
    error: str | None = None,
) -> DiagramResult:
    """构造 DiagramResult 工厂."""
    variant = DiagramVariant(
        id=variant_id,
        identity="horizontal_3frame",
        layout="horizontal",
        color="ocean_breeze",
        style="academic",
    )
    prompt = DiagramPrompt(
        candidate_id=candidate_id,
        prompt_text="draw a diagram",
        variant=variant,
        target_image_path=image_path,
        prompt_path=image_path.with_suffix(".md"),
        stage=PipelineStage.S5_FINAL,
    )
    return DiagramResult(
        candidate_id=candidate_id,
        image_path=image_path,
        prompt=prompt,
        generated=generated,
        size_kb=size_kb,
        error=error,
    )


class TestDiagramGateHappyPath:
    def test_4_distinct_results_pass(self, tmp_path):
        results = []
        for i, vid in enumerate(["C01", "C02", "C03", "C04"]):
            img = tmp_path / f"image_{i}.png"
            img.write_bytes(b"\x89PNG" + b"\x00" * 200000)  # ~200KB fake PNG
            results.append(_make_result(f"cand_{i}", img, True, 200.0, vid))
        report = DiagramGate.check(results)
        assert report.passed is True
        assert report.errors == []


class TestDiagramGateErrors:
    def test_too_few_results_fails(self, tmp_path):
        results = []
        for i in range(2):
            img = tmp_path / f"image_{i}.png"
            img.write_bytes(b"\x89PNG" + b"\x00" * 1000)
            results.append(_make_result(f"cand_{i}", img, True, 100.0))
        report = DiagramGate.check(results)
        assert report.passed is False
        assert any("图数量不足" in e for e in report.errors)

    def test_failed_generation_is_error(self, tmp_path):
        img = tmp_path / "missing.png"
        results = [
            _make_result(f"cand_{i}", img, True, 100.0, f"C0{i}")
            for i in range(1, 4)
        ]
        img.write_bytes(b"\x89PNG" + b"\x00" * 100000)
        results.append(_make_result("cand_4", tmp_path / "x.png", False, error="API timeout"))
        report = DiagramGate.check(results)
        assert report.passed is False
        assert any("API timeout" in e for e in report.errors)


class TestDiagramGateWarnings:
    def test_duplicate_variant_warns(self, tmp_path):
        """4 张图如果只有 2 种 variant，应警告多样性不足."""
        results = []
        for i in range(4):
            img = tmp_path / f"image_{i}.png"
            img.write_bytes(b"\x89PNG" + b"\x00" * 200000)
            results.append(_make_result(f"cand_{i}", img, True, 200.0, "C01"))
        report = DiagramGate.check(results)
        assert any("变体重复" in w for w in report.warnings)
