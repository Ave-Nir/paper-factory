"""
test_manifest_verifier.py — manifest_verifier 测试

覆盖 P0-C-4：实现上游 manifest/bundle/asset 验证器。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from paper_pipeline.core.manifest_verifier import (
    SUPPORTED_SCHEMAS,
    FullVerificationReport,
    VerificationResult,
    verify_corpus_manifest,
    verify_figure_asset,
    verify_manuscript_source,
    verify_paper_manifest,
    verify_reference_bundle,
    verify_run_artifacts,
)
from paper_pipeline.exceptions import ValidationError


def _write_canonical_json(path: Path, data: dict) -> None:
    """写 JSON 并正确计算 content_sha256."""
    payload = {k: v for k, v in data.items() if k != "content_sha256"}
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    sha = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    data_with_hash = {**data, "content_sha256": sha}
    path.write_text(json.dumps(data_with_hash, ensure_ascii=False, indent=2), encoding="utf-8")


class TestSupportedSchemas:
    """schema 白名单必须覆盖全厂 v1 版本."""

    def test_paper_manifest_supported(self):
        assert "paper_manifest.v1" in SUPPORTED_SCHEMAS["paper_manifest"]

    def test_figure_asset_supported(self):
        assert "figure_asset.v1" in SUPPORTED_SCHEMAS["figure_asset"]

    def test_reference_bundle_supported(self):
        assert "reference_bundle.v1" in SUPPORTED_SCHEMAS["reference_bundle"]


class TestVerifyPaperManifest:
    def test_valid_manifest_passes(self, tmp_path):
        path = tmp_path / "paper_manifest.v1.json"
        _write_canonical_json(path, {
            "schema": "paper_manifest.v1",
            "paper_id": "p1",
            "manuscript_ref": {"path": "manuscript.md"},
            "figure_request_ref": {"rq_id": "rq1"},
            "run_id": "abc123",
        })
        result = verify_paper_manifest(path, expected_run_id="abc123")
        assert result.passed is True
        assert result.errors == []
        assert result.run_id == "abc123"

    def test_hash_mismatch_fails(self, tmp_path):
        path = tmp_path / "pm.json"
        path.write_text(json.dumps({
            "schema": "paper_manifest.v1",
            "paper_id": "p1",
            "content_sha256": "0" * 64,
            "manuscript_ref": {},
            "figure_request_ref": {},
        }), encoding="utf-8")
        result = verify_paper_manifest(path)
        assert result.passed is False
        assert any("content_sha256 不匹配" in e for e in result.errors)

    def test_missing_required_field_fails(self, tmp_path):
        path = tmp_path / "pm.json"
        _write_canonical_json(path, {
            "schema": "paper_manifest.v1",
            "paper_id": "p1",
            # missing manuscript_ref and figure_request_ref
        })
        result = verify_paper_manifest(path)
        assert result.passed is False
        assert any("manuscript_ref" in e for e in result.errors)

    def test_unsupported_schema_fails(self, tmp_path):
        path = tmp_path / "pm.json"
        _write_canonical_json(path, {
            "schema": "paper_manifest.v999",
            "paper_id": "p1",
            "manuscript_ref": {},
            "figure_request_ref": {},
        })
        result = verify_paper_manifest(path)
        assert result.passed is False
        assert any("v999" in e for e in result.errors)

    def test_run_id_mismatch_fails(self, tmp_path):
        path = tmp_path / "pm.json"
        _write_canonical_json(path, {
            "schema": "paper_manifest.v1",
            "paper_id": "p1",
            "manuscript_ref": {},
            "figure_request_ref": {},
            "run_id": "different",
        })
        result = verify_paper_manifest(path, expected_run_id="expected")
        assert result.passed is False
        assert any("run_id 不一致" in e for e in result.errors)


class TestVerifyReferenceBundle:
    def test_valid_bundle_passes(self, tmp_path):
        path = tmp_path / "rb.json"
        _write_canonical_json(path, {
            "schema": "reference_bundle.v1",
            "entries": [{"key": "smith2020", "title": "..."}],
        })
        result = verify_reference_bundle(path)
        assert result.passed is True

    def test_empty_entries_fails(self, tmp_path):
        path = tmp_path / "rb.json"
        _write_canonical_json(path, {
            "schema": "reference_bundle.v1",
            "entries": [],
        })
        result = verify_reference_bundle(path)
        assert result.passed is False
        assert any("entries" in e for e in result.errors)


class TestVerifyFigureAsset:
    def test_valid_figure_passes(self, tmp_path):
        path = tmp_path / "figure_asset.v1.json"
        _write_canonical_json(path, {
            "schema": "figure_asset.v1",
            "figure_id": "fig1",
            "image_path": "/tmp/fig1.png",
        })
        result = verify_figure_asset(path)
        assert result.passed is True

    def test_hash_mismatch_fails(self, tmp_path):
        """T1: figure_asset content_sha256 与文件不一致 → fail."""
        path = tmp_path / "figure_asset.v1.json"
        _write_canonical_json(path, {
            "schema": "figure_asset.v1",
            "figure_id": "fig1",
            "image_path": "/tmp/fig1.png",
        })
        # Mutate file body without recomputing content_sha256
        data = json.loads(path.read_text(encoding="utf-8"))
        data["extra_field_tampered"] = "after_seal"
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        result = verify_figure_asset(path)
        assert result.passed is False
        assert any("content_sha256" in e for e in result.errors)

    def test_lineage_run_id_mismatch_fails(self, tmp_path):
        """T2: figure_asset lineage.run_id 不一致 → fail."""
        path = tmp_path / "figure_asset.v1.json"
        _write_canonical_json(path, {
            "schema": "figure_asset.v1",
            "figure_id": "fig1",
            "image_path": "/tmp/fig1.png",
            "lineage": {"run_id": "different-run"},
            "run_id": "different-run",
        })
        result = verify_figure_asset(path, expected_run_id="expected-run")
        assert result.passed is False
        assert any("run_id 不一致" in e for e in result.errors)

    def test_missing_required_fields_fails(self, tmp_path):
        """T3: figure_asset 缺 figure_id / image_path / content_sha256 → fail."""
        path = tmp_path / "figure_asset.v1.json"
        # Write manually without proper envelope
        path.write_text(json.dumps({
            "schema": "figure_asset.v1",
            # missing figure_id, image_path, content_sha256
        }, ensure_ascii=False), encoding="utf-8")
        result = verify_figure_asset(path)
        assert result.passed is False


class TestVerifyCorpusManifest:
    def test_valid_corpus_manifest_passes(self, tmp_path):
        path = tmp_path / "cm.json"
        _write_canonical_json(path, {
            "schema": "corpus_manifest.v1",
            "dataset": "edu_wos_770",
            "dedup_policy": {"method": "multi_field"},
            "record_counts": {"imported": 770, "final": 770},
        })
        result = verify_corpus_manifest(path)
        assert result.passed is True

    def test_missing_dedup_fails(self, tmp_path):
        path = tmp_path / "cm.json"
        _write_canonical_json(path, {
            "schema": "corpus_manifest.v1",
            "dataset": "edu_wos_770",
            "record_counts": {"imported": 770},
        })
        result = verify_corpus_manifest(path)
        assert result.passed is False
        assert any("dedup_policy" in e for e in result.errors)


class TestMissingFile:
    def test_missing_file_returns_error(self, tmp_path):
        result = verify_paper_manifest(tmp_path / "missing.json")
        assert result.passed is False
        assert any("不存在" in e for e in result.errors)

    def test_empty_file_returns_error(self, tmp_path):
        path = tmp_path / "empty.json"
        path.write_bytes(b"")
        result = verify_paper_manifest(path)
        assert result.passed is False
        assert any("为空" in e for e in result.errors)

    def test_invalid_json_returns_error(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not json", encoding="utf-8")
        result = verify_paper_manifest(path)
        assert result.passed is False
        assert any("JSON 解析失败" in e for e in result.errors)


class TestVerifyRunArtifacts:
    def test_full_valid_run_passes(self, tmp_path):
        run_dir = tmp_path / "runs" / "abc123"
        run_dir.mkdir(parents=True)
        _write_canonical_json(run_dir / "paper_manifest.v1.json", {
            "schema": "paper_manifest.v1",
            "paper_id": "p1",
            "manuscript_ref": {"path": "m.md"},
            "figure_request_ref": {"rq_id": "rq1"},
            "run_id": "abc123",
        })
        _write_canonical_json(run_dir / "manuscript_source.v1.json", {
            "schema": "manuscript_source.v1",
            "content": "# Paper\n\nBody",
            "run_id": "abc123",
        })
        _write_canonical_json(run_dir / "reference_bundle.v1.json", {
            "schema": "reference_bundle.v1",
            "entries": [{"key": "k1"}],
            "run_id": "abc123",
        })
        figures_dir = run_dir / "figures" / "fig1"
        figures_dir.mkdir(parents=True)
        _write_canonical_json(figures_dir / "figure_asset.v1.json", {
            "schema": "figure_asset.v1",
            "figure_id": "fig1",
            "image_path": "/tmp/fig1.png",
            "run_id": "abc123",
        })

        report = verify_run_artifacts(run_dir, expected_run_id="abc123")
        assert report.passed is True

    def test_missing_paper_manifest_raises(self, tmp_path):
        run_dir = tmp_path / "empty"
        run_dir.mkdir()
        with pytest.raises(ValidationError) as exc:
            verify_run_artifacts(run_dir)
        assert "paper_manifest" in str(exc.value)

    def test_missing_reference_can_be_skipped(self, tmp_path):
        """若 require_reference=False,缺失 bundle 不阻断."""
        run_dir = tmp_path / "runs" / "skip_ref"
        run_dir.mkdir(parents=True)
        _write_canonical_json(run_dir / "paper_manifest.v1.json", {
            "schema": "paper_manifest.v1",
            "paper_id": "p1",
            "manuscript_ref": {},
            "figure_request_ref": {},
        })
        _write_canonical_json(run_dir / "manuscript_source.v1.json", {
            "schema": "manuscript_source.v1",
            "content": "x",
        })
        report = verify_run_artifacts(run_dir, require_reference=False)
        assert report.reference_bundle is None
        assert report.passed is True
