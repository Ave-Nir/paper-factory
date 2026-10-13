"""
偏好承接模块 —— 借鉴 paper-framework-figure-studio-pro 的偏好传递机制
将S3用户偏好自动承接为S4/S5的local-essence refinement
"""
import json
from typing import Dict, List, Optional
from pathlib import Path


class PreferenceCarryover:
    """管理S3→S4/S5的偏好承接"""

    # 偏好类型映射
    PREFERENCE_TYPES = {
        "layout": "布局偏好",
        "color": "配色偏好",
        "style": "风格偏好",
        "identity": "概念偏好",
    }

    def __init__(self):
        self.preferences: Dict = {}
        self.issue_ledger: List[str] = []

    def from_s3(self, s3_state: Dict) -> "PreferenceCarryover":
        """从S3状态加载偏好"""
        self.preferences = {
            "preferred_ids": s3_state.get("preferred_ids", []),
            "preferred_layouts": s3_state.get("preferred_layouts", []),
            "preferred_colors": s3_state.get("preferred_colors", []),
            "preferred_styles": s3_state.get("preferred_styles", []),
            "user_notes": s3_state.get("user_notes", ""),
        }
        self.issue_ledger = s3_state.get("issue_ledger", [])
        return self

    def extract_from_candidates(self, candidates: List[Dict],
                                preferred_ids: List[str]) -> Dict:
        """
        从R1候选中提取偏好候选的布局/配色/风格特征

        :param candidates: R1所有候选的元数据
        :param preferred_ids: 用户选择的偏好候选ID
        :return: 提取的偏好特征
        """
        preferred_features = {
            "layouts": [],
            "colors": [],
            "styles": [],
            "identities": [],
        }

        for c in candidates:
            if c.get("candidate_id", c.get("id", "")) in preferred_ids:
                preferred_features["layouts"].append(c.get("layout", ""))
                preferred_features["colors"].append(c.get("color", ""))
                preferred_features["styles"].append(c.get("style", ""))
                preferred_features["identities"].append(c.get("identity", ""))

        self.preferences.update(preferred_features)
        return preferred_features

    def build_carryover_emphasis(self) -> str:
        """构建偏好承接强调文本，注入S4的prompt"""
        parts = []

        if self.preferences.get("preferred_ids"):
            ids = ", ".join(self.preferences["preferred_ids"])
            parts.append(f"承接S3探索偏好: {ids}")

        if self.preferences.get("identities"):
            # 取第一个偏好候选的identity作为方向
            identity = self.preferences["identities"][0]
            parts.append(f"偏好方向: {identity}")

        if self.preferences.get("layouts"):
            layout = self.preferences["layouts"][0]
            parts.append(f"布局倾向: {layout}")

        if self.preferences.get("colors"):
            color = self.preferences["colors"][0]
            parts.append(f"配色倾向: {color}")

        if self.preferences.get("user_notes"):
            parts.append(f"用户备注: {self.preferences['user_notes']}")

        if self.issue_ledger:
            parts.append(f"已知问题: {'; '.join(self.issue_ledger)}")

        if not parts:
            return "无特定偏好，使用默认正式风格"

        return " | ".join(parts)

    def build_s3_decision(self, r1_candidates: List[Dict],
                          user_preferred_ids: List[str] = None,
                          user_notes: str = "") -> Dict:
        """
        构建S3方向选择决策

        :param r1_candidates: R1生成的候选结果
        :param user_preferred_ids: 用户手动指定的偏好ID
        :param user_notes: 用户备注
        :return: S3状态
        """
        generated = [c for c in r1_candidates if c.get("generated") and c.get("image_path")]

        if not user_preferred_ids and generated:
            # 用户未指定偏好时，自动选取首/中/尾3个候选作为默认偏好
            # 注意：此为自动行为，建议用户通过 --prefer 参数手动指定偏好以获得更精准的承接
            print("  [INFO] 用户未指定偏好，自动选取首/中/尾候选作为默认偏好")
            n = len(generated)
            picks = [
                generated[0].get("candidate_id", generated[0].get("id", "")),
                generated[n // 2].get("candidate_id", generated[n // 2].get("id", "")),
                generated[-1].get("candidate_id", generated[-1].get("id", "")),
            ]
            user_preferred_ids = list(dict.fromkeys(picks))[:3]

        # 提取偏好特征
        self.extract_from_candidates(r1_candidates, user_preferred_ids)

        if user_notes:
            self.preferences["user_notes"] = user_notes

        return {
            "stage": "S3-DIRECTION-SELECT",
            "total_r1_candidates": len(generated),
            "preferred_ids": user_preferred_ids,
            "preferred_layouts": self.preferences.get("layouts", []),
            "preferred_colors": self.preferences.get("colors", []),
            "preferred_styles": self.preferences.get("styles", []),
            "user_notes": user_notes,
            "issue_ledger": self.issue_ledger,
            "candidates_reviewed": [
                {
                    "id": c.get("candidate_id", c.get("id", "")),
                    "image_path": c.get("image_path", ""),
                    "identity": c.get("identity", ""),
                }
                for c in generated
            ],
        }
