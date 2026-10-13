# examples — 真实链路产物示例

这里放的是**一条完整管道跑出来的真实产物**（已做匿名化处理，不含任何真实姓名、机构或第三方受版权文档），用来让你不用配密钥就能看清每个环节的输入输出长什么样。

> 所有示例论文均为文献计量方向的合成/匿名样本，仅用于演示格式与数据契约。

---

## 目录导航

```
examples/
├── input/
│   └── sample_paper.md              # 输入：一篇文献计量分析论文（Markdown）
├── output/                          # 排版环节产物（对应 paperforge）
│   ├── paper_final.md / .tex        #   英文版：正文源 与 LaTeX 源
│   └── paper_final_zh.md / .tex     #   中文版：正文源 与 LaTeX 源
├── figure_specs/                    # 生图环节的输入契约
│   ├── figure_requirements.md       #   图表需求清单（人类可读）
│   └── analysis_result.v2.json      #   上游分析结果 artifact（证据底座）
└── artifact_bundle/                 # 一次完整交付的数据包
    ├── README.md                    #   交付包字段级说明（务必先看这份）
    ├── paper/                       #   稿件与清单
    ├── figures/                     #   图表需求
    └── refs/                        #   参考文献 / 写作支持请求
```

---

## 各部分说明

### `input/sample_paper.md`
标准输入样本，带 YAML frontmatter，可直接喂给任意入口：

```bash
cd ../paper2diagram-skill && python paper2diagram.py ../examples/input/sample_paper.md
cd ../paperforge          && python config/process_lunwen_v4.py ../examples/input/sample_paper.md -t auto -o ../build_out
cd ../paper_pipeline      && python run.py ../examples/input/sample_paper.md --work-dir ../workspace
```

### `output/`
排版引擎产出的正文与 LaTeX 源（中英双版）。对照它们可以看到模板切换后章节编号、三线表、引用格式的差异。

### `figure_specs/`
生图环节的输入：

- `figure_requirements.md` —— 人类可读的图表清单（图 1~N、表 1~N 的意图与建议图型）。
- `analysis_result.v2.json` —— 上游「分析服务」的完整 artifact，即**证据底座**。图表需求里的每条证据引用都指回这份文件中的具体路径，保证"每张图都能逐点复核数据来源"。

### `artifact_bundle/`
一次交付的完整数据包，其 [`README.md`](artifact_bundle/README.md) 逐字段说明了每个 artifact 的 schema、外壳字段（`schema_version` / `artifact_id` / `run_id` / `content_sha256` / `lineage` …）与消费方式，是理解本项目**数据契约**最适合的入口。

---

## 说明

- 示例中的 `content_sha256` 等哈希为生成时快照值，改动文件内容后哈希自然不再匹配——这是设计使然（校验本就用于发现篡改）。
- 未包含任何 API 密钥；密钥只从环境变量读取，见根目录 [`.env.example`](../.env.example)。