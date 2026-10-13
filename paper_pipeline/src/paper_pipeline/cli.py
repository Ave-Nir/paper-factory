"""
CLI 入口 —— 仅负责参数解析与流程触发，无业务逻辑

原则：
- CLI 层最薄，所有业务逻辑下沉至 Orchestrator
- 环境变量在 CLI 层统一注入，禁止在业务层硬编码
- 异常在 CLI 层统一捕获并格式化输出

支持两种输入模式：
  paper-pipeline <paper>                        # 裸文件输入（legacy，直接传入 .docx/.md/.tex 文件）
  paper-pipeline --manifest runs/<run_id>/     # 标准输入（0729 SPEC-X Step 5，验证上游 artifact 后排版）
"""
import argparse
import sys
from pathlib import Path

from .config.settings import get_settings
from .core.manifest_verifier import verify_run_artifacts
from .core.pipeline import PipelineOrchestrator
from .exceptions import PipelineError
from .gates.structured_logger import StructuredLogger


def main() -> int:
    """
    CLI 主入口

    :return: 退出码 (0=成功, 1=失败)
    """
    parser = argparse.ArgumentParser(
        description="论文处理完整流程：生图(4张) -> 插入 -> 排版PDF",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
环境变量（必需）:
  LLM_API_KEY         LLM API 密钥 (MIMO-V2.5-Pro)
  IMAGE_API_KEY       生图 API 密钥

环境变量（可选）:
  IMAGE_BASE_URL      生图端点 (默认: https://once.novai.su/v1)
  IMAGE_MODEL         生图模型 (默认: gpt-image-2)
  LLM_BASE_URL        LLM 端点 (默认: https://api.novai.su/v1)

示例:
  # 标准输入：从上游 artifact 目录排版
  paper-pipeline --manifest runs/run-0730-001/

  # 裸文件输入：直接传入论文文件
  paper-pipeline /path/to/paper.docx --work-dir /path/to/output
        """,
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="上游 artifact 目录路径 (runs/<run_id>/)，含 paper_manifest.v1.json 等。"
             "启用时跳过裸文件解析，直接从标准 artifact 链验证并排版。"
             "若目录中缺少 paper_manifest.v1.json 则阻断。",
    )
    parser.add_argument(
        "paper",
        type=Path,
        nargs="?",
        default=None,
        help="输入论文文件路径 (.docx / .md / .tex)。"
             "若同时指定 --manifest 则忽略此参数。",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help="工作目录。默认: 项目根目录下的 paper_pipeline/",
    )

    args = parser.parse_args()

    if args.manifest:
        run_dir = args.manifest.resolve()
        if not run_dir.is_dir():
            print(f"[INPUT ERROR] --manifest 指定的目录不存在: {run_dir}", file=sys.stderr)
            return 1
        print(f"[INPUT] --manifest 模式：验证 {run_dir} 中的上游 artifact")
        try:
            report = verify_run_artifacts(run_dir, require_reference=True)
            print(f"[VERIFY] paper_manifest.v1.json {'PASS' if report.paper_manifest.passed else 'FAIL'}")
            print(f"[VERIFY] manuscript_source.v1.json {'PASS' if report.manuscript_source.passed else 'FAIL'}")
            if report.reference_bundle:
                print(f"[VERIFY] reference_bundle.v1.json {'PASS' if report.reference_bundle.passed else 'FAIL'}")
            print(f"[VERIFY] figure_asset.v1.json × {len(report.figure_assets)}: "
                  f"{sum(1 for f in report.figure_assets if f.passed)} PASS, "
                  f"{sum(1 for f in report.figure_assets if not f.passed)} FAIL")
            if not report.passed:
                for err in report.all_errors()[:10]:
                    print(f"  [ERROR] {err}", file=sys.stderr)
                print(f"  ... 共 {len(report.all_errors())} 项错误", file=sys.stderr)
                return 1
            print(f"[VERIFY] 全部 artifact 验证通过 (run_id={report.paper_manifest.run_id or 'N/A'})")
        except PipelineError as e:
            print(f"[VERIFY ERROR] {e}", file=sys.stderr)
            return 1

        # 验证通过后 → 进入排版流水线
        manuscript_path = run_dir / "manuscript_source.v1.json"
        work_dir = args.work_dir or (run_dir / "typeset_output")
        work_dir.mkdir(parents=True, exist_ok=True)
        try:
            settings = get_settings(work_dir=work_dir)
        except PipelineError as e:
            print(f"[CONFIG ERROR] {e}", file=sys.stderr)
            return 1

        log_file = work_dir / "pipeline.log"
        logger = StructuredLogger("paper_pipeline", log_file=log_file)

        orchestrator = PipelineOrchestrator(settings, logger=logger)
        try:
            orchestrator.run(manuscript_path)
        except PipelineError as e:
            print(f"\n[PIPELINE ERROR] {e}", file=sys.stderr)
            return 1
        except Exception as e:
            print(f"\n[UNEXPECTED ERROR] {type(e).__name__}: {e}", file=sys.stderr)
            return 1
        return 0

    if args.paper is None:
        parser.print_help()
        print("\n[ERROR] 必须指定 paper 文件或 --manifest 参数", file=sys.stderr)
        return 1

    work_dir = args.work_dir or Path.cwd()
    try:
        settings = get_settings(work_dir=work_dir)
    except PipelineError as e:
        print(f"[CONFIG ERROR] {e}", file=sys.stderr)
        return 1

    log_file = work_dir / "pipeline.log"
    logger = StructuredLogger("paper_pipeline", log_file=log_file)

    orchestrator = PipelineOrchestrator(settings, logger=logger)
    try:
        orchestrator.run(args.paper)
    except PipelineError as e:
        print(f"\n[PIPELINE ERROR] {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"\n[UNEXPECTED ERROR] {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
