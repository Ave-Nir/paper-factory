"""L2 tests for submission_manifest_builder — SPEC-X P1-1 (C-P1-1).

Tests:
1. build_submission_manifest: end-to-end with valid upstream artifacts
2. T1 fail-closed: paper_manifest not found → SubmissionManifestError
3. T2 fail-closed: paper_manifest hash mismatch → SubmissionManifestError
4. T3 fail-closed: reference_bundle hash mismatch → SubmissionManifestError
5. T4 fail-closed: figure_asset hash mismatch → SubmissionManifestError
6. T5 fail-closed: figure_asset run_id mismatch → SubmissionManifestError
7. T6 fail-closed: cross-service run_id inconsistency → SubmissionManifestError
8. T7 atomic write: tmp file cleaned up on error
9. T8 schema compliance: built submission matches required schema fields
"""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

# Allow direct import of paper_pipeline package + relative imports within it
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "src"))
sys.path.insert(0, str(_REPO_ROOT))

import importlib.util

# 模块名与文件包路径保持一致，保证 dataclass 正常工作
_MODULE_NAME = "_paper_pipeline_core_submission_manifest_builder"
_spec = importlib.util.spec_from_file_location(
    _MODULE_NAME,
    _REPO_ROOT / "src" / "paper_pipeline" / "core" / "submission_manifest_builder.py",
)
smb = importlib.util.module_from_spec(_spec)
sys.modules[_MODULE_NAME] = smb
_spec.loader.exec_module(smb)

# Import SubmissionManifestError
SubmissionManifestError = smb.SubmissionManifestError
build_submission_manifest = smb.build_submission_manifest
write_submission_manifest = smb.write_submission_manifest


def _canonical_sha(data: dict) -> str:
    payload = {k: v for k, v in data.items() if k != "content_sha256"}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _write_canonical_json(path: Path, data: dict) -> str:
    """Write JSON with proper content_sha256 envelope."""
    payload = {k: v for k, v in data.items() if k != "content_sha256"}
    data["content_sha256"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data["content_sha256"]


class TestBuildSubmissionManifest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

        # Create valid upstream paper_manifest
        self.paper_manifest = {
            "schema_version": "paper_manifest.v1",
            "artifact_id": "test-pm-id",
            "run_id": "test-run-id",
            "status": "completed",
            "analysis_result_ref": {
                "artifact_id": "test-ar-id",
                "content_sha256": "a" * 64,
            },
            "claim_evidence_map": [
                {"evidence_id": "ev_1", "section_id": "results.3.1", "rq_id": "RQ1", "artifact_ref": {}, "json_pointer": "/x", "claim_scope": "s"},
                {"evidence_id": "ev_2", "section_id": "results.3.1", "rq_id": "RQ2", "artifact_ref": {}, "json_pointer": "/y", "claim_scope": "s"},
            ],
        }
        self.pm_path = self.tmpdir / "paper_manifest.v1.json"
        _write_canonical_json(self.pm_path, self.paper_manifest)

        # Create valid upstream reference_bundle
        self.reference_bundle = {
            "schema_version": "reference_bundle.v1",
            "artifact_id": "test-rb-id",
            "run_id": "test-run-id",
            "status": "completed",
            "entries": [],
        }
        self.rb_path = self.tmpdir / "reference_bundle.v1.json"
        _write_canonical_json(self.rb_path, self.reference_bundle)

        # Create valid upstream figure_asset
        self.figure_asset = {
            "schema_version": "figure_asset.v1",
            "artifact_id": "test-fa-id",
            "run_id": "test-run-id",
            "status": "completed",
            "figure_id": "Figure 1",
            "assets": [],
            "caption": "Test caption",
            "alt_text": "Test alt",
            "lineage": {"run_id": "test-run-id"},
            "review_status": "pending",
        }
        self.fa_path = self.tmpdir / "figures" / "figure_asset.v1.json"
        self.fa_path.parent.mkdir(parents=True, exist_ok=True)
        _write_canonical_json(self.fa_path, self.figure_asset)

    def test_build_end_to_end(self):
        """End-to-end build with valid upstream artifacts."""
        submission = build_submission_manifest(
            run_dir=self.tmpdir,
            paper_manifest_path=self.pm_path,
            reference_bundle_path=self.rb_path,
            figure_asset_paths=[self.fa_path],
            output_artifacts=[
                {"artifact_id": "out-1", "media_type": "application/pdf",
                 "relative_path": "paper.pdf", "content_sha256": "f" * 64}
            ],
            gate5_passed=True,
            funding=["Grant 123"],
        )

        self.assertEqual(submission["schema_version"], "submission_manifest.v1")
        self.assertEqual(submission["status"], "completed")
        self.assertEqual(submission["run_id"], "test-run-id")
        self.assertEqual(submission["claim_evidence_count"], 2)
        self.assertEqual(submission["evidence_by_section"]["results.3.1"], 2)
        # envelope present
        self.assertTrue(submission["content_sha256"])
        self.assertEqual(submission["gate5"]["passed"], True)
        # schema required fields
        for field in ("schema_version", "artifact_id", "run_id", "submission_run_id",
                      "producer", "created_at", "content_sha256", "status", "lineage",
                      "paper_manifest_ref", "reference_bundle_ref", "figure_asset_refs",
                      "template", "outputs", "gate5", "human_visual_review", "declarations"):
            self.assertIn(field, submission, f"missing required field: {field}")

    def test_fail_paper_manifest_not_found(self):
        """T1: paper_manifest missing → SubmissionManifestError."""
        with self.assertRaises(SubmissionManifestError) as ctx:
            build_submission_manifest(
                run_dir=self.tmpdir,
                paper_manifest_path=self.tmpdir / "nonexistent.json",
                reference_bundle_path=self.rb_path,
                figure_asset_paths=[self.fa_path],
            )
        self.assertIn("paper_manifest 不存在", str(ctx.exception))

    def test_fail_paper_manifest_hash_mismatch(self):
        """T2: paper_manifest on-disk content doesn't match declared content_sha256."""
        # Write a valid pm first, then mutate file body without recomputing content_sha256
        # First write a valid PM with canonical hash
        _write_canonical_json(self.pm_path, {
            "schema_version": "paper_manifest.v1",
            "artifact_id": "test-pm-id",
            "run_id": "test-run-id",
            "status": "completed",
            "claim_evidence_map": [],
            "analysis_result_ref": {},
        })
        # Then MUTATE file body without recomputing content_sha256 (add extra field)
        # Read, mutate, write back without recomputing hash
        pm_data = json.loads(self.pm_path.read_text(encoding="utf-8"))
        pm_data["extra_field_added_after_seal"] = "tampered"
        # Write back without recomputing content_sha256
        self.pm_path.write_text(
            json.dumps(pm_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        with self.assertRaises(SubmissionManifestError) as ctx:
            build_submission_manifest(
                run_dir=self.tmpdir,
                paper_manifest_path=self.pm_path,
                reference_bundle_path=self.rb_path,
                figure_asset_paths=[self.fa_path],
            )
        self.assertIn("paper_manifest", str(ctx.exception))

    def test_fail_reference_bundle_hash_mismatch(self):
        """T3: reference_bundle hash mismatch → SubmissionManifestError."""
        # Write a valid rb first, then mutate file body
        _write_canonical_json(self.rb_path, {
            "schema_version": "reference_bundle.v1",
            "artifact_id": "test-rb-id",
            "run_id": "test-run-id",
            "status": "completed",
            "entries": [],
        })
        # Mutate body without recomputing content_sha256
        rb_data = json.loads(self.rb_path.read_text(encoding="utf-8"))
        rb_data["extra_field_added_after_seal"] = "tampered"
        self.rb_path.write_text(
            json.dumps(rb_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        with self.assertRaises(SubmissionManifestError) as ctx:
            build_submission_manifest(
                run_dir=self.tmpdir,
                paper_manifest_path=self.pm_path,
                reference_bundle_path=self.rb_path,
                figure_asset_paths=[self.fa_path],
            )
        self.assertIn("reference_bundle", str(ctx.exception))

    def test_fail_figure_asset_hash_mismatch(self):
        """T4: figure_asset on-disk content doesn't match declared content_sha256."""
        # Tamper: write with wrong hash
        bad_fa = {
            "schema_version": "figure_asset.v1",
            "artifact_id": "test-fa-id",
            "run_id": "test-run-id",
            "status": "completed",
            "figure_id": "Figure 1",
            "assets": [],
            "lineage": {"run_id": "test-run-id"},
            "content_sha256": "badhash" * 8 + "badhas",
        }
        self.fa_path.write_text(json.dumps(bad_fa, ensure_ascii=False), encoding="utf-8")

        with self.assertRaises(SubmissionManifestError) as ctx:
            build_submission_manifest(
                run_dir=self.tmpdir,
                paper_manifest_path=self.pm_path,
                reference_bundle_path=self.rb_path,
                figure_asset_paths=[self.fa_path],
            )
        self.assertIn("figure_asset", str(ctx.exception))

    def test_fail_figure_asset_run_id_mismatch(self):
        """T5: figure_asset run_id differs from paper_manifest run_id → blocked."""
        bad_fa = {
            "schema_version": "figure_asset.v1",
            "artifact_id": "test-fa-id",
            "run_id": "different-run-id",  # Wrong!
            "status": "completed",
            "figure_id": "Figure 1",
            "assets": [],
            "lineage": {"run_id": "different-run-id"},
        }
        _write_canonical_json(self.fa_path, bad_fa)

        with self.assertRaises(SubmissionManifestError) as ctx:
            build_submission_manifest(
                run_dir=self.tmpdir,
                paper_manifest_path=self.pm_path,
                reference_bundle_path=self.rb_path,
                figure_asset_paths=[self.fa_path],
            )
        self.assertIn("run_id_mismatch", str(ctx.exception))

    def test_fail_cross_service_run_id_inconsistency(self):
        """T6: paper_manifest run_id != reference_bundle run_id → blocked."""
        # Make reference_bundle have a different run_id
        self.reference_bundle["run_id"] = "different-run-id"
        _write_canonical_json(self.rb_path, self.reference_bundle)

        with self.assertRaises(SubmissionManifestError) as ctx:
            build_submission_manifest(
                run_dir=self.tmpdir,
                paper_manifest_path=self.pm_path,
                reference_bundle_path=self.rb_path,
                figure_asset_paths=[self.fa_path],
            )
        self.assertIn("run_id 不一致", str(ctx.exception))

    def test_atomic_write_no_tmp_leftover(self):
        """T7: atomic write cleans up tmp on success."""
        submission = build_submission_manifest(
            run_dir=self.tmpdir,
            paper_manifest_path=self.pm_path,
            reference_bundle_path=self.rb_path,
            figure_asset_paths=[self.fa_path],
        )
        out = self.tmpdir / "submission.json"
        write_submission_manifest(submission, out)
        self.assertTrue(out.exists())
        tmp = out.with_suffix(out.suffix + ".tmp")
        self.assertFalse(tmp.exists())

    def test_schema_required_fields(self):
        """T8: built submission has all schema required fields."""
        submission = build_submission_manifest(
            run_dir=self.tmpdir,
            paper_manifest_path=self.pm_path,
            reference_bundle_path=self.rb_path,
            figure_asset_paths=[self.fa_path],
            output_artifacts=[{"artifact_id": "o1", "media_type": "application/pdf",
                                "relative_path": "p.pdf", "content_sha256": "0"*64}],
        )

        # Submission-specific required fields per submission_manifest.v1.schema.json
        for field in ("submission_run_id", "paper_manifest_ref", "reference_bundle_ref",
                      "figure_asset_refs", "template", "outputs", "gate5",
                      "human_visual_review", "declarations"):
            self.assertIn(field, submission)

        # paper_manifest_ref has required subfields
        for sub in ("artifact_id", "kind", "content_sha256"):
            self.assertIn(sub, submission["paper_manifest_ref"])

        # declarations has required subfields
        for sub in ("data_availability", "funding", "conflicts"):
            self.assertIn(sub, submission["declarations"])

        # outputs minItems=1 (per schema)
        self.assertGreaterEqual(len(submission["outputs"]), 1)

    def test_gate5_blocked_status(self):
        """When gate5_passed=False, status='blocked'."""
        submission = build_submission_manifest(
            run_dir=self.tmpdir,
            paper_manifest_path=self.pm_path,
            reference_bundle_path=self.rb_path,
            figure_asset_paths=[self.fa_path],
            gate5_passed=False,
            gate5_issues=["FONT_INCONSISTENT", "TOC_NOT_SEPARATE"],
        )
        self.assertEqual(submission["status"], "blocked")
        self.assertEqual(submission["gate5"]["passed"], False)
        self.assertEqual(len(submission["gate5"]["issues"]), 2)

    def test_multiple_figure_assets(self):
        """Verify multiple figure_assets can be linked."""
        # Create a second figure_asset
        fa2_path = self.tmpdir / "figures" / "figure_asset_2.v1.json"
        fa2_data = {
            "schema_version": "figure_asset.v1",
            "artifact_id": "test-fa2-id",
            "run_id": "test-run-id",
            "status": "completed",
            "figure_id": "Figure 2",
            "assets": [],
            "caption": "Test caption 2",
            "alt_text": "Test alt 2",
            "lineage": {"run_id": "test-run-id"},
        }
        _write_canonical_json(fa2_path, fa2_data)

        submission = build_submission_manifest(
            run_dir=self.tmpdir,
            paper_manifest_path=self.pm_path,
            reference_bundle_path=self.rb_path,
            figure_asset_paths=[self.fa_path, fa2_path],
        )
        self.assertEqual(len(submission["figure_asset_refs"]), 2)


if __name__ == "__main__":
    unittest.main()