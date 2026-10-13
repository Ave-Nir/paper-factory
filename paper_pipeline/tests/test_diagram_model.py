"""
test_diagram_model.py — 数据模型测试

验证 DiagramVariant / DiagramPrompt / DiagramResult 的边界条件和类型严格性。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from paper_pipeline.models.diagram import (
    DiagramPrompt,
    DiagramResult,
    DiagramVariant,
    PipelineStage,
)


class TestDiagramVariant:
    def test_valid_construction(self):
        v = DiagramVariant(
            id="C01",
            identity="horizontal_3frame",
            layout="horizontal",
            color="ocean_breeze",
            style="academic",
        )
        assert v.id == "C01"
        assert v.identity == "horizontal_3frame"

    def test_from_dict_with_missing_fields_defaults_to_empty(self):
        v = DiagramVariant.from_dict({})
        assert v.id == ""
        assert v.layout == ""

    def test_from_dict_raises_on_non_dict(self):
        with pytest.raises(ValueError):
            DiagramVariant.from_dict("not a dict")

    def test_from_dict_coerces_to_string(self):
        v = DiagramVariant.from_dict({"id": 123})
        assert v.id == "123"


class TestPipelineStage:
    """S0-S5 必须完整定义且不可自定义."""

    def test_all_stages_defined(self):
        names = {stage.name for stage in PipelineStage}
        assert "S0_ANALYSIS" in names
        assert "S1_STRATEGY" in names
        assert "S2_SKETCH" in names
        assert "S3_DIRECTION" in names
        assert "S4_FORMAL" in names
        assert "S5_FINAL" in names

    def test_stage_count_is_six(self):
        assert len(list(PipelineStage)) == 6


class TestDiagramResultDefaults:
    def test_default_stage_is_s5_final(self):
        r = DiagramResult(
            candidate_id="x",
            image_path=Path("/tmp/x.png"),
            prompt=DiagramPrompt(
                candidate_id="x",
                prompt_text="",
                variant=DiagramVariant(id="", identity="", layout="", color="", style=""),
                target_image_path=Path("/tmp/x.png"),
                prompt_path=Path("/tmp/x.md"),
                stage=PipelineStage.S5_FINAL,
            ),
            generated=False,
        )
        assert r.stage == PipelineStage.S5_FINAL
        assert r.error is None
        assert r.size_kb == 0.0
