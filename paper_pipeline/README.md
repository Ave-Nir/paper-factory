# paper-pipeline — 论文工厂整合管道与质量审计

> 把 [`paper2diagram-skill`](../paper2diagram-skill/README.md) 和 [`paperforge`](../paperforge/README.md) 串成一条命令：**生图 → 插入 → 排版 → Gate5 审计 → 自动修复**。

这是 [`paper-factory`](../README.md) 的编排层。它不重复实现业务，只做三件事：**编排**（Orchestrator）、**审计**（质量门）、**留痕**（结构化日志 + 错误归因）。

---

## 它解决了什么

生图 + 排版这两步单独都能跑，但拼在一起时有四个真实痛点，正是本模块存在的理由：

| 痛点 | 本模块的做法 |
| --- | --- |
| 流程图该插进哪一节？ | 多重章节检测（Heading 样式 / 中文编号 / 数字编号 / 英文模式），精准定位"研究方法"章节末尾 |
| 排版完"看起来没问题"就交付？ | **Gate5 十六项 PDF 严格校验**，ERROR 级问题**拒绝产出** |
| 检测出问题还得手改 LaTeX？ | **15 条自动修复规则**按错误代码精准改写源文件 |
| 修复后全量重跑太慢？ | **增量重编译**，跳过 docx 解析直接调 `xelatex`，提速 50%–70% |

---

## 架构

```
┌──────────────────────────────────────────────────────────┐
│  CLI            cli.py —— 参数解析，最薄的一层             │
├──────────────────────────────────────────────────────────┤
│  Orchestrator   core/pipeline.py —— 编排各 Service        │
├──────────────────────────────────────────────────────────┤
│  Services       diagram_service / typeset_service         │
├──────────────────────────────────────────────────────────┤
│  Models         dataclass / Pydantic 全链路数据模型        │
├──────────────────────────────────────────────────────────┤
│  Config         config/settings.py —— 配置中心（fail-closed）│
├──────────────────────────────────────────────────────────┤
│  Gates          Gate5 / 结构化日志 / 错误归因              │
└──────────────────────────────────────────────────────────┘
```

**分层红线**：上层只调用紧邻下层，禁止跨层与循环依赖；所有异常携带完整上下文。

---

## 快速开始

```bash
cd paper_pipeline

# 必需：密钥只从环境变量读取，缺失即 fail-closed 报错
$env:LLM_API_KEY   = "sk-你的LLM密钥"
$env:IMAGE_API_KEY = "sk-你的图片API密钥"

# 裸文件输入：直接处理一篇论文
python run.py ../examples/input/sample_paper.md --work-dir ../workspace

# 标准输入：验证上游 artifact 链后再排版
python run.py --manifest runs/<run_id>/
```

> `--work-dir` 不指定时默认为当前目录。

### 两种输入模式

| 模式 | 用法 | 行为 |
| --- | --- | --- |
| **裸文件** | `paper-pipeline <paper>` | 直接解析 `.docx` / `.md` / `.tex` 并走完整流程 |
| **标准 artifact** | `paper-pipeline --manifest runs/<run_id>/` | 先校验 `paper_manifest.v1.json` 等上游产物的 schema 与 hash，缺一即阻断 |

标准模式会验证 `paper_manifest`、`manuscript_source`、`reference_bundle`、`figure_asset` 的存在性、schema 版本与 `content_sha256` 一致性（fail-closed）。

---

## 质量门

### 流程内的三级门

```
InputGate（输入校验） → DiagramGate（生图校验） → TypesetGate（排版校验） → Gate5（PDF 审计）
```

| Gate | 校验内容 | 失败处理 |
| --- | --- | --- |
| **InputGate** | 文件存在、扩展名、大小（空文件 / <1KB 阻断） | `ValidationError` |
| **DiagramGate** | 图片数量、尺寸合规、文件完整性 | `DiagramGenerationError` |
| **TypesetGate** | PDF 生成成功、页码范围、质量报告 | `TypesetError` |

### Gate5 —— PDF 十六项审计

排版完成后执行，**ERROR 级问题拒绝输出 PDF/Word**：

| # | 检测项 | 级别 | 自动修复 |
| --- | --- | --- | --- |
| 1 | 封面完整性 | warning | — |
| 2 | 重复参考文献标题 | **error** | ✅ |
| 3 | 二级标题左对齐 | **error** | ✅ |
| 4 | 摘要内容非空 | **error** | — |
| 5 | 关键词不单独分页 | **error** | ✅ |
| 6 | 目录独立成页 | **error** | ✅ |
| 7 | 目录条目完整性 | warning | ✅ |
| 8 | 页码格式（罗马不晚于阿拉伯） | **error** | ✅ |
| 9 | 页眉页脚合理性 | warning | — |
| 10 | 正文字号一致性 | **error** | ✅ |
| 11 | 空白页 | warning | — |
| 12 | 参考文献条目格式 | warning | — |
| 13 | 图片插入 | warning | — |
| 14 | 图片宽高比（防拉伸） | warning | ✅ |
| 15 | PDF 可打开性 | **error** | — |
| 16 | `\cite` / `\bibitem` 对应与序号连续 | warning | ✅ |

**自动修复规则示例**

| 错误代码 | 修复内容 |
| --- | --- |
| `DUPLICATE_REF_HEADING` | 删除多余的参考文献标题 |
| `SUBHEADING_NOT_LEFT` | 为 titlesec 添加 `\raggedright` |
| `KEYWORD_ALONE` | 删除关键词与目录间的 `\clearpage` |
| `TOC_NOT_SEPARATE` | 目录前补 `\clearpage` |
| `ROMAN_AFTER_ARABIC` | 删除正文中的 `\pagenumbering{Roman}` |
| `IMAGE_ASPECT_DISTORTED` | 补 `keepaspectratio` |
| `TABLE_NOT_THREE_LINE` | `\hline` → booktabs 三线表 |

---

## 产物

```
workspace/<run>/
├── diagrams/                 # 生成的学术流程图
├── build/
│   ├── paper.pdf             # 最终 PDF（已插入流程图）
│   ├── paper.docx            # 同结构 Word
│   ├── paper.tex             # LaTeX 源（含位置标记）
│   └── images/               # 提取的图片
├── pipeline.log              # 结构化日志（JSON Lines，可接 CI/CD）
├── pipeline_log.json         # 日志汇总
└── error_attribution.json    # 错误归因（仅检测失败时生成）
```

`error_attribution.json` 含：**根因分析**（可能原因 + 置信度）、**修复建议**（自动化程度 + 成功率预估）、**历史学习**（基于历史修复成功率）。

---

## 测试

```bash
cd paper_pipeline
python -m pytest -q      # 118 passed
```

覆盖范围：Gate5 规则、PDF 严格校验规则、settings 路径解析、artifact manifest 校验、清单构建、异常体系、图表模型、输入门。

其中一条值得注意的测试：**断言默认路径中不残留任何硬编码绝对盘符**，同时 fixture 会主动清空 `LLM_API_KEY` / `IMAGE_API_KEY`，用来守住"无硬编码 + fail-closed"这两条红线。

---

## 目录结构

```
paper_pipeline/
├── run.py                          # 一键入口（把 src/ 加进 sys.path）
├── pyproject.toml                  # 打包配置（console script: paper-pipeline）
├── src/paper_pipeline/
│   ├── cli.py                      # CLI（最薄层）
│   ├── exceptions.py               # PipelineError 及子类
│   ├── core/
│   │   ├── pipeline.py             # Orchestrator（流程编排）
│   │   ├── manifest_verifier.py    # 上游 artifact 链校验
│   │   └── submission_manifest_builder.py  # 交付清单构建
│   ├── services/
│   │   ├── diagram_service.py      # 生图服务封装
│   │   └── typeset_service.py      # 排版服务封装（调用 paperforge）
│   ├── gates/
│   │   ├── quality_gates.py        # InputGate / DiagramGate / TypesetGate / Gate5
│   │   ├── structured_logger.py    # 结构化日志
│   │   └── error_attribution.py    # 错误归因
│   ├── models/                     # paper.py / diagram.py
│   └── config/settings.py          # 配置中心（环境变量 + 相对路径推导）
└── tests/                          # 118 项测试
```

---

## 许可

[MIT](../LICENSE) © 2026 Ave-Nir