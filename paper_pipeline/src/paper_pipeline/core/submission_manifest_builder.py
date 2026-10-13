"""submission_manifest_builder.py — C 侧最终交付物 submission_manifest.v1.json 构建器.

SPEC-X P1-1 (C-P1-1): submission_manifest 是 C 排版交付最终产物,
必须严格满足 submission_manifest.v1 schema, 且上游 3 类 artifact refs 必须一致.

上游 ref 一致性 (架构根因):
  - paper_manifest_ref.content_sha256 与实际 paper_manifest 文件 hash 一致
  - reference_bundle_ref.content_sha256 与实际 reference_bundle 文件 hash 一致
  - figure_asset_refs[] 中每个 content_sha256 与实际 figure_asset 文件 hash 一致
  - 三处上游 ref 的 run_id 必须一致

不一致时 fail-closed 阻断提交, 抛出 SubmissionManifestError.

调用方必须 catch SubmissionManifestError 并阻断排版提交.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Try package import first; fall back to direct module import for standalone use.
try:
    from paper_pipeline.exceptions import ValidationError
except ImportError:
    import importlib.util as _importlib_util
    from pathlib import Path as _Path
    _ex_path = _Path(__file__).resolve().parent.parent / "exceptions.py"
    _spec = _importlib_util.spec_from_file_location("_paper_pipeline_exceptions", _ex_path)
    _mod = _importlib_util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    ValidationError = _mod.ValidationError


SUBMISSION_MANIFEST_SCHEMA_VERSION = "submission_manifest.v1"


@dataclass
class UpstreamArtifactRef:
    """上游 artifact 引用 — 在 submission_manifest 中每个上游 ref 都必须有
    artifact_id + content_sha256 一致性."""

    artifact_id: str
    kind: str
    schema_version: str
    run_id: str
    content_sha256: str
    relative_path: Path


class SubmissionManifestError(ValidationError):
    """submission_manifest 构建/校验异常.

    当上游 artifact refs 不一致时 fail-closed 抛出.
    """

    def __init__(
        self,
        message: str,
        *,
        mismatched_refs: list[dict[str, Any]] | None = None,
        run_dir: Path | None = None,
    ) -> None:
        super().__init__(
            message,
            stage="SUBMISSION_MANIFEST_BUILD",
            context={
                "run_dir": str(run_dir) if run_dir else None,
                "mismatched_refs": mismatched_refs or [],
            },
        )
        self.mismatched_refs = mismatched_refs or []


def _canonical_sha256(data: dict[str, Any]) -> str:
    """Compute canonical JSON SHA-256, excluding content_sha256 itself.

    Matches scripts/pipeline_common.canonical_sha256 (FTG-007 contract).
    """
    payload = {k: v for k, v in data.items() if k != "content_sha256"}
    serialized = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _sha256_of_file(path: Path) -> str:
    """Compute canonical SHA-256 of the JSON file at ``path``.

    FTG-007 contract: content_sha256 stored in artifact is the CANONICAL
    JSON SHA-256 (sorted keys, no indentation, UTF-8), NOT the file bytes.
    This matches scripts/pipeline_common.canonical_sha256 and B-side
    input_verifier._compute_canonical_hash.
    """
    data = json.loads(path.read_text(encoding="utf-8"))
    return _canonical_sha256(data)


def _verify_upstream_ref(
    ref: dict[str, Any],
    actual_path: Path,
    *,
    required_kind: str,
    run_dir: Path,
) -> tuple[bool, str]:
    """Verify one upstream ref's content_sha256 matches the actual file hash.

    Returns (is_consistent, error_message). When is_consistent=False, error_message
    describes the mismatch in detail.
    """
    if not actual_path.exists():
        return False, f"上游 artifact 文件不存在: {actual_path}"

    declared_sha = ref.get("content_sha256", "")
    if not declared_sha:
        return False, f"上游 ref 缺少 content_sha256: {ref.get('artifact_id', '?')}"

    kind = ref.get("kind", "")
    if kind != required_kind:
        return False, f"上游 ref kind 错误: 期望 {required_kind!r}, 实际 {kind!r}"

    actual_sha = _sha256_of_file(actual_path)
    if declared_sha != actual_sha:
        return False, (
            f"上游 ref {required_kind} content_sha256 不一致:\n"
            f"  声明: {declared_sha[:16]}...\n"
            f"  实际: {actual_sha[:16]}...\n"
            f"  文件: {actual_path}"
        )
    return True, ""


def build_submission_manifest(
    *,
    run_dir: Path,
    paper_manifest_path: Path,
    reference_bundle_path: Path,
    figure_asset_paths: list[Path],
    template_id: str = "auto",
    template_version: str = "1.0.0",
    template_engine: str = "latex",
    anonymous_required: bool = False,
    output_artifacts: list[dict[str, str]] | None = None,
    gate5_passed: bool = True,
    gate5_issues: list[str] | None = None,
    data_availability: str = "available",
    funding: list[str] | None = None,
    conflicts: str = "none",
    ethics: str = "n/a",
) -> dict[str, Any]:
    """Build submission_manifest.v1 with strict upstream ref validation.

    SPEC-X P1-1 (C-P1-1): Fail-closed on any upstream inconsistency.

    Args:
        run_dir: runs/<run_id>/ directory.
        paper_manifest_path: B 侧 paper_manifest.v1.json 路径.
        reference_bundle_path: D1 侧 reference_bundle.v1.json 路径.
        figure_asset_paths: E 侧 figure_asset.v1.json 路径列表.
        template_id/template_version/template_engine: 排版模板元数据.
        anonymous_required: 是否需要匿名版本.
        output_artifacts: C 端 PDF/DOCX/TeX 产物 (relative_path, content_sha256, media_type).
        gate5_passed: Gate5 PDF 严格检测是否通过.
        gate5_issues: Gate5 检测的 issues 列表.
        data_availability/funding/conflicts/ethics: 投稿声明.

    Returns:
        submission_manifest dict (含 content_sha256).

    Raises:
        SubmissionManifestError: 任一上游 ref 不一致或文件缺失.
    """
    run_dir = Path(run_dir)
    paper_manifest_path = Path(paper_manifest_path)
    reference_bundle_path = Path(reference_bundle_path)

    # ── Step 1: 验证上游 paper_manifest (file_exists + content_sha256) ──
    if not paper_manifest_path.exists():
        raise SubmissionManifestError(
            f"上游 paper_manifest 不存在: {paper_manifest_path}",
            run_dir=run_dir,
        )
    try:
        pm_data = json.loads(paper_manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SubmissionManifestError(
            f"上游 paper_manifest 不可解析: {exc}",
            run_dir=run_dir,
        ) from exc

    pm_ref = pm_data.get("content_sha256", "")
    pm_run_id = pm_data.get("run_id", "")
    pm_artifact_id = pm_data.get("artifact_id", "")
    pm_schema_version = pm_data.get("schema_version", "")

    # ── Step 1.5: 验证 paper_manifest content_sha256 一致性 (FTG-007) ──
    if not pm_ref:
        raise SubmissionManifestError(
            f"上游 paper_manifest 缺少 content_sha256 字段: {paper_manifest_path}",
            run_dir=run_dir,
        )
    pm_actual_sha = _sha256_of_file(paper_manifest_path)
    if pm_actual_sha != pm_ref:
        raise SubmissionManifestError(
            f"上游 paper_manifest content_sha256 不一致:\n"
            f"  声明: {pm_ref[:16]}...\n"
            f"  实际: {pm_actual_sha[:16]}...",
            mismatched_refs=[{
                "kind": "paper_manifest",
                "declared_sha256": pm_ref[:16],
                "actual_sha256": pm_actual_sha[:16],
                "path": str(paper_manifest_path),
            }],
            run_dir=run_dir,
        )

    # ── Step 2: 验证上游 reference_bundle ──
    if not reference_bundle_path.exists():
        raise SubmissionManifestError(
            f"上游 reference_bundle 不存在: {reference_bundle_path}",
            run_dir=run_dir,
        )
    try:
        rb_data = json.loads(reference_bundle_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SubmissionManifestError(
            f"上游 reference_bundle 不可解析: {exc}",
            run_dir=run_dir,
        ) from exc

    rb_ref = rb_data.get("content_sha256", "")
    rb_run_id = rb_data.get("run_id", "")
    rb_artifact_id = rb_data.get("artifact_id", "")
    rb_schema_version = rb_data.get("schema_version", "")

    # ── Step 2.5: 验证 reference_bundle content_sha256 一致性 (FTG-007) ──
    if not rb_ref:
        raise SubmissionManifestError(
            f"上游 reference_bundle 缺少 content_sha256 字段: {reference_bundle_path}",
            run_dir=run_dir,
        )
    rb_actual_sha = _sha256_of_file(reference_bundle_path)
    if rb_actual_sha != rb_ref:
        raise SubmissionManifestError(
            f"上游 reference_bundle content_sha256 不一致:\n"
            f"  声明: {rb_ref[:16]}...\n"
            f"  实际: {rb_actual_sha[:16]}...",
            mismatched_refs=[{
                "kind": "reference_bundle",
                "declared_sha256": rb_ref[:16],
                "actual_sha256": rb_actual_sha[:16],
                "path": str(reference_bundle_path),
            }],
            run_dir=run_dir,
        )

    # ── Step 3: 验证上游 figure_assets ──
    figure_asset_refs: list[dict[str, Any]] = []
    figure_asset_mismatches: list[dict[str, Any]] = []
    for fa_path in figure_asset_paths:
        fa_path = Path(fa_path)
        if not fa_path.exists():
            figure_asset_mismatches.append({
                "kind": "figure_asset",
                "error": f"file_not_found",
                "path": str(fa_path),
            })
            continue
        try:
            fa_data = json.loads(fa_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            figure_asset_mismatches.append({
                "kind": "figure_asset",
                "error": f"json_decode: {exc}",
                "path": str(fa_path),
            })
            continue
        fa_ref = fa_data.get("content_sha256", "")
        fa_artifact_id = fa_data.get("artifact_id", "")
        fa_run_id = fa_data.get("run_id", "")
        # ── FTG-007 hash 一致性 ──
        if fa_ref != _sha256_of_file(fa_path):
            figure_asset_mismatches.append({
                "kind": "figure_asset",
                "error": "hash_mismatch",
                "declared_sha256": fa_ref[:16],
                "actual_sha256": _sha256_of_file(fa_path)[:16],
                "path": str(fa_path),
            })
            continue
        # ── run_id 一致性 (跨 run 不允许混入) ──
        if pm_run_id and fa_run_id and fa_run_id != pm_run_id:
            figure_asset_mismatches.append({
                "kind": "figure_asset",
                "error": "run_id_mismatch",
                "declared_run_id": fa_run_id,
                "expected_run_id": pm_run_id,
                "path": str(fa_path),
            })
            continue
        figure_asset_refs.append({
            "artifact_id": fa_artifact_id,
            "kind": "figure_asset",
            "schema_version": fa_data.get("schema_version", ""),
            "run_id": fa_run_id,
            "content_sha256": fa_ref,
        })

    # ── Step 4: 跨上游 run_id 一致性 (B / D1 / E 必须同一 run) ──
    if pm_run_id and rb_run_id and pm_run_id != rb_run_id:
        raise SubmissionManifestError(
            f"上游 run_id 不一致: paper_manifest={pm_run_id}, reference_bundle={rb_run_id}",
            mismatched_refs=[{
                "kind": "run_id",
                "expected": pm_run_id,
                "actual": rb_run_id,
            }],
            run_dir=run_dir,
        )

    # ── Step 5: 若有 figure_asset mismatch, fail-closed ──
    if figure_asset_mismatches:
        raise SubmissionManifestError(
            f"{len(figure_asset_mismatches)} 个 figure_asset 上游不一致 — "
            f"submission_manifest 不能构建",
            mismatched_refs=figure_asset_mismatches,
            run_dir=run_dir,
        )

    # ── Step 6: 构造 submission_manifest (envelope 注入后计算 hash) ──
    submission_run_id = pm_run_id or str(uuid.uuid4())

    submission = {
        "schema_version": SUBMISSION_MANIFEST_SCHEMA_VERSION,
        "artifact_id": str(uuid.uuid4()),
        "run_id": pm_run_id or str(uuid.uuid4()),
        "submission_run_id": submission_run_id,
        "producer": {
            "service": "typesetting",
            "version": "1.0.0",
            "code_revision": os.environ.get("GIT_COMMIT", "unverified"),
        },
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "status": "completed" if gate5_passed else "blocked",
        "analysis_result_ref": pm_data.get("analysis_result_ref", {}),
        "paper_manifest_ref": {
            "artifact_id": pm_artifact_id,
            "kind": "paper_manifest",
            "schema_version": pm_schema_version,
            "run_id": pm_run_id,
            "content_sha256": pm_ref,
            "status": pm_data.get("status", "completed"),
        },
        "reference_bundle_ref": {
            "artifact_id": rb_artifact_id,
            "kind": "reference_bundle",
            "schema_version": rb_schema_version,
            "run_id": rb_run_id,
            "content_sha256": rb_ref,
            "status": rb_data.get("status", "completed"),
        },
        "figure_asset_refs": figure_asset_refs,
        "template": {
            "id": template_id,
            "version": template_version,
            "engine": template_engine,
            "anonymous_required": anonymous_required,
        },
        "outputs": output_artifacts or [],
        "gate5": {
            "passed": gate5_passed,
            "rule_id": "T7_PAPER_MANIFEST_CONSUMED",
            "severity": "info" if gate5_passed else "error",
            "issues": gate5_issues or [],
            "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
        "human_visual_review": {
            "status": "not_required",
        },
        "declarations": {
            "data_availability": data_availability,
            "funding": funding or [],
            "conflicts": conflicts,
            "ethics": ethics,
        },
        "claim_evidence_count": len(pm_data.get("claim_evidence_map", [])),
        "evidence_by_section": _aggregate_evidence_by_section(
            pm_data.get("claim_evidence_map", [])
        ),
        "extensions": {},
        "lineage": {
            "parent_refs": [pm_artifact_id, rb_artifact_id] + [
                fa["artifact_id"] for fa in figure_asset_refs
            ],
            "source_run_ids": [pm_run_id] if pm_run_id else [],
        },
    }

    # ── Step 7: 在 envelope 注入后计算 content_sha256 (canonical, 排除自身) ──
    submission["content_sha256"] = _canonical_sha256(submission)

    return submission


def _aggregate_evidence_by_section(cems: list[dict[str, Any]]) -> dict[str, int]:
    """按 section_id 聚合 evidence 数量 (用于 FTG-007 验证)."""
    agg: dict[str, int] = {}
    for c in cems:
        sid = c.get("section_id", "")
        if sid:
            agg[sid] = agg.get(sid, 0) + 1
    return agg


def write_submission_manifest(
    submission: dict[str, Any],
    output_path: Path,
) -> Path:
    """Atomically write submission_manifest to disk.

    SPEC-X P1 T3 invariant: tmp + os.replace for atomic write.
    """
    import os as _os
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    try:
        tmp_path.write_text(
            json.dumps(submission, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _os.replace(tmp_path, output_path)
    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise
    return output_path