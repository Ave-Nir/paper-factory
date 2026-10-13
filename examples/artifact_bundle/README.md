# B 文本工厂 — 交付产物说明

> 数据集：output_770_final_v2 | 语言：zh | 模型：deepseek-v4-pro
> 生成日期：2026-07-20 | SPEC-B 评分：96/100

---

## 一、文件清单

| # | 文件 | 格式 | Schema | 台账依据 | 交付对象 |
|---|------|------|--------|---------|----------|
| 1 | `paper/manuscript_source.md` | Markdown | `manuscript_source.v1` | §3.2 | **C (排版)** |
| 2 | `paper/manuscript_source.tex` | LaTeX | `manuscript_source.v1` | §3.2 | **C (排版)** |
| 3 | `paper/manuscript_source.json` | JSON | `manuscript_source.v1` | §3.2/§3.8 | **C/D2/D3** |
| 4 | `paper/paper_manifest.json` | JSON | `paper_manifest.v1` | §3.2/§3.9 | **C/D/E** |
| 5 | `figures/figure_request.json` | JSON | `figure_request.v1` | §3.2/§3.9 | **E (图表)** |
| 6 | `refs/reference_request.json` | JSON | `reference_request.v1` | §3.2/§3.7 | **D1 (参考文献)** |
| 7 | `refs/writing_support_request.json` | JSON | `writing_support_request.v1` | §3.2/§3.8 | **D2 (写作支持)** |

---

## 二、各文件详解

### 2.1 `paper/manuscript_source.md` — 论文正文 (Markdown)

**交付对象**：C (排版交付)

**用途**：可直接用 pandoc 转换为 docx，或作为排版引擎输入。含 YAML frontmatter 元数据。

**YAML frontmatter 字段**（对齐台账 §1.3）：

| 字段 | 类型 | 台账依据 | 值 |
|------|------|---------|-----|
| `schema_version` | T-016 | §1.3 | `manuscript_source.v1` |
| `artifact_id` | T-001 (UUID) | §1.3 | `e9c68a24-...` |
| `run_id` | T-001 (UUID) | §1.3 | 本次 pipeline 执行的 run ID |
| `producer.service` | T-005 | §1.3 | `narrative` |
| `producer.version` | T-004 | §1.3 | `2.0.0` |
| `producer.code_revision` | string | §1.3 | `unverified` |
| `created_at` | T-003 (UTC) | §1.3 | `2026-07-20T06:24:38Z` |
| `content_sha256` | T-002 | §1.3 | 全文 SHA-256 |
| `status` | T-007 | §1.3 | `completed` |
| `lineage.parent_refs` | T-102[] | §1.3 | 父 artifact 引用列表 |
| `lineage.source_run_ids` | T-001[] | §1.3 | 来源 run ID 列表 |

**正文结构**（IMRaD）：

```
## Abstract
## 一、引言        (Introduction: background → gap → RQ → roadmap)
## 二、研究方法     (Methods: data source, filtering, tools)
## 三、研究结果     (Results: 3.1~3.5, 五个分析维度)
## 四、讨论         (Discussion: literature dialogue, implications, limitations)
## 五、结论         (Conclusion: synthesis, outlook)
## References
```

---

### 2.2 `paper/manuscript_source.tex` — 论文正文 (LaTeX)

**交付对象**：C (排版交付)

**用途**：可直接用 xelatex/pdflatex 编译为 PDF。含完整导言区（documentclass, packages, title, author）。内容与 Markdown 版本完全一致。

---

### 2.3 `paper/manuscript_source.json` — 稿件正文 artifact

**交付对象**：C/D2/D3

**Schema**：`manuscript_source.v1`（台账 §3.2）

**§1.3 外壳字段**：全部 9 个字段齐全。

**业务字段**（台账 §3.8 MSP_INPUT_REF / MSSP_*）：

| 字段 | 类型 | 台账依据 | 说明 |
|------|------|---------|------|
| `format` | string | — | `markdown` 或 `latex` |
| `source_text` | string | §3.8 | 稿件正文全文 |
| `word_count` | int | §3.8 | 词数统计 |
| `language` | T-013 | §3.8 | `zh`（ISO 639-1） |

**消费方式**：
```python
import json
ms = json.load(open('paper/manuscript_source.json'))
assert ms['schema_version'] == 'manuscript_source.v1'
assert len(ms['content_sha256']) == 64
paper_text = ms['source_text']  # 论文全文
```

---

### 2.4 `paper/paper_manifest.json` — 论文清单

**交付对象**：C/D/E

**Schema**：`paper_manifest.v1`（台账 §3.2）

**§1.3 外壳字段**：全部 9 个字段齐全。

**业务字段**（台账 §3.9 PAP_*）：

| 字段 | 类型 | 台账 Field ID | 说明 |
|------|------|-------------|------|
| `paper_run_id` | T-001 | PAP_PAPER_RUN | 每次组装唯一 |
| `analysis_result_ref` | T-102 | PAP_ANALYSIS_REF | 指向 A 的 analysis_result.v2 |
| `analysis_audit_ref` | T-102 | PAP_ANALYSIS_AUDIT_REF | 指向 A 的 analysis_audit.v1 |
| `reference_bundle_ref` | T-102 | PAP_REFERENCE_BUNDLE_REF | 指向 D1 的 reference_bundle.v1（D1 就绪后填入） |
| `sections[]` | object[] | PAP_SECTIONS | 每节含 section_id, sha256, status, md_path, json_path |
| `claim_evidence_map[]` | T-107[] | PAP_CLAIM_EVIDENCE | claim 到 evidence 的映射 |
| `figure_request_refs[]` | T-102[] | PAP_FIGURE_REQUESTS | 指向 figure_request.v1 |
| `manuscript_source_ref` | T-102 | PAP_SOURCE_REF | 指向 manuscript_source.v1 |
| `paper_content_sha256` | T-002 | PAP_PAPER_HASH | 论文正文的 SHA-256 |

**T-102 ArtifactRef 子字段**（每个 ref 对象）：

| 字段 | 类型 | 说明 |
|------|------|------|
| `artifact_id` | T-001 | 被引用 artifact 的 UUID |
| `kind` | T-006 | artifact 种类，如 `analysis_result` |
| `schema_version` | T-016 | schema 版本，如 `analysis_result.v2` |
| `run_id` | T-001 | 被引用 artifact 的 run ID |
| `relative_path` | string | 相对于 workspace 的文件路径 |
| `content_sha256` | T-002 | 被引用 artifact 的内容 hash |
| `status` | T-007 | 被引用 artifact 的执行状态 |

**消费方式**（C 验证五链一致）：
```python
import json
pm = json.load(open('paper/paper_manifest.json'))

# 1. 验证 manuscript_source hash
ms = json.load(open('paper/manuscript_source.json'))
assert pm['manuscript_source_ref']['content_sha256'] == ms['content_sha256']

# 2. 验证 section hashes
for sec in pm['sections']:
    md = open(f"sections/{sec['section_id']}.md").read()
    assert sec['sha256'] == hashlib.sha256(md.encode()).hexdigest()

# 3. 验证 paper_content_sha256
paper = open('paper/manuscript_source.md').read()
assert pm['paper_content_sha256'] == hashlib.sha256(paper.encode()).hexdigest()
```

---

### 2.5 `figures/figure_request.json` — 图表需求

**交付对象**：E (科学图表与数据可视化)

**Schema**：`figure_request.v1`（台账 §3.2）

**§1.3 外壳字段**：全部 9 个字段齐全，业务数据在 `payload` 中。

**业务字段**（台账 §3.9 FIG_*）：

| 字段 | 类型 | 台账 Field ID | 说明 |
|------|------|-------------|------|
| `figure_requests[].figure_request_id` | T-001 | FIG_REQUEST_ID | 每个图表需求的唯一 UUID |
| `figure_requests[].figure_id` | string | — | 全局编号（图1~N, 表1~N） |
| `figure_requests[].figure_type` | string | — | `figure` 或 `table` |
| `figure_requests[].rq_id` | T-015 | FIG_RQ_ID | 对应的 Research Question |
| `figure_requests[].intended_claim` | T-015 | FIG_CLAIM | 该图要表达的核心主张 |
| `figure_requests[].evidence_refs[]` | T-107[] | FIG_EVIDENCE_REFS | 关联的 evidence 引用 |
| `figure_requests[].allowed_chart_families[]` | enum[] | FIG_CHART_FAMILY | 建议图表类型：`line`, `bar`, `network`, `heatmap`, `scatter`, `table`, `area` |
| `figure_requests[].visual_constraints` | object | FIG_VISUAL_CONSTRAINTS | `color_blind_safe`, `grayscale_safe` |
| `figure_requests[].status` | T-007 | FIG_STATUS | 当前为 `planned`，E 完成后改为 `completed` |
| `total_figures` | int | — | 图的总数 |
| `total_tables` | int | — | 表的总数 |

**当前统计**：16 条需求（13 张图 + 3 张表），覆盖 5 个 Results 子节。

**消费方式**（E 读取并出图）：
```python
fm = json.load(open('figures/figure_request.json'))
for req in fm['payload']['figure_requests']:
    chart_type = req['allowed_chart_families']    # ['line', 'area']
    data_refs = req['evidence_refs']              # ['SC-2.1', 'SC-2.2']
    # E: 从 analysis_result.v2 取 data → data_slice (T-114) → 渲染 → figure_asset.v1
```

---

### 2.6 `refs/reference_request.json` — 参考文献解析请求

**交付对象**：D1 (参考文献解析服务)

**Schema**：`reference_request.v1`（台账 §3.2）

**§1.3 外壳字段**：全部 9 个字段齐全。

**业务字段**（台账 §3.7 REF_*）：

| 字段 | 类型 | 台账 Field ID | 说明 |
|------|------|-------------|------|
| `reference_request_id` | T-001 | REF_REQUEST_ID | 唯一 UUID |
| `requester` | T-005 | REF_REQUESTER | `narrative`（B 文本工厂） |
| `citation_contexts[]` | object[] | REF_CITATION_CONTEXT | 每条引用的作者、年份、来源角色 |
| `citation_contexts[].citation_key_hint` | string | — | 建议的 citation key（如 `Bourdieu1984`） |
| `citation_contexts[].author_surname` | string | — | 作者姓氏 |
| `citation_contexts[].year` | string | — | 发表年份 |
| `citation_contexts[].source_role` | string | — | `primary`（主引用） |
| `allowed_data_sources[]` | enum[] | REF_ALLOWED_SOURCES | `["crossref", "pubmed", "openalex"]` |
| `requested_style_profile_ref` | T-102 | REF_STYLE_ID | D1 发布 style profile 后填入（当前 `null`） |

**消费方式**（D1 解析）：
```python
rr = json.load(open('refs/reference_request.json'))
for ctx in rr['citation_contexts']:
    # D1: author + year → resolver (Crossref/PubMed/OpenAlex) → CSL-JSON
    # D1 产出: reference_bundle.v1 (含 formatted_bibliography)
```

---

### 2.7 `refs/writing_support_request.json` — 写作支持请求

**交付对象**：D2 (写作支持服务)

**Schema**：`writing_support_request.v1`（台账 §3.2）

**§1.3 外壳字段**：全部 9 个字段齐全。

**业务字段**（台账 §3.8 WRT_*）：

| 字段 | 类型 | 台账 Field ID | 说明 |
|------|------|-------------|------|
| `source_manuscript_ref` | T-102 | WRT_SOURCE_REF | 指向 manuscript_source.v1（含 content_sha256） |
| `allowed_evidence_refs[]` | T-107[] | WRT_ALLOWED_FACTS | 允许 D2 使用的事实集合 |
| `rule_set_version` | T-004 | WRT_RULE_VERSION | 规则集版本 `1.0.0` |
| `target_journal_ref` | T-102 | WRT_TARGET_JOURNAL | D2 配置期刊后填入（当前 `null`） |

---

## 三、台账治理验证清单

### §1.3 artifact 外壳

| 文件 | schema_version | artifact_id | run_id | producer | created_at | content_sha256 | status | lineage | extensions |
|------|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| manuscript_source.json | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| paper_manifest.json | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| figure_request.json | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| reference_request.json | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| writing_support_request.json | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| evidence_graph.json | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

### 类型合规

| 类型 | 说明 | 使用位置 |
|------|------|---------|
| T-001 (UUID) | RFC 4122，全小写 | 所有 `artifact_id`, `run_id`, `figure_request_id` |
| T-002 (SHA-256) | 64 位 hex | 所有 `content_sha256` |
| T-003 (UTC) | ISO-8601，Z 结尾 | 所有 `created_at` |
| T-004 (SemVer) | MAJOR.MINOR.PATCH | `producer.version`, `rule_set_version` |
| T-005 (ServiceId) | 受控枚举 | `producer.service: "narrative"` |
| T-007 (RunStatus) | 受控枚举 | `status: "completed"/"planned"` |
| T-016 (ArtifactSchemaId) | `{name}.v{N}` | 所有 `schema_version` |
| T-102 (ArtifactRef) | 含 kind/schema_version/content_sha256 | `analysis_result_ref`, `manuscript_source_ref` |

### FTG 审计门

| Gate | 检查内容 | 状态 |
|------|---------|:---:|
| FTG-001 | schema 版本/必填字段/类型 | ✅ |
| FTG-002 | artifact ref/hash/run 一致性 | ✅ |
| FTG-003 | owner 和字段名注册 | ✅ |
| FTG-004 | null/empty/status 语义 | ✅ |
| FTG-005 | 数值/单位/样本量 | ✅ |
| FTG-006 | secret 泄露 | ✅ |
| FTG-007 | manifest 链完整性 | ✅ |
| FTG-008 | 弃用字段 | ✅ |
| FTG-009 | gate/approval/publication 分轴 | ✅ |
| FTG-010 | migration-only 隔离 | ✅ |
| FTG-012 | lineage 父引用闭合 | ✅ |

---

## 四、版本信息

| 字段 | 值 |
|------|-----|
| 交付日期 | 2026-07-20 |
| 数据集 | output_770_final_v2 (Web of Science, 教育不平等, 770 篇) |
| 语言 | zh (简体中文) |
| 模型 | deepseek-v4-pro |
| 论文结构 | IMRaD (Introduction / Methods / Results / Discussion / Conclusion) |
| 论文字数 | ~7,000 词 |
| SPEC-B 评分 | 96/100 |
| 交付方 | 成员 B (文本工厂 / narrative) |
| 消费方 | C (排版交付), D1 (参考文献), D2 (写作支持), E (科学图表) |
