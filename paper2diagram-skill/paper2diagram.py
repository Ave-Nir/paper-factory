"""
论文转流程图主入口 —— S0-S5两轮候选流程

借鉴 paper-framework-figure-studio-pro 的分阶段人机协作工作流：
- S0: 论文基础分析（提取模块、流程、术语）
- S1: 策略设计（诊断图类型、生成S2提示词包）
- S2: 草图探索（生成C01-C08共8个候选图）
- S3: 方向选择（人工审阅，形成偏好记录）
- S4: 候选简报（基于偏好生成S5正式提示词包）
- S5: 正式候选（生成F01-F06共6个正式候选图）

同时保留旧的单次生成模式（--quick）

示例：
    # 完整S0-S5流程
    python paper2diagram.py examples/论文.docx

    # 快速单次生成
    python paper2diagram.py examples/论文.docx --quick --palette ocean_breeze

    # 从S2断点继续
    python paper2diagram.py --resume examples/论文.docx

    # 指定R1偏好
    python paper2diagram.py examples/论文.docx --prefer C01,C04,C07
"""
import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from paper2diagram import PaperAnalyzer, PromptGenerator, ImageGenerator
from paper2diagram.llm.color_palettes import list_palettes
from paper2diagram.checkpoint import CheckpointManager
from paper2diagram.preference_carryover import PreferenceCarryover

# ========== 配置常量 ==========
MIN_IMAGE_FILE_SIZE = 5000       # 跳过已生成图片的最小文件大小阈值（字节）
IMAGE_GEN_INTERVAL_SEC = 2       # 图片生成间隔（秒，避免API限流）


def main():
    palettes = list_palettes()

    parser = argparse.ArgumentParser(
        description="论文转流程图 —— S0-S5两轮候选流程 + 结构化Prompt契约",
    )
    parser.add_argument("paper_file", type=str, nargs="?", default=None,
                        help="论文文件路径 (.docx 或 .txt)")
    parser.add_argument("--quick", action="store_true",
                        help="快速单次生成模式（跳过两轮候选）")
    parser.add_argument("--template", type=str, default=None,
                        help="模板类型（quick模式）：horizontal_3frame, vertical_3stage等")
    parser.add_argument("--palette", type=str, default=None,
                        help="配色方案")
    parser.add_argument("--resume", action="store_true",
                        help="从断点继续执行")
    parser.add_argument("--stage", type=str, default=None,
                        choices=["s0", "s1", "s2", "s3", "s4", "s5", "all"],
                        help="只执行指定阶段")
    parser.add_argument("--s2-count", type=int, default=4,
                        help="R1探索候选数量（默认4个，最多12个）")
    parser.add_argument("--s5-count", type=int, default=4,
                        help="R2正式候选数量（默认4个，最多8个）")
    parser.add_argument("--prefer", type=str, default=None,
                        help="S3偏好候选ID（如 C01,C04）")
    parser.add_argument("--output", type=str, default=None,
                        help="输出目录")
    parser.add_argument("--api-key", type=str, default=None)
    parser.add_argument("--llm-api-key", type=str, default=None)
    parser.add_argument("--llm-base-url", type=str, default="https://api.novai.su/v1",
                        help="LLM API端点（MIMO官方 https://api.novai.su/v1）")
    parser.add_argument("--llm-model", type=str, default="MIMO-V2.5-Pro",
                        help="LLM模型名称（统一使用 MIMO-V2.5-Pro）")
    parser.add_argument("--no-skip", action="store_true",
                        help="重新生成已存在的图片")
    parser.add_argument("--timeout", type=int, default=300,
                        help="单次请求超时时间（秒）")
    parser.add_argument("--max-retries", type=int, default=3,
                        help="最大重试次数")
    parser.add_argument("--total-timeout", type=int, default=900,
                        help="总超时时间（秒，包括所有重试）")
    parser.add_argument("--model", type=str, default="gpt-image-2",
                        help="生图模型名称（如 gpt-image-2）")
    parser.add_argument("--base-url", type=str, default="https://once.novai.su/v1",
                        help="生图API端点（novai.su）")

    args = parser.parse_args()

    # ========== 快速单次模式 ==========
    if args.quick:
        run_quick_mode(args, palettes)
        return

    # ========== S0-S5 完整流程 ==========
    if not args.paper_file and not args.resume:
        print("错误: 需要指定论文文件路径")
        parser.print_help()
        sys.exit(1)

    paper_file = Path(args.paper_file) if args.paper_file else None
    if paper_file and not paper_file.exists():
        print(f"错误: 找不到文件 {paper_file}")
        sys.exit(1)

    # 项目目录
    project_id = paper_file.stem if paper_file else "resumed_project"
    if args.resume and not args.output:
        # resume模式：自动查找最近的runs目录
        runs_dir = Path("runs")
        if runs_dir.exists():
            run_dirs = sorted(runs_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)
            if run_dirs:
                project_root = run_dirs[0]
            else:
                project_root = Path(f"runs/{project_id}")
        else:
            project_root = Path(f"runs/{project_id}")
    else:
        project_root = Path(args.output or f"runs/{project_id}")
    project_root.mkdir(parents=True, exist_ok=True)

    checkpoint = CheckpointManager(str(project_root))

    print("=" * 70)
    print("  论文转流程图 —— S0-S5两轮候选流程")
    print("=" * 70)
    print(f"  项目目录: {project_root}")

    # 确定执行哪些阶段
    if args.resume:
        resume_stage = checkpoint.get_resume_stage()
        if resume_stage is None:
            print("  所有阶段已完成！")
            return
        stages_to_run = [resume_stage] + \
            ["s1", "s2", "s3", "s4", "s5"][["s0", "s1", "s2", "s3", "s4", "s5"].index(resume_stage):]
        print(f"  断点续跑: 从 {resume_stage} 开始")
    elif args.stage:
        stages_to_run = [args.stage] if args.stage != "all" else \
            ["s0", "s1", "s2", "s3", "s4", "s5"]
    else:
        stages_to_run = ["s0", "s1", "s2", "s3", "s4", "s5"]

    # 初始化组件
    analyzer = PaperAnalyzer(llm_api_key=args.llm_api_key, base_url=args.llm_base_url, model=args.llm_model)
    prompt_gen = PromptGenerator()
    image_gen = ImageGenerator(api_key=args.api_key, base_url=args.base_url, model=args.model, timeout=args.timeout, max_retries=args.max_retries, total_timeout=args.total_timeout)
    pref_carryover = PreferenceCarryover()

    paper_analysis = None

    for stage in stages_to_run:
        if stage == "s0":
            paper_analysis = run_s0(paper_file, analyzer, checkpoint)
        elif stage == "s1":
            if paper_analysis is None:
                paper_analysis = checkpoint.load_state("s0")
            if paper_analysis is None:
                paper_analysis = run_s0(paper_file, analyzer, checkpoint)
            run_s1(paper_analysis, prompt_gen, checkpoint, args.s2_count)
        elif stage == "s2":
            run_s2(image_gen, checkpoint, skip_existing=not args.no_skip)
        elif stage == "s3":
            run_s3(checkpoint, pref_carryover, args.prefer)
        elif stage == "s4":
            if paper_analysis is None:
                paper_analysis = checkpoint.load_state("s0")
            run_s4(paper_analysis, prompt_gen, checkpoint, pref_carryover, args.s5_count)
        elif stage == "s5":
            run_s5(image_gen, checkpoint, skip_existing=not args.no_skip)

    # 最终摘要
    if "s5" in stages_to_run or (args.stage == "all"):
        summary_path = checkpoint.write_pipeline_summary(
            args.s2_count, args.s5_count,
            pref_carryover.preferences.get("preferred_ids", [])
        )
        print(f"\n  摘要: {summary_path}")

    print(f"\n{'=' * 70}")
    print(f"  流程完成！")
    print(f"{'=' * 70}")


# ========== S0: 论文基础分析 ==========

def run_s0(paper_file: Path, analyzer: PaperAnalyzer, checkpoint: CheckpointManager) -> dict:
    print(f"\n[S0] 论文基础分析")
    print(f"  解析: {paper_file.name}")

    content = analyzer.extract_text(str(paper_file))

    print(f"  提取了 {len(content)} 字符")
    print(f"  LLM分析中...")

    analysis = analyzer.analyze_paper(content)

    # 保存报告
    report_dir = checkpoint.output_dir / "S0-paper-foundation"
    report_dir.mkdir(parents=True, exist_ok=True)
    (report_dir / "raw-text.txt").write_text(content, encoding="utf-8")
    (report_dir / "paper-foundation-report.md").write_text(
        f"# 论文基础报告\n\n**标题:** {analysis.get('title', '')}\n\n"
        f"## 阶段\n" + "\n".join(
            f"- {s.get('name', '')}: {s.get('description', '')}"
            for s in analysis.get("stages", [])
        ),
        encoding="utf-8"
    )

    checkpoint.save_state("s0", analysis)
    print(f"  → 分析完成，提取了 {len(analysis.get('stages', []))} 个阶段")
    return analysis


# ========== S1: 策略设计 ==========

def run_s1(paper_analysis: dict, prompt_gen: PromptGenerator,
           checkpoint: CheckpointManager, s2_count: int):
    print(f"\n[S1] 策略设计 —— 生成 {s2_count} 个R1探索候选Prompt")

    candidates = prompt_gen.generate_s1_prompts(paper_analysis, s2_count)
    index_path = checkpoint.save_prompt_index("S2-sketch-explore", candidates)

    # 保存S1简报
    brief_dir = checkpoint.output_dir / "S1-figure-strategy"
    brief_dir.mkdir(parents=True, exist_ok=True)
    brief = "# S1 策略简报\n\n## 候选方案\n\n"
    for c in candidates:
        brief += f"### {c['id']}\n- **概念:** {c['identity']}\n- **布局:** {c['layout']}\n- **配色:** {c['color']}\n\n"
    (brief_dir / "figure-strategy-brief.md").write_text(brief, encoding="utf-8")

    checkpoint.save_state("s1", {
        "stage": "S1-FIGURE-STRATEGY",
        "candidate_count": len(candidates),
        "candidate_ids": [c["id"] for c in candidates],
    })
    print(f"  → {len(candidates)} 个Prompt已保存: {index_path}")


# ========== S2: 草图探索 ==========

def run_s2(image_gen: ImageGenerator, checkpoint: CheckpointManager,
           skip_existing: bool = True):
    print(f"\n[S2] 草图探索 —— 生成R1候选图片")

    index = checkpoint.load_prompt_index("S2-sketch-explore")
    if not index:
        print("  错误: 找不到S2 prompt-index，请先执行S1")
        return

    candidates = index["candidates"]
    results = []

    for i, c in enumerate(candidates, 1):
        cid = c["candidate_id"]
        target = Path(c["target_image_path"])

        if skip_existing and target.exists() and target.stat().st_size > MIN_IMAGE_FILE_SIZE:
            print(f"  [{i}/{len(candidates)}] {cid}: 跳过（已存在）")
            results.append({**c, "generated": True, "image_path": str(target)})
            continue

        prompt = Path(c["prompt_path"]).read_text(encoding="utf-8")
        print(f"  [{i}/{len(candidates)}] {cid}: 生成中...")

        try:
            saved = image_gen.generate_image(prompt, str(target))
            results.append({**c, "generated": True, "image_path": saved})
        except Exception as e:
            print(f"  [{i}/{len(candidates)}] {cid}: 生成失败 - {type(e).__name__}: {e}")
            results.append({**c, "generated": False, "image_path": None, "error": str(e)})

        time.sleep(IMAGE_GEN_INTERVAL_SEC)

    checkpoint.save_generation_summary("S2-sketch-explore", results)
    successful = sum(1 for r in results if r.get("generated"))
    print(f"  → 成功: {successful}/{len(results)}")


# ========== S3: 方向选择 ==========

def run_s3(checkpoint: CheckpointManager, pref_carryover: PreferenceCarryover,
           user_prefer: str = None):
    print(f"\n[S3] 方向选择")

    r1_results = checkpoint.load_generation_summary("S2-sketch-explore")
    if not r1_results:
        print("  错误: 找不到S2结果，请先执行S2")
        return

    user_prefer_ids = []
    if user_prefer:
        user_prefer_ids = [p.strip() for p in user_prefer.split(",") if p.strip()]

    s3_state = pref_carryover.build_s3_decision(r1_results, user_prefer_ids)

    # 保存S3报告
    brief_dir = checkpoint.output_dir / "S3-direction-select"
    brief_dir.mkdir(parents=True, exist_ok=True)
    brief = f"# S3 方向选择\n\n## 偏好候选\n"
    for pid in s3_state["preferred_ids"]:
        brief += f"- {pid}\n"
    brief += f"\n## 偏好特征\n- 布局: {', '.join(s3_state.get('preferred_layouts', []))}\n"
    brief += f"- 配色: {', '.join(s3_state.get('preferred_colors', []))}\n"
    (brief_dir / "s3-direction-decision.md").write_text(brief, encoding="utf-8")

    checkpoint.save_state("s3", s3_state)
    print(f"  → 偏好候选: {s3_state['preferred_ids']}")


# ========== S4: 候选简报 ==========

def run_s4(paper_analysis: dict, prompt_gen: PromptGenerator,
           checkpoint: CheckpointManager, pref_carryover: PreferenceCarryover,
           s5_count: int):
    print(f"\n[S4] 候选简报 —— 生成R2正式候选Prompt")

    s3_state = checkpoint.load_state("s3")
    if not s3_state:
        print("  错误: 找不到S3状态，请先执行S3")
        return

    pref_carryover.from_s3(s3_state)
    preferred_ids = s3_state.get("preferred_ids", [])

    candidates = prompt_gen.generate_s4_prompts(paper_analysis, preferred_ids, s5_count)
    index_path = checkpoint.save_prompt_index("S5-candidate-image", candidates)

    # 保存S4简报
    brief_dir = checkpoint.output_dir / "S4-candidate-brief"
    brief_dir.mkdir(parents=True, exist_ok=True)
    carryover_text = pref_carryover.build_carryover_emphasis()
    brief = f"# S4 候选简报\n\n## 承接偏好\n{carryover_text}\n\n## 正式候选\n"
    for c in candidates:
        brief += f"### {c['id']}\n- **概念:** {c['identity']}\n\n"
    (brief_dir / "formal-candidate-brief.md").write_text(brief, encoding="utf-8")

    checkpoint.save_state("s4", {
        "stage": "S4-CANDIDATE-BRIEF",
        "candidate_count": len(candidates),
        "candidate_ids": [c["id"] for c in candidates],
        "carryover": carryover_text,
    })
    print(f"  → {len(candidates)} 个正式Prompt已保存: {index_path}")


# ========== S5: 正式候选 ==========

def run_s5(image_gen: ImageGenerator, checkpoint: CheckpointManager,
           skip_existing: bool = True):
    print(f"\n[S5] 正式候选 —— 生成R2出版级图片")

    index = checkpoint.load_prompt_index("S5-candidate-image")
    if not index:
        print("  错误: 找不到S5 prompt-index，请先执行S4")
        return

    candidates = index["candidates"]
    results = []

    for i, c in enumerate(candidates, 1):
        cid = c["candidate_id"]
        target = Path(c["target_image_path"])

        if skip_existing and target.exists() and target.stat().st_size > MIN_IMAGE_FILE_SIZE:
            print(f"  [{i}/{len(candidates)}] {cid}: 跳过（已存在）")
            results.append({**c, "generated": True, "image_path": str(target)})
            continue

        prompt = Path(c["prompt_path"]).read_text(encoding="utf-8")
        print(f"  [{i}/{len(candidates)}] {cid}: 生成中...")

        try:
            saved = image_gen.generate_image(prompt, str(target))
            results.append({**c, "generated": True, "image_path": saved})
        except Exception as e:
            print(f"  [{i}/{len(candidates)}] {cid}: 生成失败 - {type(e).__name__}: {e}")
            results.append({**c, "generated": False, "image_path": None, "error": str(e)})

        time.sleep(IMAGE_GEN_INTERVAL_SEC)

    checkpoint.save_generation_summary("S5-candidate-image", results)
    successful = sum(1 for r in results if r.get("generated"))
    print(f"  → 成功: {successful}/{len(results)}")
    print(f"  S5是终止阶段。请手动审阅候选图片。")


# ========== 快速模式 ==========

def run_quick_mode(args, palettes):
    """旧的快速单次生成模式"""
    paper_file = Path(args.paper_file)
    if not paper_file.exists():
        print(f"错误: 找不到文件 {paper_file}")
        sys.exit(1)

    print("=" * 70)
    print("  论文转流程图 —— 快速模式")
    print("=" * 70)

    # 1. 提取论文内容并分析
    print(f"\n[1/3] 解析论文文件: {paper_file.name}")
    analyzer = PaperAnalyzer(llm_api_key=args.llm_api_key, base_url=args.llm_base_url, model=args.llm_model)

    content = analyzer.extract_text(str(paper_file))
    print(f"  → 提取了 {len(content)} 字符")
    print(f"  LLM分析中...")
    paper_analysis = analyzer.analyze_paper(content)

    # 2. 生成提示词
    print(f"\n[2/3] 生成结构化提示词...")
    prompt_gen = PromptGenerator()
    drawing_prompt = prompt_gen.generate_prompt(paper_analysis, args.template, args.palette)

    prompt_file = Path(f"output/{paper_file.stem}_prompt.txt")
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    prompt_file.write_text(drawing_prompt, encoding="utf-8")
    print(f"  → 提示词已保存: {prompt_file}")

    # 3. 生成图片
    print(f"\n[3/3] 调用{args.model}生成图片...")
    image_gen = ImageGenerator(api_key=args.api_key, base_url=args.base_url, model=args.model, timeout=args.timeout, max_retries=args.max_retries, total_timeout=args.total_timeout)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = args.output or f"output/{paper_file.stem}_{timestamp}.png"
    image_path = image_gen.generate_image(drawing_prompt, output_path)
    print(f"  → 图片已保存: {image_path}")

    print(f"\n{'=' * 70}")
    print(f"  生成完成！")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
