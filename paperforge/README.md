# PaperForge — 学术论文 LaTeX / Word 双输出排版引擎

> **代码驱动排版**：所有输出由 Python 确定性生成，LLM 只负责"理解内容"，不负责"写 LaTeX"——从根上规避幻觉，保证每次编译结果稳定可比。

PaperForge 是 [`paper-factory`](../README.md) 的排版核心：吃进 `.docx` / `.md` / `.tex`，吐出**格式对齐的 PDF + Word**，并在产出前过 Gate1–Gate4 质量门。

---

## 核心能力

| 能力 | 说明 |
| --- | --- |
| **双输入** | `.docx`（Word）与 `.md`（Markdown）自动识别，亦支持 `.tex` 重新排版 |
| **双输出** | PDF（XeLaTeX 编译）与 Word（python-docx）同时生成，结构与格式对齐 |
| **10 套模板** | 中文/英文学位论文、期刊、会议全覆盖，支持 `-t auto` 自动推断 |
| **精细排版** | 标题独占页、目录单开页、三线表（booktabs）、页眉页脚、多区域页码 |
| **中英混排** | 中文宋体/黑体、英文 Times New Roman，自动切换 |
| **公式三模式** | Unicode 可读文本 / Word 原生 OMML / 保留 LaTeX 原样 |
| **稳定编译** | 编译失败自动修复（非法字符、编码、Overfull hbox），多轮重试 |
| **质量门** | Gate1 输入校验 → Gate2 结构检查 → Gate3 编译检查 → Gate4 终审 |
| **配置驱动** | 格式参数、模板规则、输入候选全部收敛进 YAML，无硬编码 |
| **NL Pipeline（可选）** | 自然语言描述 → `PaperSpec` JSON → 直接排版，密钥仅从环境变量读取 |

---

## 快速开始

> ⚠️ PaperForge 需**以自身目录为工作目录**运行（内部按相对路径解析模板与资源）。

```bash
cd paperforge

# 自动检测模板（推荐）
python config/process_lunwen_v4.py ../examples/input/sample_paper.md -t auto

# 强制指定模板
python config/process_lunwen_v4.py paper.docx -t ieee
python config/process_lunwen_v4.py paper.docx -t renai

# 自定义输出目录 / 仅生成 PDF
python config/process_lunwen_v4.py paper.docx -o build_out -t auto
python config/process_lunwen_v4.py paper.docx -o build_out --no-word

# 排版已有 .tex
python -c "from workflows.tex_typeset import typeset_tex; typeset_tex('paper.tex', 'build_out')"
```

### 支持的模板

| 模板 | 语言 | 适用场景 |
| --- | --- | --- |
| `nsfc` | 中文 | 国家自然科学基金申请书 |
| `sci` | 中文 | SCI 中文期刊 |
| `thesis` | 中文 | 中文学位论文 |
| `renai` | 中文 | 天津仁爱学院毕业论文 |
| `humanities` | 中文 | 人文社科类论文 |
| `ieee` | 英文 | IEEE 会议 / 期刊 |
| `icml2025` | 英文 | ICML 2025 |
| `cvpr2024` | 英文 | CVPR 2024 |
| `neurips2024` | 英文 | NeurIPS 2024 |
| `acl2024` | 英文 | ACL 2024 |

`-t auto` 会依据语言占比、标题/摘要关键词、引用格式等规则自动推断模板；`-t <名称>` 则强制指定，优先级最高。

### 输出结果

```
build_out/
├── paper.pdf      # 排版好的 PDF
├── paper.docx     # 同结构 Word（目录、三线表、分页齐全）
├── paper.tex      # 中间 LaTeX 源
├── paper.aux      # BibTeX 辅助文件
├── paper.toc      # 目录
└── images/        # 从文档中提取的图片
```

---

## NL Pipeline（自然语言 → 排版）

可选能力：给一段自然语言描述，让 LLM 产出结构化 `PaperSpec`，再走同一套确定性排版流程。

```bash
# 密钥仅从环境变量读取（绝不写入代码或配置）
$env:LLM_API_KEY = "sk-你的密钥"

# 1. 生成 PaperSpec JSON
python config/nl_pipeline.py intake --input description.txt -o paper_spec.json

# 2. 生成后立即排版
python config/nl_pipeline.py intake --input description.txt -t nsfc --render -o build_out/

# 3. 从已保存的 JSON 反复排版（不再调用 LLM）
python config/nl_pipeline.py render paper_spec.json -t ieee -o build_ieee/
```

> 安全约定：本项目**从不**通过 CLI 参数或配置文件传递 API 密钥，只从环境变量读取。根目录 [`.env.example`](../.env.example) 中不含任何真实值。

---

## 编程接口

```python
from core.converter import convert, Converter, ConversionConfig
from core.formula_engine import OutputMode

# 便捷方式
result = convert("input.docx", "output/paper.docx", output_format="docx")

# 完整控制
config = ConversionConfig(
    output_format="docx",
    formula_mode=OutputMode.UNICODE,
    quality_threshold=80,
)
converter = Converter(config)
result = converter.convert("input.docx", "output/paper.docx")

print(f"质量得分: {result.validation.score}/100")
print(f"是否达标: {result.validation.is_acceptable}")
```

公式引擎支持三种模式：

```python
from core.formula_engine import FormulaEngine, OutputMode

FormulaEngine(OutputMode.UNICODE).convert(r"\alpha + \beta = \gamma")  # → α + β = γ
FormulaEngine(OutputMode.OMML).convert(r"x^{2}")                      # → x²（Word 原生上标）
FormulaEngine(OutputMode.LATEX).convert(r"\frac{a}{b}")               # → \frac{a}{b}
```

---

## 目录结构

```
paperforge/
├── config/
│   ├── process_lunwen_v4.py   # ★ 通用入口：.docx / .md / .tex / .json → PDF + Word
│   ├── nl_pipeline.py         # ★ NL Pipeline：自然语言 → PaperSpec → 排版
│   ├── venue_config.yaml      # venue → 模板类映射
│   ├── field_config.yaml      # field → 术语 / 章节命名
│   ├── style_config.yaml      # 作者风格偏好 + 输入候选
│   └── template_rules.yaml    # 模板自动识别规则
├── core/
│   ├── document_reader.py     # Word 文档解析与块分类
│   ├── markdown_reader.py     # Markdown 文档解析
│   ├── tex_reader.py          # LaTeX 解析（保留公式）
│   ├── tex_normalizer.py      # 混合语法规范化
│   ├── word_builder.py        # Word 文档构建（核心）
│   ├── latex_builder.py       # LaTeX 组装（配置驱动）
│   ├── latex_compiler.py      # XeLaTeX 编译
│   ├── latex_cleaner.py       # LaTeX 清洗
│   ├── assembler.py           # 全文拼装
│   ├── template_engine.py     # 模板引擎
│   ├── template_detector.py   # 模板自动检测
│   ├── formatting.py          # 排版格式规格（各模板独立 FormatSpec）
│   ├── formula_engine.py      # 公式处理引擎
│   ├── converter.py           # 统一转换接口
│   ├── quality_validator.py   # 文档质量验证
│   ├── quality_inspector.py   # 编译日志质量检查
│   ├── checker.py             # LaTeX 静态检查
│   ├── retryer.py             # 编译重试器
│   ├── input_validator.py     # 输入校验
│   ├── types.py               # 统一类型系统（Block 等）
│   ├── llm_factory.py         # LLM 工厂（统一从环境变量读密钥）
│   ├── nl_intake.py           # 自然语言接管
│   ├── nl_to_document.py      # PaperSpec → DocumentContent
│   └── utils/miktex.py        # MiKTeX 路径解析
├── composers/section_composer.py
├── gates/gate_system.py       # ★ Gate1–Gate4 质量门
├── templates/                 # 10 套模板 YAML + bibstyle/ BibTeX 样式
└── workflows/tex_typeset.py   # .tex 重新排版工作流
```

---

## 依赖

- Python 3.10+
- PyYAML、python-docx
- MiKTeX 或 TeX Live（`xelatex`、`bibtex`）
- 中文支持：`xeCJK` / `ctex`

```bash
pip install -r ../requirements.txt
```

---

## 许可

[MIT](../LICENSE) © 2026 Ave-Nir