"""
paper_pipeline —— 论文处理完整流程

输入一篇论文 → 生成4张不同结构的流程图(S0-S5) → 插入第1张到研究方法章节 → 排版PDF

核心分层：
  cli.py          → CLI 入口（仅负责参数解析，无业务逻辑）
  core/pipeline.py → 流程编排（Orchestrator，负责 Stage 调度与 Gate 串联）
  services/       → 服务层（DiagramService, TypesetService，封装底层 skill）
  models/         → 数据模型（全链路类型定义）
  config/         → 配置中心（环境变量 + YAML，零硬编码）
  gates/          → 质量门（输入/输出校验，证明链闭环）
  exceptions.py   → 统一异常体系
"""

__version__ = "1.0.0"
