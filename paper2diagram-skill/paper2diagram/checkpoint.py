"""
状态管理与断点续跑模块 —— 借鉴 paper-framework-figure-studio-pro 的 checkpoint 机制
每个阶段完成后保存状态，支持从任意阶段断点继续
"""
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any


def _safe_load_json(path: Path) -> Optional[Any]:
    """安全读取JSON文件，损坏时返回None并输出上下文"""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print(f"[WARN] JSON文件解析失败: {path} - {type(e).__name__}: {e}")
        return None


class CheckpointManager:
    """管理S0-S5各阶段的状态和断点续跑"""

    def __init__(self, project_root: str):
        self.project_root = Path(project_root)
        self.state_dir = self.project_root / "state"
        self.output_dir = self.project_root / "outputs"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    # ========== 状态保存与加载 ==========

    def save_state(self, stage: str, state: Dict) -> str:
        """保存阶段状态"""
        state_path = self.state_dir / f"{stage}-state.json"
        state["_saved_at"] = datetime.now().isoformat()
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(state_path)

    def load_state(self, stage: str) -> Optional[Dict]:
        """加载阶段状态"""
        state_path = self.state_dir / f"{stage}-state.json"
        return _safe_load_json(state_path)

    def has_state(self, stage: str) -> bool:
        """检查某阶段是否有状态"""
        return (self.state_dir / f"{stage}-state.json").exists()

    def get_completed_stages(self) -> List[str]:
        """获取已完成的阶段列表"""
        stages = []
        for s in ["s0", "s1", "s2", "s3", "s4", "s5"]:
            if self.has_state(s):
                stages.append(s)
        return stages

    def get_resume_stage(self) -> Optional[str]:
        """获取下一个应执行的阶段"""
        completed = self.get_completed_stages()
        all_stages = ["s0", "s1", "s2", "s3", "s4", "s5"]
        for s in all_stages:
            if s not in completed:
                return s
        return None  # 全部完成

    # ========== Prompt索引管理 ==========

    def save_prompt_index(self, stage: str, candidates: List[Dict]) -> str:
        """保存Prompt索引和候选文件"""
        stage_output = self.output_dir / stage
        stage_output.mkdir(parents=True, exist_ok=True)

        rows = []
        for c in candidates:
            cid = c["id"]
            cand_dir = stage_output / "candidates" / cid
            cand_dir.mkdir(parents=True, exist_ok=True)

            prompt_path = cand_dir / "prompt-v01.md"
            prompt_path.write_text(c["prompt"], encoding="utf-8")

            rows.append({
                "candidate_id": cid,
                "identity": c.get("identity", ""),
                "prompt_path": str(prompt_path),
                "target_image_path": str(cand_dir / "image-v01.png"),
                "layout": c.get("layout", ""),
                "color": c.get("color", ""),
                "style": c.get("style", ""),
            })

        index = {
            "schema_version": 2,
            "stage": stage,
            "prompt_mode": "file_reference_handoff",
            "candidate_ids": [r["candidate_id"] for r in rows],
            "candidates": rows,
        }

        index_path = stage_output / "prompt-index.json"
        index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(index_path)

    def load_prompt_index(self, stage: str) -> Optional[Dict]:
        """加载Prompt索引"""
        index_path = self.output_dir / stage / "prompt-index.json"
        return _safe_load_json(index_path)

    # ========== 生成结果管理 ==========

    def save_generation_summary(self, stage: str, results: List[Dict]) -> str:
        """保存图片生成结果摘要"""
        summary_path = self.output_dir / stage / "generation-summary.json"
        summary_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(summary_path)

    def load_generation_summary(self, stage: str) -> Optional[List[Dict]]:
        """加载图片生成结果摘要"""
        summary_path = self.output_dir / stage / "generation-summary.json"
        return _safe_load_json(summary_path)

    # ========== 报告生成 ==========

    def write_pipeline_summary(self, s2_count: int, s5_count: int,
                               preferred_ids: List[str]) -> str:
        """生成最终Pipeline摘要"""
        s0_state = self.load_state("s0") or {}
        s3_state = self.load_state("s3") or {}

        summary = f"""# Pipeline 摘要

## S0 论文基础
- 论文标题: {s0_state.get("title", "(未知)")}
- 输出: outputs/S0-paper-foundation/paper-foundation-report.md

## S1 策略设计
- {s2_count}个第一轮候选Prompt已准备
- 输出: outputs/S1-figure-strategy/

## S2 草图探索
- 图片: outputs/S2-sketch-explore/candidates/C*/image-v01.png

## S3 方向选择
- 偏好ID: {', '.join(s3_state.get("preferred_ids", []))}
- 输出: outputs/S3-direction-select/

## S4 候选简报
- {s5_count}个正式候选Prompt已准备
- 输出: outputs/S4-candidate-brief/

## S5 最终候选
- 图片: outputs/S5-candidate-image/candidates/F*/image-v01.png

S5是终止阶段。请手动审阅生成的候选图片，
选择最佳的进行后续编辑（PowerPoint/Inkscape/Figma）。
"""
        summary_path = self.project_root / "PIPELINE-SUMMARY.md"
        summary_path.write_text(summary, encoding="utf-8")
        return str(summary_path)

    # ========== 重置 ==========

    def reset(self, keep_s0: bool = False):
        """重置所有状态（可选保留S0）"""
        stages_to_remove = ["s1", "s2", "s3", "s4", "s5"]
        if not keep_s0:
            stages_to_remove.insert(0, "s0")

        for stage in stages_to_remove:
            state_file = self.state_dir / f"{stage}-state.json"
            if state_file.exists():
                state_file.unlink()

            stage_output = self.output_dir / stage
            if stage_output.exists():
                shutil.rmtree(stage_output)
