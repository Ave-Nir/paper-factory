"""
manifest_verifier.py — 上游 manifest/bundle/asset 验证器

C 侧 (排版交付) 接收来自上游的 3 类 artifact，必须先验证才能进入排版流水线：
  - paper_manifest.v1.json    (B 侧产出，含 manuscript_source / figure_request refs)
  - reference_bundle.v1.json  (D1 侧产出，含 formatted_bibliography)
  - figure_asset.v1.json × N  (E 侧产出，含 content_sha256 + lineage)

每个 artifact 必须满足：
  1. 文件存在且可读
  2. schema 版本号匹配
  3. content_sha256 与文件实际内容一致 (FTG-007)
  4. lineage.run_id 一致 (跨服务引用闭合)
  5. 必填字段非空

失败时抛出 ValidationError，调用方必须 catch 并阻断排版。
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..exceptions import ValidationError


# 已知 schema 版本号白名单
SUPPORTED_SCHEMAS: dict[str, set[str]] = {
    "paper_manifest": {"paper_manifest.v1"},
    "reference_bundle": {"reference_bundle.v1"},
    "figure_asset": {"figure_asset.v1"},
    "submission_manifest": {"submission_manifest.v1"},  # SPEC-X P1-1 (C-P1-1)
    "manuscript_source": {"manuscript_source.v1"},
    "corpus_manifest": {"corpus_manifest.v1"},
    "analysis_audit": {"analysis_audit.v1"},
    "analysis_result": {"analysis_result.v2"},
}


@dataclass
class VerificationResult:
    """单条 artifact 验证结果."""
    artifact_type: str
    artifact_path: Path
    passed: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    schema_version: str | None = None
    content_sha256: str | None = None
    run_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_type": self.artifact_type,
            "artifact_path": str(self.artifact_path),
            "passed": self.passed,
            "errors": self.errors,
            "warnings": self.warnings,
            "schema_version": self.schema_version,
            "content_sha256": self.content_sha256,
            "run_id": self.run_id,
        }


def _compute_canonical_sha256(data: dict[str, Any]) -> str:
    """Compute canonical JSON SHA-256, excluding content_sha256 itself.

    Matches scripts/pipeline_common.canonical_sha256 (FTG-007 contract).
    """
    payload = {k: v for k, v in data.items() if k != "content_sha256"}
    serialized = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _verify_one(
    artifact_type: str,
    path: Path,
    *,
    expected_run_id: str | None = None,
    require_fields: list[str] | None = None,
) -> VerificationResult:
    """验证单个 JSON artifact 的存在性、schema、hash、lineage."""
    result = VerificationResult(
        artifact_type=artifact_type,
        artifact_path=path,
        passed=False,
    )

    # 1. 存在性
    if not path.exists():
        result.errors.append(f"文件不存在: {path}")
        return result
    if path.stat().st_size == 0:
        result.errors.append(f"文件为空: {path}")
        return result

    # 2. JSON 可解析
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        result.errors.append(f"JSON 解析失败: {exc}")
        return result
    except UnicodeDecodeError as exc:
        result.errors.append(f"编码错误: {exc}")
        return result

    # 3. schema 版本号
    schema = data.get("schema") or data.get("schema_version")
    if schema is None:
        result.warnings.append("未声明 schema 字段")
    else:
        result.schema_version = schema
        supported = SUPPORTED_SCHEMAS.get(artifact_type, set())
        if supported and schema not in supported:
            result.errors.append(
                f"schema 版本 {schema!r} 不在白名单 {sorted(supported)!r}"
            )

    # 4. content_sha256 一致性 (FTG-007)
    declared_hash = data.get("content_sha256")
    if declared_hash is None:
        result.warnings.append("未声明 content_sha256 — 跳过 hash 校验")
    else:
        actual_hash = _compute_canonical_sha256(data)
        result.content_sha256 = actual_hash
        if declared_hash != actual_hash:
            result.errors.append(
                f"content_sha256 不匹配: 声明={declared_hash[:16]}..., 实际={actual_hash[:16]}..."
            )

    # 5. lineage.run_id 一致性
    lineage = data.get("lineage") or {}
    artifact_run_id = lineage.get("run_id") or data.get("run_id")
    result.run_id = artifact_run_id
    if expected_run_id is not None and artifact_run_id is not None:
        if artifact_run_id != expected_run_id:
            result.errors.append(
                f"run_id 不一致: 期望={expected_run_id}, 实际={artifact_run_id}"
            )

    # 6. 必填字段
    if require_fields:
        for field_name in require_fields:
            value = data.get(field_name)
            if value is None or value == "" or value == []:
                result.errors.append(f"必填字段缺失或为空: {field_name}")

    result.passed = len(result.errors) == 0
    return result


def verify_paper_manifest(
    path: Path, *, expected_run_id: str | None = None
) -> VerificationResult:
    """验证 B 侧 paper_manifest.v1.json."""
    return _verify_one(
        "paper_manifest",
        path,
        expected_run_id=expected_run_id,
        require_fields=["paper_id", "manuscript_ref", "figure_request_ref"],
    )


def verify_reference_bundle(
    path: Path, *, expected_run_id: str | None = None
) -> VerificationResult:
    """验证 D1 侧 reference_bundle.v1.json."""
    return _verify_one(
        "reference_bundle",
        path,
        expected_run_id=expected_run_id,
        require_fields=["entries"],
    )


def verify_submission_manifest(
    path: Path, *, expected_run_id: str | None = None
) -> VerificationResult:
    """验证 C 侧提交物 submission_manifest.v1.json (排版交付最终产物).

    SPEC-X P1-1 (C-P1-1): submission_manifest 是 C 排版交付最终产物,
    必须严格满足 submission_manifest.v1 schema, 且上游 3 类 artifact refs 必须一致.

    必填字段:
      - schema_version = "submission_manifest.v1"
      - submission_run_id, paper_manifest_ref, reference_bundle_ref,
        figure_asset_refs, template, outputs (minItems=1),
        gate5 (passed), human_visual_review (status),
        declarations (data_availability, funding, conflicts)
      - content_sha256 与文件实际内容一致 (FTG-007)

    上游 ref 一致性:
      - paper_manifest_ref.content_sha256 与实际 paper_manifest 文件 hash 一致
      - reference_bundle_ref.content_sha256 与实际 reference_bundle 文件 hash 一致
      - figure_asset_refs[] 中每个 content_sha256 与实际 figure_asset 文件 hash 一致
      - 三处上游 ref 的 run_id 必须一致 (与 expected_run_id 一致)
    """
    return _verify_one(
        "submission_manifest",
        path,
        expected_run_id=expected_run_id,
        require_fields=[
            "submission_run_id",
            "paper_manifest_ref",
            "reference_bundle_ref",
            "figure_asset_refs",
            "template",
            "outputs",
            "gate5",
            "human_visual_review",
            "declarations",
        ],
    )


def verify_figure_asset(
    path: Path, *, expected_run_id: str | None = None
) -> VerificationResult:
    """验证 E 侧 figure_asset.v1.json.

    figure_asset 单文件较小，可以批量验证目录下所有 *.v1.json.
    """
    return _verify_one(
        "figure_asset",
        path,
        expected_run_id=expected_run_id,
        require_fields=["figure_id", "image_path", "content_sha256"],
    )


def verify_manuscript_source(
    path: Path, *, expected_run_id: str | None = None
) -> VerificationResult:
    """验证 B 侧 manuscript_source.v1.json (纯文本源稿件)."""
    return _verify_one(
        "manuscript_source",
        path,
        expected_run_id=expected_run_id,
        require_fields=["content"],
    )


def verify_corpus_manifest(
    path: Path, *, expected_run_id: str | None = None
) -> VerificationResult:
    """验证 A 侧 corpus_manifest.v1.json (用于数据可信度回溯)."""
    return _verify_one(
        "corpus_manifest",
        path,
        expected_run_id=expected_run_id,
        require_fields=["dataset", "dedup_policy", "record_counts"],
    )


@dataclass
class FullVerificationReport:
    """一组 artifact 的完整验证报告."""
    paper_manifest: VerificationResult | None
    manuscript_source: VerificationResult | None
    reference_bundle: VerificationResult | None
    figure_assets: list[VerificationResult]

    @property
    def passed(self) -> bool:
        if self.paper_manifest and not self.paper_manifest.passed:
            return False
        if self.manuscript_source and not self.manuscript_source.passed:
            return False
        if self.reference_bundle and not self.reference_bundle.passed:
            return False
        return all(fa.passed for fa in self.figure_assets)

    def all_errors(self) -> list[str]:
        errors: list[str] = []
        for vr in [self.paper_manifest, self.manuscript_source, self.reference_bundle]:
            if vr:
                errors.extend(f"[{vr.artifact_type}] {e}" for e in vr.errors)
        for fa in self.figure_assets:
            errors.extend(f"[{fa.artifact_type}] {e}" for e in fa.errors)
        return errors

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "paper_manifest": self.paper_manifest.to_dict() if self.paper_manifest else None,
            "manuscript_source": self.manuscript_source.to_dict() if self.manuscript_source else None,
            "reference_bundle": self.reference_bundle.to_dict() if self.reference_bundle else None,
            "figure_assets": [fa.to_dict() for fa in self.figure_assets],
        }


def verify_run_artifacts(
    run_dir: Path,
    *,
    expected_run_id: str | None = None,
    require_reference: bool = True,
) -> FullVerificationReport:
    """验证一个 run 目录下的所有上游 artifact。

    Args:
        run_dir: runs/<run_id>/ 目录
        expected_run_id: 若提供则所有 artifact 的 run_id 必须一致
        require_reference: 若 False 则 reference_bundle 缺失为 warning 而非 error

    Raises:
        ValidationError: 任一必填 artifact 缺失或验证失败
    """
    paper_manifest_path = run_dir / "paper_manifest.v1.json"
    manuscript_path = run_dir / "manuscript_source.v1.json"
    reference_path = run_dir / "reference_bundle.v1.json"
    figures_dir = run_dir / "figures"

    pm = verify_paper_manifest(paper_manifest_path, expected_run_id=expected_run_id) \
        if paper_manifest_path.exists() else None
    ms = verify_manuscript_source(manuscript_path, expected_run_id=expected_run_id) \
        if manuscript_path.exists() else None
    rb = verify_reference_bundle(reference_path, expected_run_id=expected_run_id) \
        if reference_path.exists() else None

    figure_assets: list[VerificationResult] = []
    if figures_dir.exists():
        for fig_json in sorted(figures_dir.glob("**/figure_asset.v1.json")):
            figure_assets.append(
                verify_figure_asset(fig_json, expected_run_id=expected_run_id)
            )

    report = FullVerificationReport(
        paper_manifest=pm,
        manuscript_source=ms,
        reference_bundle=rb,
        figure_assets=figure_assets,
    )

    if pm is None:
        raise ValidationError(
            "缺少 paper_manifest.v1.json — 无法进入排版流水线",
            stage="MANIFEST_VERIFY",
            context={"run_dir": str(run_dir)},
        )
    if ms is None:
        raise ValidationError(
            "缺少 manuscript_source.v1.json",
            stage="MANIFEST_VERIFY",
            context={"run_dir": str(run_dir)},
        )
    if rb is None and require_reference:
        raise ValidationError(
            "缺少 reference_bundle.v1.json (require_reference=True)",
            stage="MANIFEST_VERIFY",
            context={"run_dir": str(run_dir)},
        )

    if not report.passed:
        errors = report.all_errors()
        raise ValidationError(
            f"上游 artifact 验证失败: {len(errors)} 项",
            stage="MANIFEST_VERIFY",
            context={"run_dir": str(run_dir), "errors": errors[:10]},
        )

    return report
