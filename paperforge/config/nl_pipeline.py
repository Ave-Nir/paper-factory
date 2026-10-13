"""
NL Pipeline —— 独立 CLI

工作流：
1. 从自然语言文本/文件生成 PaperSpec JSON（调用兼容 OpenAI 的 LLM）
2. 可选：从 JSON 还原并生成 PDF/Word（调用 process_lunwen_v4.py 的核心函数）

用法：
    # 仅生成 PaperSpec JSON
    python config/nl_pipeline.py intake --text "..." -o paper_spec.json
    python config/nl_pipeline.py intake --input description.txt -o paper_spec.json

    # 生成 JSON 后立即排版
    python config/nl_pipeline.py intake --text "..." --render -o build/

    # 从已保存的 JSON 排版
    python config/nl_pipeline.py render paper_spec.json -o build/

环境变量：
    LLM_API_KEY          LLM API 密钥（必填）
    LLM_BASE_URL         默认 https://api.novai.su/v1
    LLM_MODEL            默认 MIMO-V2.5-Pro
    OPENAI_API_KEY       备用
    LLM_PROVIDER         强制指定 deepseek / openai

安全说明：
    - 任何命令行参数都不接受 API key
    - 密钥只能通过环境变量传入
    - 切勿将密钥写入代码或配置文件
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Optional


# ============================================================
# 路径注入：让独立 CLI 也能 import core
# ============================================================
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ============================================================
# 子命令 1: intake
# ============================================================

def cmd_intake(args) -> int:
    """从自然语言文本生成 PaperSpec JSON。"""
    from core.llm_factory import create_llm_from_env, describe_config, LLMConfigError
    from core.nl_intake import NLIntake, IntakeParseError, IntakeValidationError

    # 读取输入
    if args.text:
        user_text = args.text
    elif args.input:
        in_path = Path(args.input)
        if not in_path.exists():
            print(f"[错误] 输入文件不存在: {in_path}", file=sys.stderr)
            return 2
        user_text = in_path.read_text(encoding="utf-8")
    else:
        print("[错误] 必须提供 --text 或 --input", file=sys.stderr)
        return 2

    # 加载 LLM
    try:
        llm = create_llm_from_env(
            provider=args.provider,
            model=args.model,
            base_url=args.base_url,
        )
    except LLMConfigError as e:
        print(f"[错误] {e}", file=sys.stderr)
        return 3

    cfg = describe_config()
    print("=" * 70)
    print("PaperForge NL Pipeline — 自然语言 → PaperSpec JSON")
    print("=" * 70)
    print(f"  Provider:  {cfg['provider']}")
    print(f"  Model:     {cfg['model']}")
    print(f"  Base URL:  {cfg['base_url']}")
    print(f"  Has Key:   {'是' if cfg['has_api_key'] else '否'}")
    print(f"  文本长度:  {len(user_text)} 字符")
    print()

    # 调用 LLM
    intake = NLIntake(llm)
    try:
        paper_spec, ref_db, section_data_map = intake.process(
            user_text,
            venue=args.venue,
            field=args.field,
        )
    except (IntakeParseError, IntakeValidationError) as e:
        print(f"[错误] LLM 输出解析/校验失败:\n{e}", file=sys.stderr)
        return 4
    except Exception as e:
        print(f"[错误] LLM 调用失败: {e}", file=sys.stderr)
        return 5

    # 序列化为 JSON
    from core.nl_to_document import serialize_intake_output
    payload = serialize_intake_output(paper_spec, ref_db, section_data_map)

    print("  ✓ PaperSpec 提取成功")
    print(f"    标题:  {paper_spec.get('title', '(无)')}")
    print(f"    Venue: {paper_spec.get('venue', '(无)')}")
    print(f"    引用:  {len(ref_db)} 条")
    print(f"    章节:  {list(section_data_map.keys())}")

    # 写出
    out_path = Path(args.output) if args.output else Path("paper_spec.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  ✓ 保存: {out_path}")

    # 可选：立即排版
    if args.render:
        return cmd_render_from_payload(payload, args)

    return 0


# ============================================================
# 子命令 2: render
# ============================================================

def cmd_render(args) -> int:
    """从已保存的 JSON 文件排版成 PDF/Word。"""
    in_path = Path(args.input)
    if not in_path.exists():
        print(f"[错误] 输入文件不存在: {in_path}", file=sys.stderr)
        return 2
    payload = json.loads(in_path.read_text(encoding="utf-8"))
    return cmd_render_from_payload(payload, args)


def cmd_render_from_payload(payload: dict, args) -> int:
    """公共：把 PaperSpec payload 转 DocumentContent 并跑排版。"""
    from core.nl_to_document import (
        deserialize_intake_output,
        build_document_content,
    )

    paper_spec, ref_db, section_data_map = deserialize_intake_output(payload)
    doc = build_document_content(paper_spec, ref_db, section_data_map)

    # 解析模板
    template = args.template
    if template == "auto":
        from core.template_detector import TemplateDetector
        detector = TemplateDetector()
        detection = detector.detect(doc, hint=None)
        template = detection.template
        print(f"  自动检测模板: {template} (置信度 {detection.confidence:.0%})")

    # 调用主流程的 render_enhanced_latex
    out_dir = Path(args.output) if args.output else Path("build")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "images").mkdir(exist_ok=True)

    print(f"  模板: {template}")
    print(f"  输出: {out_dir}")

    # 复用 process_lunwen_v4 的 render_enhanced_latex + 编译逻辑
    try:
        from config.process_lunwen_v4 import (
            render_enhanced_latex,
            PRESET_FORMATS,
        )
        from core.formatting import PRESET_FORMATS as FORMATS
    except ImportError as e:
        print(f"[错误] 无法导入主流程模块: {e}", file=sys.stderr)
        return 6

    format_spec = FORMATS.get(template)
    tex = render_enhanced_latex(doc, str(out_dir), format_spec=format_spec, template=template)
    tex_path = out_dir / "paper.tex"
    tex_path.write_text(tex, encoding="utf-8")
    print(f"  ✓ LaTeX: {tex_path}")

    # 编译 PDF
    if not args.no_pdf:
        from core.utils.miktex import MikTeXResolver
        import subprocess
        import re

        resolver = MikTeXResolver(custom_path=getattr(args, "miktex", None))
        config = resolver.resolve("xelatex")
        env = resolver.get_env(config)
        if not config.is_found and not config.found_in_path:
            print("  [错误] 找不到 xelatex，跳过 PDF 编译", file=sys.stderr)
        else:
            for i in range(1, 4):
                r = subprocess.run(
                    [config.engine_path, "-interaction=nonstopmode", "paper.tex"],
                    cwd=str(out_dir),
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
                ok = "Output written" in r.stdout
                err_lines = [ln.strip() for ln in r.stdout.splitlines() if ln.startswith("!")]
                print(f"  编译 #{i}: {'OK' if ok else '失败'} {len(err_lines)} errors")
                if r.returncode != 0 and not ok:
                    for ln in err_lines[:5]:
                        print(f"    ! {ln}")
                if ok and "Output written on paper.pdf" in r.stdout:
                    m = re.search(r"Output written on paper\.pdf \((\d+) pages", r.stdout)
                    if m:
                        print(f"  ✓ PDF: {out_dir / 'paper.pdf'} ({m.group(1)} 页)")
                    break

    # 生成 Word
    if not args.no_word:
        try:
            from core.word_builder import WordDocumentBuilder
            wb = WordDocumentBuilder(format_spec=format_spec)
            wb.build_from_blocks(doc, str(out_dir / "paper.docx"))
            print(f"  ✓ Word: {out_dir / 'paper.docx'}")
        except Exception as e:
            print(f"  [警告] Word 生成失败: {e}", file=sys.stderr)

    return 0


# ============================================================
# 参数解析
# ============================================================

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="nl_pipeline",
        description="PaperForge NL Pipeline — 自然语言→结构化→排版",
    )
    sub = p.add_subparsers(dest="command", required=True)

    # --- intake ---
    p_intake = sub.add_parser("intake", help="从自然语言生成 PaperSpec JSON")
    p_intake.add_argument("--text", help="直接传入自然语言文本")
    p_intake.add_argument("--input", help="从 .txt/.md 文件读取")
    p_intake.add_argument("-o", "--output", help="输出 JSON 路径（默认 paper_spec.json）")
    p_intake.add_argument("--venue", help="目标 venue（覆盖 LLM 推断）")
    p_intake.add_argument("--field", help="目标 field（覆盖 LLM 推断）")
    p_intake.add_argument("--provider", help="强制 provider: deepseek / openai")
    p_intake.add_argument("--model", help="强制模型名")
    p_intake.add_argument("--base-url", help="强制 base url")
    p_intake.add_argument(
        "--render", action="store_true",
        help="intake 完成后立即排版（等同 render 子命令）",
    )
    p_intake.add_argument("-t", "--template", default="auto", help="模板名（默认 auto）")
    p_intake.add_argument("--no-pdf", action="store_true", help="跳过 PDF 编译")
    p_intake.add_argument("--no-word", action="store_true", help="跳过 Word 生成")
    p_intake.add_argument("--miktex", help="MiKTeX bin 目录")
    p_intake.set_defaults(func=cmd_intake)

    # --- render ---
    p_render = sub.add_parser("render", help="从 PaperSpec JSON 排版")
    p_render.add_argument("input", help="paper_spec.json 路径")
    p_render.add_argument("-o", "--output", help="输出目录（默认 build）")
    p_render.add_argument("-t", "--template", default="auto", help="模板名（默认 auto）")
    p_render.add_argument("--no-pdf", action="store_true", help="跳过 PDF 编译")
    p_render.add_argument("--no-word", action="store_true", help="跳过 Word 生成")
    p_render.add_argument("--miktex", help="MiKTeX bin 目录")
    p_render.set_defaults(func=cmd_render)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
