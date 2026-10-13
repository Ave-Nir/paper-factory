# paper2diagram-skill — 论文 → 学术流程图生成器

> 不是"读个摘要直接让模型画图"，而是一条 **S0–S5 分阶段人机协作流水线**：先分析论文的技术结构，再按 **结构化 Prompt 契约** 生成候选，最后在你选定的方向上精修出图。

这是 [`paper-factory`](../README.md) 的生图模块，可独立使用，也被 `paper_pipeline` 编排调用。

---

## 为什么不是"一把梭"

直接让生图模型画流程图，常见问题是：布局随机、文字乱码、箭头关系错乱、多张图风格漂移。本模块用三件事来约束它：

- **结构化 Prompt 契约**：语义图契约（节点/边/分组）+ 可见文字契约（哪些字必须出现）+ Edge-label-first 原则（先定连线语义，再排版面）。
- **两轮候选机制**：R1 探索轮铺开多种布局×配色，R2 正式轮在选定方向上精修，避免"一稿定生死"。
- **偏好承接**：S3 的偏好会显式写进 S4/S5 的提示词，保证多轮之间不跑偏。

---

## 工作流程

```
S0 论文基础分析   LLM 提取阶段、模块、连接关系与术语
S1 策略设计       诊断图类型，生成 R1 探索候选 Prompt
S2 草图探索       调用生图模型产出 R1 候选（C01–C12 布局变体 × 配色）
S3 方向选择       人工审阅并指定偏好候选（或自动选取首/中/尾）
S4 候选简报       基于偏好生成 R2 正式候选 Prompt（F01–F08），承接偏好特征
S5 正式候选       调用生图模型产出出版级图片
```

快速模式（跳过两轮候选）：`论文文件 → LLM 分析 → 模板匹配 → 结构化提示词 → 出图`。

---

## 安装

```bash
pip install -r requirements.txt
```

依赖：`openai`、`python-docx`、`pyyaml`、`requests`。

---

## 使用方法

```bash
# 完整 S0–S5（默认 4 个 R1 + 4 个 R2 候选）
python paper2diagram.py ../examples/input/sample_paper.md

# 跳过 S3，直接指定 R1 偏好
python paper2diagram.py ../examples/input/sample_paper.md --prefer C01,C04

# 只跑某个阶段 / 从断点续跑
python paper2diagram.py ../examples/input/sample_paper.md --stage s0
python paper2diagram.py --resume

# 自定义候选数量
python paper2diagram.py ../examples/input/sample_paper.md --s2-count 8 --s5-count 6

# 快速单次出图
python paper2diagram.py ../examples/input/sample_paper.md --quick --template horizontal_3frame --palette ocean_breeze
```

### 参数说明

| 参数 | 说明 |
| --- | --- |
| `paper_file` | 论文文件路径（`.docx` / `.txt` / `.md`） |
| `--quick` | 快速单次生成模式（跳过两轮候选） |
| `--template <id>` | 快速模式指定布局模板 |
| `--palette <name>` | 指定配色方案 |
| `--resume` | 从断点继续执行 |
| `--stage s0..s5` | 只执行指定阶段 |
| `--s2-count <n>` | R1 探索候选数量（默认 4，最多 12） |
| `--s5-count <n>` | R2 正式候选数量（默认 4，最多 8） |
| `--prefer <ids>` | S3 偏好候选 ID，如 `C01,C04` |
| `--output <path>` | 输出目录 |
| `--no-skip` | 重新生成已存在的图片 |
| `--model` / `--base-url` | 生图模型与端点 |
| `--llm-base-url` / `--llm-model` | LLM 端点与模型 |
| `--timeout` / `--max-retries` / `--total-timeout` | 单次超时 / 重试次数 / 总超时 |

---

## 配置密钥

推荐用环境变量（`.gitignore` 已忽略 `.env`）：

```powershell
$env:LLM_API_KEY   = "sk-你的LLM密钥"
$env:IMAGE_API_KEY = "sk-你的图片API密钥"
python paper2diagram.py ../examples/input/sample_paper.md
```

也可通过 `--llm-api-key` / `--api-key` 临时传入。密钥读取统一收敛在根目录 [`api_config.py`](../api_config.py)，缺失时 fail-closed 报错，不静默降级。

---

## 配色方案

| ID | 名称 | 适用领域 |
| --- | --- | --- |
| `ocean_breeze` | 海洋清风 | 科技、工程 |
| `pink_girl` | 粉彩少女 | 社会科学、人文 |
| `forest_green` | 柔绿森林 | 环境、生态 |
| `summer_beach` | 夏日海滩 | 能源、材料 |
| `fresh_holiday` | 清新假日 | 计算机、数据科学 |

## 布局模板

| 模板 ID | 描述 |
| --- | --- |
| `horizontal_3frame` | 横向三段式（左→中→右） |
| `vertical_3stage` | 纵向三段式（上→中→下） |
| `hybrid_3x2` | 混合式 3×2（顶部横向 + 底部纵向） |
| `complex_multi` | 复杂多阶段（四阶段及以上） |

自定义模板：在 `paper2diagram/templates/configs/` 下新增 YAML 即可。

## 布局变体

**探索轮 R1（C01–C12）**

| ID | 风格 | ID | 风格 |
| --- | --- | --- | --- |
| C01 | 经典水平管线 | C07 | 极简线框 |
| C02 | 中心压缩布局 | C08 | 图标增强图 |
| C03 | 双轨训练 / 推理 | C09 | 漏斗式 |
| C04 | 垂直层叠 + 跳跃连接 | C10 | 信号轨迹式 |
| C05 | 数据流强调（圆形节点） | C11 | UML 组件图 |
| C06 | 展开模块视图 | C12 | 叙事分镜式 |

**正式轮 R2（F01–F08）**

| ID | 风格 | ID | 风格 |
| --- | --- | --- | --- |
| F01 | 精修标准管线 | F05 | 模块端口连接 |
| F02 | 双面板训练 / 推理 | F06 | 极简高对比 |
| F03 | 垂直层叠最终版 | F07 | 内部展开最终版 |
| F04 | 潜空间中心图 | F08 | 数据流加权最终版 |

---

## 工程可靠性

生图是最容易卡住的一环，因此内置：

- **单次请求超时**（默认 300s）、**最大重试次数**（默认 3）、**总超时上限**（默认 900s），均可通过参数覆盖。
- **智能异常分类**：超时 / 连接 / 5xx 自动重试；认证错误（400/401/403/429）立即退出，不浪费额度。
- **响应格式兼容**：同时支持 base64 内联与 URL 两种返回。
- **断点续跑**：各阶段状态持久化，中断后不必重跑已完成的阶段。
- **跳过已存在图片**：小于阈值（5KB）的图片才会被重新生成，避免重复烧钱。

---

## 项目结构

```
paper2diagram-skill/
├── paper2diagram/
│   ├── llm/
│   │   ├── paper_analyzer.py      # 论文结构与术语分析
│   │   ├── prompt_generator.py    # 结构化 Prompt 契约生成
│   │   ├── color_palettes.py      # 5 套配色方案
│   │   └── candidate_variants.py  # 12 + 8 种布局变体
│   ├── templates/
│   │   ├── manager.py             # 模板管理器
│   │   └── configs/               # 布局模板 YAML
│   ├── image/
│   │   └── generator.py           # 生图（超时 + 重试 + 异常分类）
│   ├── checkpoint.py              # 状态管理与断点续跑
│   └── preference_carryover.py    # S3 → S4/S5 偏好承接
├── paper2diagram.py               # 主入口
└── requirements.txt
```

---

## 许可

[MIT](../LICENSE) © 2026 Ave-Nir